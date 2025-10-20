# ./tools/r_tools/tools/git_tools.py
from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# Prosesshjelpere
# ──────────────────────────────────────────────────────────────────────────────

def _run_git(cwd: Path, *args: str) -> tuple[int, str]:
    """
    Kjør 'git <args>' og returner (rc, stdout+stderr).
    """
    proc = subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout

def _run_module_or_cli(tool: str, tool_args: list[str], cwd: Path) -> tuple[int, str]:
    """
    Kjør først 'python -m <tool> ...' (sikker PATH),
    fall tilbake til bare '<tool> ...' hvis det feiler å starte.
    Returnerer (rc, output).
    """
    # 1) python -m <tool>
    try:
        proc = subprocess.run(
            [sys.executable, "-m", tool, *tool_args],
            cwd=str(cwd),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        return proc.returncode, proc.stdout
    except FileNotFoundError:
        pass  # ekstremt usannsynlig (mangler python)

    # 2) bare CLI-navn
    proc = subprocess.run(
        [tool, *tool_args],
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    return proc.returncode, proc.stdout

# ──────────────────────────────────────────────────────────────────────────────
# Git-hjelpere
# ──────────────────────────────────────────────────────────────────────────────

def _ensure_repo(root: Path) -> None:
    rc, out = _run_git(root, "rev-parse", "--is-inside-work-tree")
    if rc != 0 or "true" not in (out or ""):
        raise RuntimeError(f"Ikke et git-repo: {root}")

def current_branch(root: Path) -> str:
    rc, out = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return ""
    return (out or "").strip()

def _is_clean(root: Path) -> bool:
    rc, out = _run_git(root, "status", "--porcelain")
    return rc == 0 and (out.strip() == "")

def list_branches(root: Path) -> list[str]:
    _ensure_repo(root)
    rc, out = _run_git(root, "branch", "--format", "%(refname:short)")
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]

def list_remotes(root: Path) -> list[str]:
    _ensure_repo(root)
    rc, out = _run_git(root, "remote")
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]

def status(root: Path) -> str:
    _ensure_repo(root)
    _, out = _run_git(root, "status", "-sb")
    return out

def diff(root: Path, staged: bool = False) -> str:
    _ensure_repo(root)
    args = ["diff"]
    if staged:
        args.append("--cached")
    _, out = _run_git(root, *args)
    return out

def log(root: Path, n: int = 10) -> str:
    _ensure_repo(root)
    _, out = _run_git(root, "log", f"-{n}", "--oneline", "--graph", "--decorate")
    return out

def fetch(root: Path, remote: str) -> str:
    _ensure_repo(root)
    _, out = _run_git(root, "fetch", remote)
    return out

def pull_rebase(root: Path, remote: str, branch: str, ff_only: bool = True) -> str:
    _ensure_repo(root)
    args = ["pull", "--ff-only" if ff_only else "--rebase", remote, branch]
    _, out = _run_git(root, *args)
    return out

def push(root: Path, remote: str, branch: str) -> str:
    _ensure_repo(root)
    _, out = _run_git(root, "push", remote, branch)
    return out

def switch(root: Path, branch: str) -> str:
    _ensure_repo(root)
    _, out = _run_git(root, "switch", branch)
    return out

def create_branch(root: Path, name: str, base: str | None = None) -> str:
    _ensure_repo(root)
    if base:
        _, out = _run_git(root, "switch", "-c", name, base)
    else:
        _, out = _run_git(root, "switch", "-c", name)
    return out

def merge_to(root: Path, source: str, target: str, ff_only: bool = True) -> str:
    _ensure_repo(root)
    rc, out = _run_git(root, "switch", target)
    if rc != 0:
        return out
    args = ["merge"]
    if ff_only:
        args.append("--ff-only")
    args.append(source)
    _, out2 = _run_git(root, *args)
    return out + out2

def add_commit(root: Path, message: str) -> str:
    _ensure_repo(root)
    if not message.strip():
        return "[git] Commit-melding kan ikke være tom.\n"
    _, out_a = _run_git(root, "add", "-A")
    _, out_c = _run_git(root, "commit", "-m", message)
    return out_a + out_c

