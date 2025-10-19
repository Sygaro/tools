# ./tools/r_tools/tools/gh_raw.py
from __future__ import annotations

import json
import os
from collections.abc import Iterable
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
    # /repos/{owner}/{repo}/branches/{branch} gir commit.sha
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

def run_gh_raw(
    cfg: dict,
    *,
    wrap_read: bool = False,
    as_json: bool | None = None,  # behold for bakoverkomp., men brukes ikke lenger
) -> None:
    """
    Les 'gh_raw' fra cfg og skriv enten:
      - raw.githubusercontent.com-URLer (default), eller
      - en /read(urls:[ "...blob/<commit>/path", ... ])-blokk når wrap_read=True.

    Støtter gh_raw.user, gh_raw.repo, gh_raw.branch, gh_raw.path_prefix (+ ev. gh_raw.wrap_read).
    """
    gh = cfg.get("gh_raw", {}) or {}
    user = gh.get("user")
    repo = gh.get("repo")
    branch = gh.get("branch", "main")
    path_prefix = (gh.get("path_prefix") or "").strip()
    token = os.environ.get("GITHUB_TOKEN")

    # Tillat at config også kan bestemme wrapping hvis UI ikke sendte flagg
    wrap_read = bool(wrap_read or gh.get("wrap_read", False))

    if not user or not repo:
        print("gh_raw: mangler 'user' eller 'repo' i config.")
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
