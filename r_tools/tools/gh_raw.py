# ./tools/r_tools/tools/gh_raw.py
from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def _req(url: str, token: str | None) -> dict[str, Any]:
    headers = {"User-Agent": "r_tools/gh_raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = Request(url, headers=headers)
    with urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _fetch_tree(user: str, repo: str, ref: str, token: str | None) -> dict[str, Any]:
    """
    Hent Git tree for gitt ref (branch/commit). Bruker GitHub API v3.
    """
    url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{ref}?recursive=1"
    try:
        return _req(url, token)
    except HTTPError as e:
        msg = f"HTTP {e.code} for {url}. "
        if e.code == 404:
            msg += "Sjekk at user/repo/branch stemmer, og at ref/branch eksisterer. " "Er repo privat? Sett GITHUB_TOKEN i miljøet."
        raise RuntimeError(msg) from e
    except URLError as e:
        raise RuntimeError(f"Nettverksfeil mot {url}: {e.reason}") from e

def _resolve_commit_sha(user: str, repo: str, branch: str, token: str | None) -> str:
    """
    Slå opp siste commit-SHA for en branch.
    """
    url = f"https://api.github.com/repos/{user}/{repo}/branches/{branch}"
    try:
        data = _req(url, token)
        sha = (data.get("commit") or {}).get("sha")
        if not sha:
            raise RuntimeError("Uventet svar ved SHA-oppslag (mangler commit.sha).")
        return sha
    except HTTPError as e:
        # fallback: /commits/{branch}
        if e.code != 404:
            raise
        data = _req(f"https://api.github.com/repos/{user}/{repo}/commits/{branch}", token)
        sha = data.get("sha")
        if not sha:
            raise RuntimeError("Uventet svar ved SHA-oppslag (fallback mangler sha).")
        return sha

def _filter_paths(nodes: Iterable[dict[str, Any]], path_prefix: str | None) -> list[str]:
    out: list[str] = []
    pre = (path_prefix or "").strip().rstrip("/")
    for n in nodes:
        if n.get("type") != "blob":
            continue
        p = n.get("path", "")
        if not p:
            continue
        if pre:
            if p == pre or p.startswith(pre + "/"):
                out.append(p)
        else:
            out.append(p)
    return out

# ---------- Prosjekt-drevet oppløsning av owner/repo/branch ----------

_GH_SSH_RE = re.compile(r"^git@github\.com:(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", re.IGNORECASE)
_GH_HTTPS_RE = re.compile(r"^https://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?$", re.IGNORECASE)

def _parse_github_remote(remote_url: str) -> tuple[str, str]:
    """
    Parse 'git remote get-url <remote>' for GitHub → (owner, repo)
    Støtter SSH og HTTPS. Kaster ValueError dersom URL ikke peker til github.com.
    """
    s = (remote_url or "").strip()
    m = _GH_SSH_RE.match(s) or _GH_HTTPS_RE.match(s)
    if not m:
        raise ValueError(f"Ikke en GitHub-remote: {remote_url!r}")
    owner = m.group("owner")
    repo = m.group("repo")
    return owner, repo

def _git(root: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=str(root), text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    return proc.returncode, proc.stdout

def resolve_github_from_project(root: Path, remote: str = "origin") -> tuple[str, str, str]:
    """
    Returner (owner, repo, remote_url) for gitt prosjekt-root og remote.
    Kaster ved ikke-git eller hvis remote ikke peker til github.com.
    """
    rc, out = _git(root, "rev-parse", "--is-inside-work-tree")
    if rc != 0 or "true" not in (out or ""):
        raise RuntimeError(f"Ikke et git-repo: {root}")
    rc, url = _git(root, "remote", "get-url", remote)
    if rc != 0:
        raise RuntimeError(f"Kunne ikke hente remote '{remote}' i {root}")
    owner, repo = _parse_github_remote((url or "").strip())
    return owner, repo, (url or "").strip()

# ---------- Hovedkjøring ----------

def run_gh_raw(
    cfg: dict,
    *,
    wrap_read: bool = False,
    as_json: bool | None = None,  # behold for bakoverkomp., men brukes ikke lenger
) -> None:
    """
    To moduser:
      A) Manuell (som før): cfg['gh_raw'] må inneholde user, repo, branch (og ev. path_prefix)
      B) Prosjekt-drevet: cfg['gh_raw'] kan mangle user/repo, men ha 'project_root' og 'remote'.
         Da slås owner/repo opp via git, og branch kan gis eller hentes fra cfg['gh_raw']['branch'].

    Output:
      - rå 'raw.githubusercontent.com'-URLer (default), eller
      - en /read(urls: [ "…blob/<commit>/path", … ])-blokk når wrap_read=True.
    """
    gh = cfg.get("gh_raw", {}) or {}
    token = os.environ.get("GITHUB_TOKEN")
    path_prefix = (gh.get("path_prefix") or "").strip()

    user = gh.get("user")
    repo = gh.get("repo")
    branch = gh.get("branch", "main")

    # Prosjekt-drevet fallback (hvis user/repo ikke er satt)
    if not user or not repo:
        project_root_str = (gh.get("project_root") or "").strip()
        remote_name = gh.get("remote", "origin")
        if project_root_str:
            project_root = Path(project_root_str).resolve()
            owner, repo_name, _remote_url = resolve_github_from_project(project_root, remote_name)
            user = user or owner
            repo = repo or repo_name
        # ellers: manuell modus uten prosjekt

    if not user or not repo:
        print("gh_raw: mangler 'user' eller 'repo' (hverken manuell konfig eller prosjekt-drevet oppslag ga verdi).")
        return

    tree = _fetch_tree(user, repo, branch, token)
    nodes: list[dict[str, Any]] = list(tree.get("tree", []))
    if not nodes:
        print("gh_raw: tomt tre eller mangler 'tree' i responsen.")
        return

    # Filtrer paths
    paths = _filter_paths(nodes, path_prefix)

    if tree.get("truncated"):
        print("⚠ gh_raw: Result list is truncated by GitHub API; output may be incomplete.")

    if not wrap_read:
        # Standard: RAW-URLer
        base = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/"
        for p in paths:
            print(base + p)
        return

    # Wrap som /read(urls:[ ... ]) med blob/<commit>/...
    commit_sha = _resolve_commit_sha(user, repo, branch, token)
    blob_base = f"https://github.com/{user}/{repo}/blob/{commit_sha}/"

    print("/read(urls: [")
    for i, p in enumerate(paths):
        sep = "," if i < len(paths) - 1 else ""
        print(f'  "{blob_base}{p}"{sep}')
    print("])")
