# /home/reidar/tools/r_tools/tools/gh_raw.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def _fetch_tree(user: str, repo: str, branch: str, token: str | None) -> Dict[str, Any]:
    """
    Hent Git tree for gitt branch. Bruker GitHub API v3.
    - token (valgfri): bruk GITHUB_TOKEN for private repo/høyere rate-limit.
    """
    url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{branch}?recursive=1"
    headers = {"User-Agent": "r_tools/gh_raw"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        msg = f"HTTP {e.code} for {url}. "
        if e.code == 404:
            msg += (
                "Sjekk at user/repo/branch stemmer, og at branchen eksisterer. "
                "Er repo privat? Sett GITHUB_TOKEN i miljøet."
            )
        raise RuntimeError(msg) from e
    except URLError as e:
        raise RuntimeError(f"Nettverksfeil mot {url}: {e.reason}") from e

def run_gh_raw(cfg: Dict, as_json: bool = False) -> None:
    """
    Les 'gh_raw' fra cfg og skriv raw.githubusercontent-URLer for alle blobs i treet.
    Respekterer evt. path_prefix for å begrense output.
    """
    gh = cfg.get("gh_raw", {})
    user = gh.get("user")
    repo = gh.get("repo")
    branch = gh.get("branch", "main")
    path_prefix = (gh.get("path_prefix") or "").rstrip("/")
    token = os.environ.get("GITHUB_TOKEN")

    if not user or not repo:
        print("gh_raw: mangler 'user' eller 'repo' i config.")
        return

    tree = _fetch_tree(user, repo, branch, token)
    nodes: List[Dict[str, Any]] = list(tree.get("tree", []))
    if not nodes:
        print("gh_raw: tomt tre eller mangler 'tree' i responsen.")
        return

    base = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/"
    out: List[str] = []
    for node in nodes:
        if node.get("type") != "blob":
            continue
        p = node.get("path", "")
        if path_prefix:
            if p == path_prefix or p.startswith(path_prefix + "/"):
                out.append(base + p)
        else:
            out.append(base + p)

    if as_json:
        print(json.dumps(out, indent=2))
    else:
        for u in out:
            print(u)