def add_commit_push(root: Path, remote: str, branch: str, message: str) -> str:
    txt = add_commit(root, message)
    _, out_p = _run_git(root, "push", remote, branch)
    _, out_s = _run_git(root, "status", "-sb")
    return txt + out_p + out_s

# ──────────────────────────────────────────────────────────────────────────────
# Beskyttede branches / pre-push / stash&switch / resolve
# ──────────────────────────────────────────────────────────────────────────────

def _is_protected(branch: str, patterns: list[str]) -> bool:
    b = branch or ""
    for pat in patterns:
        pat = str(pat).strip()
        if not pat:
            continue
        if any(ch in pat for ch in "*?["):
            if fnmatch.fnmatch(b, pat):
                return True
        elif b == pat:
            return True
    return False

def pre_push_check(root: Path, run_tests: bool = False, mode: str = "strict") -> tuple[int, str]:
    """
    Kjør formaterings-/lint-/test-sjekker før push.

    mode:
      - "strict":      black --check må passere, ellers FAIL (default).
      - "warn":        black-avvik gir bare advarsel; ruff/pytest kan fortsatt stoppe.
      - "autoformat":  ved black-avvik kjør automatisk `black .` og fortsett; ruff/pytest kan stoppe.
    """
    _ensure_repo(root)

    def _run_tool(label: str, tool: str, tool_args: list[str]) -> tuple[int, str]:
        rc, out = _run_module_or_cli(tool, tool_args, root)
        return rc, f"▶ {label}\n{out}"

    overall_rc = 0
    outputs: list[str] = []
    reasons: list[str] = []

    # 1) Black --check
    black_rc, black_out = _run_tool("black --check .", "black", ["--check", "."])
    outputs.append(black_out)

    black_failed = black_rc != 0
    if black_failed:
        if mode == "autoformat":
            fmt_rc, fmt_out = _run_module_or_cli("black", ["."], root)
            outputs.append(f"▶ black . (autoformat)\n{fmt_out}")
            if fmt_rc == 0:
                black_failed = False
                reasons.append("autoformatted by black")
            else:
                overall_rc = overall_rc or fmt_rc
                reasons.append("black autoformat failed")
        elif mode == "warn":
            reasons.append("black found reformatting issues (warning only)")
            black_failed = False
        else:
            overall_rc = overall_rc or black_rc
            reasons.append("black --check failed")

    # 2) Ruff
    ruff_rc, ruff_out = _run_tool("ruff check .", "ruff", ["check", "."])
    outputs.append(ruff_out)
    if ruff_rc != 0:
        overall_rc = overall_rc or ruff_rc
        reasons.append("ruff failed")

    # 3) Pytest (valgfritt)
    if run_tests:
        py_rc, py_out = _run_tool("pytest -q", "pytest", ["-q"])
        outputs.append(py_out)
        if py_rc != 0:
            overall_rc = overall_rc or py_rc
            reasons.append("pytest failed")

    # Sammendrag
    if overall_rc == 0:
        summary = "Pre-push: OK"
        if reasons:
            summary += " (" + ", ".join(reasons) + ")"
    else:
        summary = "Pre-push: FAILED"
        if reasons:
            summary += " (" + ", ".join(reasons) + ")"

    outputs.append(summary + "\n")
    return overall_rc, "\n".join(outputs)

def stash_switch(root: Path, branch: str, message: str | None = None) -> str:
    _ensure_repo(root)
    msg = message or f"ui: auto-stash before switch to {branch}"
    _run_git(root, "stash", "push", "-u", "-m", msg)
    _run_git(root, "switch", "HEAD")
    _, out = _run_git(root, "switch", branch)
    return f"[git] stash push: {msg}\n" + out

