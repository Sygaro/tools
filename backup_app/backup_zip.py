#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kompatibilitets-wrapper for tidligere bruksmønster:
  ./backup.sh 1.06 Frontend_OK
Nå rutes dette til backup.py sin fleksible CLI.
"""
from __future__ import annotations
import os
import sys
from pathlib import Path
from typing import List, Optional

HERE = Path(__file__).resolve().parent

def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    SOURCE_DEFAULT = os.getenv("BACKUP_SOURCE_DEFAULT")
    PROJECT_DEFAULT = os.getenv("BACKUP_PROJECT_DEFAULT")

    if any(arg.startswith("--") for arg in argv):
        os.execv(sys.executable, [sys.executable, str(HERE / "backup.py"), *argv])
        return 0

    version = argv[0] if len(argv) >= 1 else None
    tag = argv[1] if len(argv) >= 2 else None

    if not SOURCE_DEFAULT:
        print(
            "[DEPRECATED] Gammelt kall oppdaget. Sett kilde/prosjekt eksplisitt.\n"
            "Eksempel:\n"
            f"  ./backup.sh --source /sti/til/prosjekt --project mittprosjekt "
            f"{f'--version {version} ' if version else ''}{f'--tag {tag}' if tag else ''}\n\n"
            "Tips: midlertidig default via env:\n"
            "  export BACKUP_SOURCE_DEFAULT=/sti/til/prosjekt\n"
            "  export BACKUP_PROJECT_DEFAULT=mittprosjekt\n",
            file=sys.stderr,
        )
        return 2

    cmd = [sys.executable, str(HERE / "backup.py"), "--source", SOURCE_DEFAULT]
    if PROJECT_DEFAULT:
        cmd += ["--project", PROJECT_DEFAULT]
    if version:
        cmd += ["--version", version]
    if tag:
        cmd += ["--tag", tag]
    os.execv(sys.executable, cmd)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
