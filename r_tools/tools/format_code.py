# /home/reidar/tools/r_tools/tools/format_code.py
"""
Erstatter tools/rydd_kode.sh – kjører verktøy styrt fra config.
Forutsetter at prettier/black/ruff finnes i PATH.
"""
from __future__ import annotations
import subprocess, shutil
from typing import Dict, List

def _run(cmd: List[str], dry: bool) -> int:
    print("▶", " ".join(cmd))
    if dry: return 0
    try:
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        print(f"Verktøy ikke funnet: {cmd[0]}")
        return 127

def run_format(cfg: Dict, dry_run: bool = False) -> None:
    fmt = cfg.get("format", {})
    rc = 0

    pr = fmt.get("prettier", {})
    if pr.get("enable", False):
        if shutil.which("npx"):
            for g in pr.get("globs", []):
                rc |= _run(["npx", "prettier", "--write", g], dry_run)
        else:
            print("npx ikke funnet – hopper over prettier.")

    bl = fmt.get("black", {})
    if bl.get("enable", False):
        if shutil.which("black"):
            rc |= _run(["black"] + bl.get("paths", []), dry_run)
        else:
            print("black ikke funnet – hopper over black.")

    rf = fmt.get("ruff", {})
    if rf.get("enable", False):
        if shutil.which("ruff"):
            rc |= _run(["ruff"] + rf.get("args", []), dry_run)
        else:
            print("ruff ikke funnet – hopper over ruff.")

    if rc != 0:
        print(f"Noen kommandoer returnerte kode {rc}")