def resolve_helper(root: Path) -> str:
    _ensure_repo(root)
    _, out = _run_git(root, "diff", "--name-only", "--diff-filter=U")
    files = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    guide: list[str] = []
    guide.append("=== Merge-konflikter ===")
    if not files:
        guide.append("Ingen filer i konflikt.")
    else:
        for f in files:
            guide.append(f" - {f}")
        guide.append("")
        guide.append("Veiviser:")
        guide.append("  1) Åpne filene over og løst markerte seksjoner (<<<<<<< ======= >>>>>>>).")
        guide.append("  2) Marker løst per fil:    git add <fil>")
        guide.append("  3) Fullfør merge:         git commit")
        guide.append("     (eller avbryt:         git merge --abort)")
        guide.append("")
        guide.append("Tips:")
        guide.append("  - Se diff:                git diff")
        guide.append("  - Se status:              git status -sb")
        guide.append("  - Aksepter 'theirs':      git checkout --theirs <fil> && git add <fil>")
        guide.append("  - Aksepter 'ours':        git checkout --ours  <fil> && git add <fil>")
    return "\n".join(guide) + "\n"

# ──────────────────────────────────────────────────────────────────────────────
# Kommandosentral
# ──────────────────────────────────────────────────────────────────────────────

def run_git(cfg: dict, action: str, args: dict) -> str:
    root = Path(cfg.get("project_root", ".")).resolve()
    gcfg = cfg.get("git") or {}
    remote = args.get("remote") or gcfg.get("default_remote", "origin")
    base = args.get("base") or gcfg.get("default_base", "main")
    branch = args.get("branch") or current_branch(root)
    ff_only = bool(args.get("ff_only", True))
    staged = bool(args.get("staged", False))
    n = int(args.get("n", 10))

    protected_patterns = list(gcfg.get("protected_branches", ["main", "master", "release/*"]))

    if action == "status":
        return status(root)
    if action == "branches":
        cur = current_branch(root)
        return "\n".join(list_branches(root)) + (f"\n(current: {cur})\n" if cur else "\n")
    if action == "remotes":
        return "\n".join(list_remotes(root)) + "\n"
    if action == "fetch":
        return fetch(root, remote)
    if action == "pull":
        return pull_rebase(root, remote, branch or base, ff_only=True)
    if action == "push":
        if _is_protected(branch, protected_patterns) and not bool(args.get("confirm", False)):
            return f"[git] '{branch}' er beskyttet. Sett confirm=true for å pushe.\n"
        if bool(args.get("precheck", False)):
            mode = str(args.get("precheck_mode") or "strict").lower()
            rc, txt = pre_push_check(root, bool(args.get("precheck_tests", False)), mode=mode)
            if rc != 0:
                return txt + "[git] Pre-push sjekk feilet. Avbryter push.\n"
        return push(root, remote, branch)
    if action == "switch":
        return switch(root, branch)
    if action == "stash_switch":
        return stash_switch(root, branch, args.get("message"))
    if action == "create":
        return create_branch(root, branch, base=args.get("base"))
    if action == "merge":
        if not _is_clean(root):
            return "[git] Arbeidskatalogen er ikke ren – commit/stash endringer før merge.\n"
        tgt = args.get("target") or branch or base
        src = args.get("source") or current_branch(root)
        if _is_protected(tgt, protected_patterns) and not bool(args.get("confirm", False)):
            return f"[git] Target '{tgt}' er beskyttet. Sett confirm=true for å bekrefte merge.\n"
        return merge_to(root, src, tgt, ff_only=ff_only)
    if action == "acp":
        message = args.get("message") or ""
        if _is_protected(branch, protected_patterns) and not bool(args.get("confirm", False)):
            return f"[git] '{branch}' er beskyttet. Sett confirm=true for ACP.\n"
        out = add_commit(root, message)
        if bool(args.get("precheck", False)):
            mode = str(args.get("precheck_mode") or "strict").lower()
            rc, txt = pre_push_check(root, bool(args.get("precheck_tests", False)), mode=mode)
            out += txt
            if rc != 0:
                return out + "[git] Pre-push sjekk feilet. Avbryter push.\n"
        _, out_p = _run_git(root, "push", remote, branch)
        _, out_s = _run_git(root, "status", "-sb")
        return out + out_p + out_s
    if action == "diff":
        return diff(root, staged=staged)
    if action == "log":
        return log(root, n=n)
    if action == "sync":
        txt = fetch(root, remote)
        txt += pull_rebase(root, remote, branch or base, ff_only=True)
        return txt
    if action == "resolve":
        return resolve_helper(root)

    return f"[git] Ukjent action: {action}\n"
