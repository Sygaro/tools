# /home/reidar/tools/r_tools/tools/clean_temp.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# Katalognavn vi gjenkjenner direkte (rask sjekk på path.parts)
_DIR_TARGETS = {
    "pycache": {"__pycache__"},
    "pytest_cache": {".pytest_cache"},
    "mypy_cache": {".mypy_cache"},
    "ruff_cache": {".ruff_cache"},
    "coverage": {"htmlcov"},
    "build": {"build"},
    "dist": {"dist"},
    "node_modules": {"node_modules"},
}

# Filnavn/globs per mål
_FILE_PATTERNS = {
    "coverage": [".coverage", ".coverage.*"],
    "editor": ["*~", ".*.swp", ".*.swo", "*.tmp", "*.bak"],
    "ds_store": [".DS_Store"],
    "thumbs_db": ["Thumbs.db", "ehthumbs.db"],
}

def _match_any_name(path: Path, names: Iterable[str]) -> bool:
    s = set(path.parts)
    return any(n in s for n in names)

def _gather_targets(root: Path, enabled: Dict[str, bool],
                    extra_globs: List[str], skip_globs: List[str],
                    only: List[str] | None, skip: List[str] | None) -> Tuple[List[Path], List[Path]]:
    """
    Returner (dirs, files) for sletting.
    - only: begrens til disse target-keyene
    - skip: hopp over disse target-keyene
    """
    only_set = set(only or [])
    skip_set = set(skip or [])

    def is_on(key: str) -> bool:
        if key in skip_set:
            return False
        if only_set and key not in only_set:
            return False
        return bool(enabled.get(key, False))

    del_dirs: List[Path] = []
    del_files: List[Path] = []

    # 1) katalogmål (rask navne-match)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        pdir = Path(dirpath)

        # bygg liste over direr som skal slettes i denne mappen
        to_remove_names: List[str] = []
        for key, names in _DIR_TARGETS.items():
            if not is_on(key):
                continue
            for d in list(dirnames):
                if d in names:
                    to_remove_names.append(d)

        # legg til i del_dirs og fjern fra traversal (unngå rglob inni)
        for name in to_remove_names:
            target = (pdir / name).resolve()
            if target.is_dir():
                del_dirs.append(target)
                # fjern fra videre os.walk
                if name in dirnames:
                    dirnames.remove(name)

        # 2) file-patterns per mål
        for key, patterns in _FILE_PATTERNS.items():
            if not is_on(key):
                continue
            for pat in patterns:
                for f in pdir.glob(pat):
                    if f.is_file():
                        del_files.append(f.resolve())

    # 3) ekstra globs
    for pat in extra_globs or []:
        for p in root.glob(pat):
            if p.is_file():
                del_files.append(p.resolve())
            elif p.is_dir():
                del_dirs.append(p.resolve())

    # 4) skip_globs (filter bort)
    def should_skip(path: Path) -> bool:
        for pat in skip_globs or []:
            # tolkes relativt til root
            for m in (root.glob(pat) if any(ch in pat for ch in "*?[]") else [root / pat]):
                try:
                    if m.resolve() == path:
                        return True
                except Exception:
                    pass
        return False

    del_dirs = [d for d in sorted(set(del_dirs)) if not should_skip(d)]
    del_files = [f for f in sorted(set(del_files)) if not should_skip(f)]
    return del_dirs, del_files

def _rm_dir(p: Path) -> bool:
    try:
        # rask og trygg: fjern tre rekursivt
        for sub in p.rglob("*"):
            try:
                if sub.is_file() or sub.is_symlink():
                    sub.unlink(missing_ok=True)
            except Exception:
                pass
        for sub in sorted([q for q in p.rglob("*") if q.is_dir()], reverse=True):
            try:
                sub.rmdir()
            except Exception:
                pass
        p.rmdir()
        return True
    except Exception:
        return False

def _rm_file(p: Path) -> bool:
    try:
        p.unlink(missing_ok=True)
        return True
    except Exception:
        return False

def run_clean(cfg: Dict, only: List[str] | None, skip: List[str],
              dry_run: bool = True) -> None:
    root = Path(cfg.get("project_root", ".")).resolve()
    c = cfg.get("clean", {})
    if not c or not c.get("enable", True):
        print("Clean er slått av i config (‘clean.enable=false’).")
        return

    enabled = dict(c.get("targets", {}))
    extra_globs = list(c.get("extra_globs", []))
    skip_globs = list(c.get("skip_globs", []))

    dirs, files = _gather_targets(root, enabled, extra_globs, skip_globs, only, skip)

    print(f"Prosjekt: {root}")
    print(f"Fjernes (kataloger): {len(dirs)}")
    for d in dirs:
        print("  DIR ", d.relative_to(root))
    print(f"Fjernes (filer): {len(files)}")
    for f in files:
        print("  FILE", f.relative_to(root))

    if dry_run:
        print("Dry-run: ingen filer/kataloger ble slettet. Bruk --yes for å utføre.")
        return

    ok = 0; fail = 0
    for d in dirs:
        (_rm_dir(d) and (ok:=ok+1)) or (fail:=fail+1)
    for f in files:
        (_rm_file(f) and (ok:=ok+1)) or (fail:=fail+1)
    print(f"Slettet: {ok} • Feilet: {fail}")
