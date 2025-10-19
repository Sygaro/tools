# ./tools/r_tools/tools/git_tools.py
from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

def _run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout

def _git(cwd: Path, *args: str) -> tuple[int, str]:
    return _run(["git", *args], cwd)

def _ensure_repo(root: Path) -> None:
    rc, out = _git(root, "rev-parse", "--is-inside-work-tree")
    if rc != 0 or "true" not in (out or ""):
        raise RuntimeError(f"Ikke et git-repo: {root}")

def current_branch(root: Path) -> str:
    rc, out = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0:
        return ""
    return (out or "").strip()

def _is_clean(root: Path) -> bool:
    rc, out = _git(root, "status", "--porcelain")
    return rc == 0 and (out.strip() == "")

def list_branches(root: Path) -> list[str]:
    _ensure_repo(root)
    rc, out = _git(root, "branch", "--format", "%(refname:short)")
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]

def list_remotes(root: Path) -> list[str]:
    _ensure_repo(root)
    rc, out = _git(root, "remote")
    if rc != 0:
        return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]

def status(root: Path) -> str:
    _ensure_repo(root)
    _, out = _git(root, "status", "-sb")
    return out

def diff(root: Path, staged: bool = False) -> str:
    _ensure_repo(root)
    args = ["diff"]
    if staged:
        args.append("--cached")
    rc, out = _git(root, *args)
    return out

def log(root: Path, n: int = 10) -> str:
    _ensure_repo(root)
    rc, out = _git(root, "log", f"-{n}", "--oneline", "--graph", "--decorate")
    return out

def fetch(root: Path, remote: str) -> str:
    _ensure_repo(root)
    rc, out = _git(root, "fetch", remote)
    return out

def pull_rebase(root: Path, remote: str, branch: str, ff_only: bool = True) -> str:
    _ensure_repo(root)
    args = ["pull", "--ff-only" if ff_only else "--rebase", remote, branch]
    rc, out = _git(root, *args)
    return out

def push(root: Path, remote: str, branch: str) -> str:
    _ensure_repo(root)
    rc, out = _git(root, "push", remote, branch)
    return out

def switch(root: Path, branch: str) -> str:
    _ensure_repo(root)
    rc, out = _git(root, "switch", branch)
    return out

def create_branch(root: Path, name: str, base: str | None = None) -> str:
    _ensure_repo(root)
    if base:
        rc, out = _git(root, "switch", "-c", name, base)
    else:
        rc, out = _git(root, "switch", "-c", name)
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
    rc, out2 = _git(root, *args)
    return out + out2

def add_commit(root: Path, message: str) -> str:
    _ensure_repo(root)
    if not message.strip():
        return "[git] Commit-melding kan ikke være tom.\n"
    rc_a, out_a = _git(root, "add", "-A")
    rc_c, out_c = _git(root, "commit", "-m", message)
    # git kan returnere rc=1 ved "ingenting å committe"
    return out_a + out_c

def add_commit_push(root: Path, remote: str, branch: str, message: str) -> str:
    txt = add_commit(root, message)
    rc_p, out_p = _git(root, "push", remote, branch)
    rc_s, out_s = _git(root, "status", "-sb")
    return txt + out_p + out_s

# ---------- Nytt: glob-beskyttelse + pre-push sjekk + stash&switch + resolve helper ----------

def _is_protected(branch: str, patterns: list[str]) -> bool:
    b = branch or ""
    for pat in patterns:
        pat = str(pat).strip()
        if not pat:
            continue
        # eksakt navn eller glob (release/* etc.)
        if "*" in pat or "?" in pat or "[" in pat:
            if fnmatch.fnmatch(b, pat):
                return True
        elif b == pat:
            return True
    return False

def pre_push_check(root: Path, run_tests: bool = False) -> tuple[int, str]:
    """
    Kjør Black --check og Ruff check (og valgfritt pytest).
    Returnerer (rc, samlet_output). rc!=0 betyr stopp push.
    """
    _ensure_repo(root)
    steps: list[tuple[list[str], str]] = [
        (["black", "--check", "."], "black --check ."),
        (["ruff", "check", "."], "ruff check ."),
    ]
    if run_tests:
        steps.append((["pytest", "-q"], "pytest -q"))

    rc_total = 0
    out_all: list[str] = []
    for cmd, label in steps:
        rc, out = _run(cmd, root)
        out_all.append(f"▶ {label}\n{out}")
        if rc != 0 and rc_total == 0:
            rc_total = rc
    return rc_total, "\n".join(out_all) + ("\n" if out_all else "")

def stash_switch(root: Path, branch: str, message: str | None = None) -> str:
    """
    Legg bort lokale endringer og bytt branch.
    """
    _ensure_repo(root)
    msg = message or f"ui: auto-stash before switch to {branch}"
    _git(root, "stash", "push", "-u", "-m", msg)  # ignorér rc – tom stash gir rc=0 med "No local changes"
    rc, out = _git(root, "switch", branch)
    return f"[git] stash push: {msg}\n" + out

def resolve_helper(root: Path) -> str:
    """
    Vis filer i konflikt + en kort veiviser for løsning/abort.
    """
    _ensure_repo(root)
    rc, out = _git(root, "diff", "--name-only", "--diff-filter=U")
    files = [ln.strip() for ln in (out or "").splitlines() if ln.strip()]
    guide = []
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
        guide.addend("  3) Fullfør merge:         git commit")
        guide.append("     (eller avbryt:         git merge --abort)")
        guide.append("")
        guide.append("Tips:")
        guide.append("  - Se diff:                git diff")
        guide.append("  - Se status:              git status -sb")
        guide.append("  - Aksepter 'theirs':      git checkout --theirs <fil> && git add <fil>")
        guide.append("  - Aksepter 'ours':        git checkout --ours  <fil> && git add <fil>")
    return "\n".join(guide) + "\n"

def run_git(cfg: dict, action: str, args: dict) -> str:
    """
    action: status | branches | remotes | fetch | pull | push | switch | create | merge | acp | diff | log | sync
            | stash_switch | resolve
    args:   remote, branch, base, message, ff_only(bool), staged(bool), n(int),
            precheck(bool), precheck_tests(bool), target, source
    """
    root = Path(cfg.get("project_root", ".")).resolve()
    gcfg = cfg.get("git") or {}
    remote = args.get("remote") or gcfg.get("default_remote", "origin")
    base = args.get("base") or gcfg.get("default_base", "main")
    branch = args.get("branch") or current_branch(root)
    ff_only = bool(args.get("ff_only", True))
    staged = bool(args.get("staged", False))
    n = int(args.get("n", 10))

    # beskyttede mønstre – støtte for glob (release/*)
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
            rc, txt = pre_push_check(root, bool(args.get("precheck_tests", False)))
            if rc != 0:
                return txt + "[git] Pre-push sjekk feilet. Avbryter push.\n"
        return push(root, remote, branch)
    if action == "switch":
        out = switch(root, branch)
        return out
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
        # Commit først, deretter (ev.) precheck, til slutt push
        message = args.get("message") or ""
        if _is_protected(branch, protected_patterns) and not bool(args.get("confirm", False)):
            return f"[git] '{branch}' er beskyttet. Sett confirm=true for ACP.\n"
        out = add_commit(root, message)
        if bool(args.get("precheck", False)):
            rc, txt = pre_push_check(root, bool(args.get("precheck_tests", False)))
            out += txt
            if rc != 0:
                return out + "[git] Pre-push sjekk feilet. Avbryter push.\n"
        rc_p, out_p = _git(root, "push", remote, branch)
        rc_s, out_s = _git(root, "status", "-sb")
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
