# ./tools/r_tools/tools/git_tools.py
from __future__ import annotations

import fnmatch
import subprocess
import sys
from pathlib import Path

# ────────────────────────────────────────────────────────────────────────────
# Prosess-hjelpere
# ────────────────────────────────────────────────────────────────────────────

def _run_cmd(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """Kjør en kommando og returner (rc, stdout)."""
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout or ""

def _run_module_or_cli(module: str, args: list[str], cwd: Path) -> tuple[int, str]:
    """
    Prøv først `python -m <module> ...` (unngår PATH-trøbbel når verktøy ligger i venv),
    fall tilbake til ren CLI hvis det ikke finnes.
    """
    try:
        return _run_cmd([sys.executable, "-m", module, *args], cwd)
    except FileNotFoundError:
        return _run_cmd([module, *args], cwd)

# ────────────────────────────────────────────────────────────────────────────
# Git-hjelpere
# ────────────────────────────────────────────────────────────────────────────

def _git(cwd: Path, *args: str) -> tuple[int, str]:
    return _run_cmd(["git", *args], cwd)

def _ensure_repo(root: Path) -> None:
    rc, out = _git(root, "rev-parse", "--is-inside-work-tree")
    if rc != 0 or "true" not in (out or ""):
        raise RuntimeError(f"Ikke et git-repo: {root}")

def current_branch(root: Path) -> str:
    rc, out = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return (out or "").strip() if rc == 0 else ""

def _is_clean(root: Path) -> bool:
    rc, out = _git(root, "status", "--porcelain")
    return rc == 0 and (out.strip() == "")

def list_branches(root: Path) -> list[str]:
    _ensure_repo(root)
    rc, out = _git(root, "branch", "--format", "%(refname:short)")
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip()] if rc == 0 else []

def list_remotes(root: Path) -> list[str]:
    _ensure_repo(root)
    rc, out = _git(root, "remote")
    return [ln.strip() for ln in (out or "").splitlines() if ln.strip()] if rc == 0 else []

def status(root: Path) -> str:
    _ensure_repo(root)
    _, out = _git(root, "status", "-sb")
    return out

def diff(root: Path, staged: bool = False) -> str:
    _ensure_repo(root)
    args = ["diff"]
    if staged:
        args.append("--cached")
    _, out = _git(root, *args)
    return out

def log(root: Path, n: int = 10) -> str:
    _ensure_repo(root)
    _, out = _git(root, "log", f"-{n}", "--oneline", "--graph", "--decorate")
    return out

def fetch(root: Path, remote: str) -> str:
    _ensure_repo(root)
    _, out = _git(root, "fetch", remote)
    return out

def pull_rebase(root: Path, remote: str, branch: str, ff_only: bool = True) -> str:
    _ensure_repo(root)
    args = ["pull", "--ff-only" if ff_only else "--rebase", remote, branch]
    _, out = _git(root, *args)
    return out

def push(root: Path, remote: str, branch: str) -> str:
    _ensure_repo(root)
    _, out = _git(root, "push", remote, branch)
    return out

def switch(root: Path, branch: str) -> str:
    _ensure_repo(root)
    _, out = _git(root, "switch", branch)
    return out

def create_branch(root: Path, name: str, base: str | None = None) -> str:
    _ensure_repo(root)
    if base:
        _, out = _git(root, "switch", "-c", name, base)
    else:
        _, out = _git(root, "switch", "-c", name)
    return out

def merge_to(root: Path, source: str, target: str, ff_only: bool = True) -> str:
    _ensure_repo(root)
    rc, out = _git(root, "switch", target)
    if rc != 0:
        return out
    args = ["merge"]
    if ff_only:
        args.append("--ff-only")
    args.append(source)
    _, out2 = _git(root, *args)
    return out + out2

def add_commit(root: Path, message: str) -> str:
    _ensure_repo(root)
    if not message.strip():
        return "[git] Commit-melding kan ikke være tom.\n"
    _, out_a = _git(root, "add", "-A")
    _, out_c = _git(root, "commit", "-m", message)
    return out_a + out_c

def add_commit_push(root: Path, remote: str, branch: str, message: str) -> str:
    txt = add_commit(root, message)
    _, out_p = _git(root, "push", remote, branch)
    _, out_s = _git(root, "status", "-sb")
    return txt + out_p + out_s

# ────────────────────────────────────────────────────────────────────────────
# Beskyttede grener + pre-push-sjekk
# ────────────────────────────────────────────────────────────────────────────

def _is_protected(branch: str, patterns: list[str]) -> bool:
    b = branch or ""
    for pat in patterns:
        pat = str(pat).strip()
        if not pat:
            continue
        if any(x in pat for x in "*?["):
            if fnmatch.fnmatch(b, pat):
                return True
        elif b == pat:
            return True
    return False

def _cfg_list(v: object) -> list[str]:
    """Aksepterer både liste og kommaseparert streng."""
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []

