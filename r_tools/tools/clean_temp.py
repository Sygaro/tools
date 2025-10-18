# tools/r_tools/tools/clean_temp.py
from __future__ import annotations

import os
from collections.abc import Iterable
from pathlib import Path

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

def _normalize_globs_from_excludes(project_root: Path, dirs: list[str], files: list[str]) -> list[str]:
    """Gjør globale exclude_dirs/exclude_files om til skip_globs som clean forstår."""
    skip: list[str] = []
    for d in dirs or []:
        d = str(d).strip("/").rstrip("/")
        if d:
            # ekskluder hele treet
            pat = f"**/{d}/**"
            if pat not in skip:
                skip.append(pat)
    for f in files or []:
        f = str(f).strip()
        if f:
            pat = f"**/{f}" if not any(ch in f for ch in "*?[]") else f
            if pat not in skip:
                skip.append(pat)
    return skip

def _gather_targets(
    root: Path,
    enabled: dict[str, bool],
    extra_globs: list[str],
    skip_globs: list[str],
    only: list[str] | None,
    skip: list[str] | None,
) -> tuple[list[Path], list[Path]]:
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

    del_dirs: list[Path] = []
    del_files: list[Path] = []
    # 1) katalogmål (rask navne-match)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        pdir = Path(dirpath)
        # Finn hvilke undermapper som skal slettes i denne mappen
        to_remove_names: list[str] = []
        for key, names in _DIR_TARGETS.items():
            if not is_on(key):
                continue
            for d in list(dirnames):
                if d in names:
                    to_remove_names.append(d)
        # Legg til i del_dirs og fjern fra traversal (unngå rglob inni)
        for name in to_remove_names:
            target = (pdir / name).resolve()
            if target.is_dir():
                del_dirs.append(target)
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
    # 3) ekstra globs (kan være filer eller kataloger)
    for pat in extra_globs or []:
        for p in root.glob(pat):
            if p.is_file():
                del_files.append(p.resolve())
            elif p.is_dir():
                del_dirs.append(p.resolve())

    # 4) skip_globs (filter bort – tolkes relativt til root)
    def should_skip(path: Path) -> bool:
        for pat in skip_globs or []:
            ms = root.glob(pat) if any(ch in pat for ch in "*?[]") else [root / pat]
            for m in ms:
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

def run_clean(cfg: dict, only: list[str] | None, skip: list[str], dry_run: bool = True) -> None:
    """
    Konfig (clean_config.json):
    {
      "clean": {
        "enable": true,
        "targets": { "pycache": true, ... },
        "extra_globs": ["*.tmp", ...],
        "skip_globs": ["**/keep/**"],
        "honor_global_excludes": false,             # <- NY: default false
        "exclude_dirs": ["data/cache"],             # <- NY: per-clean excludes (kataloger)
        "exclude_files": ["*.sqlite", ".env"]       # <- NY: per-clean excludes (filer/globs)
      }
    }
    NB: Hvis honor_global_excludes=true vil exclude_dirs/ exclude_files fra global_config.json
        bli lagt til som skip_globs her (i tillegg til clean.exclude_*).
    """
    root = Path(cfg.get("project_root", ".")).resolve()
    c = cfg.get("clean", {}) or {}
    if not c.get("enable", True):
        print("Clean er slått av i config (‘clean.enable=false’).")
        return
    enabled = dict(c.get("targets", {}))
    extra_globs = list(c.get("extra_globs", []))
    skip_globs = list(c.get("skip_globs", []))
    # Per-clean ekskludering
    clean_excl_dirs = list(c.get("exclude_dirs", []))
    clean_excl_files = list(c.get("exclude_files", []))
    skip_globs += _normalize_globs_from_excludes(root, clean_excl_dirs, clean_excl_files)
    # Valgfri bruk av globale ekskluderinger
    if bool(c.get("honor_global_excludes", False)):
        g_excl_dirs = list(cfg.get("exclude_dirs", []))
        g_excl_files = list(cfg.get("exclude_files", []))
        skip_globs += _normalize_globs_from_excludes(root, g_excl_dirs, g_excl_files)
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
    ok = 0
    fail = 0
    for d in dirs:
        (_rm_dir(d) and (ok := ok + 1)) or (fail := fail + 1)
    for f in files:
        (_rm_file(f) and (ok := ok + 1)) or (fail := fail + 1)
    print(f"Slettet: {ok} • Feilet: {fail}")
