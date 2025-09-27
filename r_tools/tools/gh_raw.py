# /home/reidar/tools/r_tools/tools/gh_raw.py
"""
Erstatter tools/get_raw_links.sh – ingen jq/curl nødvendig.
Config: cfg['gh_raw'] {user, repo, branch, path_prefix}
"""
from __future__ import annotations
from urllib.request import urlopen, Request
import json
from typing import Dict, List

def _fetch_tree(user: str, repo: str, branch: str) -> List[Dict]:
    url = f"https://api.github.com/repos/{user}/{repo}/git/trees/{branch}?recursive=1"
    req = Request(url, headers={"User-Agent": "r-tools"})
    with urlopen(req, timeout=30) as resp:
        data = resp.read()
    payload = json.loads(data.decode("utf-8"))
    return payload.get("tree", [])

def run_gh_raw(cfg: Dict, as_json: bool = False) -> None:
    g = cfg.get("gh_raw", {})
    user = g.get("user", "")
    repo = g.get("repo", "")
    branch = g.get("branch", "main")
    prefix = g.get("path_prefix", "") or ""

    tree = _fetch_tree(user, repo, branch)
    paths = [n["path"] for n in tree if n.get("type") == "blob" and (not prefix or n["path"].startswith(prefix))]
    urls = [f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{p}" for p in paths]

    if as_json:
        print(json.dumps(urls, indent=2))
    else:
        for u in urls:
            print(u)