def pre_push_check(root: Path, cfg: dict, run_tests: bool = False, mode: str = "strict") -> tuple[int, str]:
    """
    Kjør Black/Ruff/Pytest før push.
    - Bruker *samme* flagg som format_config.json (black/ruff), forutsatt at de finnes.
    - mode:
        - "strict":  black --check (feiler hvis endringer kreves)
        - "warn":    black --check, men RC ignoreres (kun varsel)
        - "autoformat": kjør black (formatter), deretter ruff (uten --fix)
    """
    _ensure_repo(root)
    fmt = cfg.get("format") or {}
    black_cfg = fmt.get("black") or {}
    ruff_cfg = fmt.get("ruff") or {}

    # ---- Black-argumenter fra config
    black_args: list[str] = []
    # Ny modell
    if black_cfg.get("line_length") is not None:
        black_args += ["--line-length", str(int(black_cfg["line_length"]))]
    target_csv = black_cfg.get("target") or ""
    if isinstance(target_csv, str) and target_csv.strip():
        for tv in [t.strip() for t in target_csv.split(",") if t.strip()]:
            black_args += ["--target-version", tv]
    # Bakoverkompatibelt
    black_args += _cfg_list(black_cfg.get("args"))

    black_paths = _cfg_list(black_cfg.get("paths")) or ["./"]

    # ---- Ruff-argumenter fra config (men uten --fix i pre-push)
    ruff_args = _cfg_list(ruff_cfg.get("args"))
    if ruff_args:
        # Fjern destruktive flagg om de finnes
        ruff_args = [a for a in ruff_args if a not in {"--fix", "--unsafe-fixes"}]
    else:
        ruff_args = ["check", "./"]
        sel = ruff_cfg.get("select") or ""
        ign = ruff_cfg.get("ignore") or ""
        if sel:
            ruff_args += ["--select", sel if isinstance(sel, str) else ",".join(_cfg_list(sel))]
        if ign:
            ruff_args += ["--ignore", ign if isinstance(ign, str) else ",".join(_cfg_list(ign))]

    steps: list[tuple[list[str], str]] = []

    if mode == "autoformat":
        steps.append((["black", *black_args, *black_paths], "black ."))  # formatterer
    else:
        steps.append((["black", "--check", *black_args, *black_paths], "black --check ."))

    steps.append((["ruff", *ruff_args], "ruff check"))

    if run_tests:
        steps.append((["pytest", "-q"], "pytest -q"))

    rc_total = 0
    out_all: list[str] = []
    for raw_cmd, label in steps:
        tool = raw_cmd[0]
        args = raw_cmd[1:]

        # Kjør via python -m der det er naturlig (black/ruff/pytest), ellers CLI.
        if tool in {"black", "ruff", "pytest"}:
            rc, out = _run_module_or_cli(tool, args, root)
        else:
            rc, out = _run_cmd([tool] + args, root)

        out_all.append(f"▶ {label}\n{out}")

        if mode == "warn" and "black --check" in label:
            # Ikke la black --check stoppe push i warn-modus
            continue

        if rc != 0 and rc_total == 0:
            rc_total = rc

    return rc_total, "\n".join(out_all) + ("\n" if out_all else "")

# ────────────────────────────────────────────────────────────────────────────
# UI-kommandoer
# ────────────────────────────────────────────────────────────────────────────

def stash_switch(root: Path, branch: str, message: str | None = None) -> str:
    _ensure_repo(root)
    msg = message or f"ui: auto-stash before switch to {branch}"
    _git(root, "stash", "push", "-u", "-m", msg)
    _git(root, "switch", "HEAD")
    _, out = _git(root, "switch", branch)
    return f"[git] stash push: {msg}\n" + out

def resolve_helper(root: Path) -> str:
    _ensure_repo(root)
    _, out = _git(root, "diff", "--name-only", "--diff-filter=U")
    files = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    guide: list[str] = ["=== Merge-konflikter ==="]
    if not files:
        guide.append("Ingen filer i konflikt.")
    else:
        for f in files:
            guide.append(f" - {f}")
        guide += [
            "",
            "Veiviser:",
            "  1) Åpne filene over og løst markerte seksjoner (<<<<<<< ======= >>>>>>>).",
            "  2) Marker løst per fil:    git add <fil>",
            "  3) Fullfør merge:         git commit",
            "     (eller avbryt:         git merge --abort)",
            "",
            "Tips:",
            "  - Se diff:                git diff",
            "  - Se status:              git status -sb",
            "  - Aksepter 'theirs':      git checkout --theirs <fil> && git add <fil>",
            "  - Aksepter 'ours':        git checkout --ours  <fil> && git add <fil>",
        ]
    return "\n".join(guide) + "\n"

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
            mode = str(args.get("precheck_mode") or gcfg.get("precheck_mode") or "strict").lower()
            rc, txt = pre_push_check(root, cfg, bool(args.get("precheck_tests", False)), mode=mode)
            if rc != 0:
                return txt + "Pre-push: FAILED\n[git] Pre-push sjekk feilet. Avbryter push.\n"
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
            mode = str(args.get("precheck_mode") or gcfg.get("precheck_mode") or "strict").lower()
            rc, txt = pre_push_check(root, cfg, bool(args.get("precheck_tests", False)), mode=mode)
            out += txt
            if rc != 0:
                return out + "Pre-push: FAILED\n[git] Pre-push sjekk feilet. Avbryter push.\n"
        _, out_p = _git(root, "push", remote, branch)
        _, out_s = _git(root, "status", "-sb")
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
