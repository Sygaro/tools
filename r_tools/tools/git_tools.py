# ./tools/r_tools/tools/git_tools.py
from __future__ import annotations
import subprocess, shlex
from pathlib import Path
from typing import Dict, List, Tuple, Optional

def _run(cmd: List[str], cwd: Path) -> Tuple[int, str]:
    proc = subprocess.run(cmd, cwd=str(cwd), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout

def _git(cwd: Path, *args: str) -> Tuple[int, str]:
    return _run(["git", *args], cwd)

def _ensure_repo(root: Path) -> None:
    rc, out = _git(root, "rev-parse", "--is-inside-work-tree")
    if rc != 0 or "true" not in (out or ""):
        raise RuntimeError(f"Ikke et git-repo: {root}")

def _current_branch(root: Path) -> str:
    rc, out = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if rc != 0: return ""
    return (out or "").strip()

def _is_clean(root: Path) -> bool:
    rc, out = _git(root, "status", "--porcelain")
    return rc == 0 and (out.strip() == "")

def list_branches(root: Path) -> List[str]:
    _ensure_repo(root)
    rc, out = _git(root, "branch", "--format", "%(refname:short)")
    if rc != 0: return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]

def list_remotes(root: Path) -> List[str]:
    _ensure_repo(root)
    rc, out = _git(root, "remote")
    if rc != 0: return []
    return [ln.strip() for ln in out.splitlines() if ln.strip()]

def status(root: Path) -> str:
    _ensure_repo(root)
    _, out = _git(root, "status", "-sb")
    return out

def diff(root: Path, staged: bool = False) -> str:
    _ensure_repo(root)
    args = ["diff", "--color"]
    if staged: args.append("--cached")
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
    args = ["pull", "--rebase" if not ff_only else "--ff-only", remote, branch]
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

def create_branch(root: Path, name: str, base: Optional[str] = None) -> str:
    _ensure_repo(root)
    if base:
        rc, out = _git(root, "switch", "-c", name, base)
    else:
        rc, out = _git(root, "switch", "-c", name)
    return out

def merge_to(root: Path, source: str, target: str, ff_only: bool = True) -> str:
    _ensure_repo(root)
    # Bytt til target
    rc, out = _git(root, "switch", target)
    if rc != 0: return out
    # Merge
    args = ["merge"]
    if ff_only: args.append("--ff-only")
    args.append(source)
    rc, out2 = _git(root, *args)
    return out + out2

def add_commit_push(root: Path, remote: str, branch: str, message: str) -> str:
    _ensure_repo(root)
    if not message.strip():
        return "[git] Commit-melding kan ikke være tom.\n"
    rc, out_a = _git(root, "add", "-A")
    rc2, out_c = _git(root, "commit", "-m", message)
    # commit kan returnere rc=1 ved "ingenting å committe"; håndter mykt:
    rc3, out_p = _git(root, "push", remote, branch)
    rc4, out_s = _git(root, "status", "-sb")
    return out_a + out_c + out_p + out_s

def run_git(cfg: Dict, action: str, args: Dict) -> str:
    """
    action: status | branches | remotes | fetch | pull | push | switch | create | merge | acp | diff | log | sync
    args:   remote, branch, base, message, ff_only(bool), staged(bool), n(int)
    """
    root = Path(cfg.get("project_root", ".")).resolve()
    gcfg = (cfg.get("git") or {})
    remote = args.get("remote") or gcfg.get("default_remote", "origin")
    base   = args.get("base")   or gcfg.get("default_base", "main")
    branch = args.get("branch") or _current_branch(root)
    ff_only = bool(args.get("ff_only", True))
    staged = bool(args.get("staged", False))
    n = int(args.get("n", 10))

    # beskyttede branches
    protected = set(gcfg.get("protected_branches", ["main", "master"]))
    if action in {"merge","push","acp","sync","pull"} and branch in (None, ""):
        branch = _current_branch(root)

    if action == "status":
        return status(root)
    if action == "branches":
        return "\n".join(list_branches(root)) + "\n"
    if action == "remotes":
        return "\n".join(list_remotes(root)) + "\n"
    if action == "fetch":
        return fetch(root, remote)
    if action == "pull":
        return pull_rebase(root, remote, branch or base, ff_only=True)
    if action == "push":
        if branch in protected and not bool(args.get("confirm", False)):
            return f"[git] '{branch}' er beskyttet. Bruk confirm=true for å pushe.\n"
        return push(root, remote, branch)
    if action == "switch":
        return switch(root, branch)
    if action == "create":
        return create_branch(root, branch, base=args.get("base"))
    if action == "merge":
        if not _is_clean(root):
            return "[git] Arbeidskatalogen er ikke ren – commit/stash endringer før merge.\n"
        if branch in protected and not bool(args.get("confirm", False)):
            return f"[git] Target '{branch}' er beskyttet. Bruk confirm=true for å bekrefte merge.\n"
        src = args.get("source") or _current_branch(root)
        tgt = args.get("target") or branch or base
        return merge_to(root, src, tgt, ff_only=ff_only)
    if action == "acp":
        if branch in protected and not bool(args.get("confirm", False)):
            return f"[git] '{branch}' er beskyttet. Bruk confirm=true for ACP til beskyttet branch.\n"
        msg = args.get("message") or ""
        return add_commit_push(root, remote, branch, msg)
    if action == "diff":
        return diff(root, staged=staged)
    if action == "log":
        return log(root, n=n)
    if action == "sync":
        txt = fetch(root, remote)
        txt += pull_rebase(root, remote, branch or base, ff_only=True)
        return txt
    return f"[git] Ukjent action: {action}\n"
