# r_tools/tools/clean_temp.py
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable, Tuple, List, Dict

# Katalogmål som typisk kan fjernes
_DIR_TARGETS: Dict[str, set[str]] = {
    "pycache": {"__pycache__"},
    "pytest_cache": {".pytest_cache"},
    "mypy_cache": {".mypy_cache"},
    "ruff_cache": {".ruff_cache"},
    "coverage": {"htmlcov"},
    "build": {"build"},
    "dist": {"dist"},
    "node_modules": {"node_modules"},
}

# Filmønstre per mål
_FILE_PATTERNS: Dict[str, List[str]] = {
    "coverage": [".coverage", ".coverage.*"],
    "editor": ["*~", ".*.swp", ".*.swo", "*.tmp", "*.bak"],
    "ds_store": [".DS_Store"],
    "thumbs_db": ["Thumbs.db", "ehthumbs.db"],
}

# Beskyttede miljøkataloger (ikke traversér dit som standard)
_PROTECTED_ENV_DIRS: set[str] = {
    ".venv",
    "venv",
    "env",
    ".tox",
    ".conda",
    "conda-env",
}

def _any_in_parts(p: Path, names: Iterable[str]) -> bool:
    parts = set(p.parts)
    return any(n in parts for n in names)

def _is_inside_venv(path: Path) -> bool:
    """Sjekk oppover i treet etter pyvenv.cfg. Beskytter venv selv om navnet er uvanlig."""
    try:
        for parent in [path] + list(path.parents):
            if (parent / "pyvenv.cfg").is_file():
                return True
        return False
    except Exception:
        # Vern ved tvil (heller falsk positiv enn å slette for mye)
        return True

def _normalize_excludes_to_skip_globs(dirs: List[str], files: List[str]) -> List[str]:
    skip: List[str] = []
    for d in dirs or []:
        d = d.strip("/").rstrip("/")
        if d:
            skip.append(f"**/{d}/**")
    for f in files or []:
        f = f.strip()
        if f:
            skip.append(f if any(ch in f for ch in "*?[]") else f"**/{f}")
    # Normaliser og fjern duplikater
    seen: set[str] = set()
    unique = []
    for s in skip:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique

def _should_skip_by_globs(root: Path, path: Path, skip_globs: List[str]) -> bool:
    for pat in skip_globs or []:
        # Forenklet (yter bra nok for prosjektstørrelser her)
        for m in root.glob(pat):
            try:
                if m.resolve() == path.resolve():
                    return True
            except Exception:
                # Uproblematisk: vi forsøker beste-match, men feiler "åpent"
                pass
    return False

def _gather_targets(
    root: Path,
    enabled: Dict[str, bool],
    extra_globs: List[str],
    skip_globs: List[str],
    only: List[str] | None,
    skip: List[str] | None,
    allow_venv_clean: bool,
) -> Tuple[List[Path], List[Path]]:
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

    def protect_env_dirs(dirnames: List[str]) -> None:
        if not allow_venv_clean:
            for protected in list(dirnames):
                if protected in _PROTECTED_ENV_DIRS:
                    dirnames.remove(protected)

    # Traversér prosjektet top-down, og stopp tidlig i beskyttede miljøer
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        protect_env_dirs(dirnames)
        here = Path(dirpath)

        # Katalogmål
        for key, names in _DIR_TARGETS.items():
            if not is_on(key):
                continue
            for d in list(dirnames):
                if d in names:
                    target = (here / d).resolve()
                    if not allow_venv_clean and (_is_inside_venv(target) or _any_in_parts(target, _PROTECTED_ENV_DIRS)):
                        # Viktig: ikke registrér for sletting, og ikke traversér inn
                        if d in dirnames:
                            dirnames.remove(d)
                        continue
                    if target.is_dir():
                        del_dirs.append(target)
                        # ikke gå inn i en katalog vi allerede vil slette
                        if d in dirnames:
                            dirnames.remove(d)

        # Filmål i denne mappen
        for key, patterns in _FILE_PATTERNS.items():
            if not is_on(key):
                continue
            for pat in patterns:
                for f in here.glob(pat):
                    if f.is_file():
                        if not allow_venv_clean and _is_inside_venv(f):
                            continue
                        del_files.append(f.resolve())

    # Ekstra globs (kan peke både på filer og kataloger)
    for pat in extra_globs or []:
        for p in root.glob(pat):
            if not allow_venv_clean and _is_inside_venv(p):
                continue
            if p.is_file():
                del_files.append(p.resolve())
            elif p.is_dir():
                del_dirs.append(p.resolve())

    # Filtrer med skip_globs (relative til root)
    del_dirs = sorted({d for d in del_dirs if not _should_skip_by_globs(root, d, skip_globs)})
    del_files = sorted({f for f in del_files if not _should_skip_by_globs(root, f, skip_globs)})

    return del_dirs, del_files

def run_clean(cfg: dict, only: List[str] | None, skip: List[str], dry_run: bool = True) -> None:
    """
    Konfig (utdrag):
    {
      "project_root": ".",
      "exclude_dirs": [],
      "exclude_files": [],
      "clean": {
        "enable": true,
        "targets": {
          "pycache": true,
          "pytest_cache": true,
          "mypy_cache": true,
          "ruff_cache": true,
          "coverage": true,
          "build": true,
          "dist": true,
          "node_modules": false,
          "editor": true,
          "ds_store": true,
          "thumbs_db": true
        },
        "extra_globs": [],
        "skip_globs": [],
        "honor_global_excludes": false,
        "exclude_dirs": [],
        "exclude_files": [],
        "allow_venv_clean": false   # <- NY, default False
      }
    }
    """
    root = Path(cfg.get("project_root", ".")).resolve()
    c = dict(cfg.get("clean", {}) or {})
    if not c.get("enable", True):
        print("Clean er slått av i config (‘clean.enable=false’).")
        return

    enabled = dict(c.get("targets", {}))
    extra_globs: List[str] = list(c.get("extra_globs", []))
    skip_globs: List[str] = list(c.get("skip_globs", []))

    # Lokale excl.
    clean_excl_dirs = list(c.get("exclude_dirs", []))
    clean_excl_files = list(c.get("exclude_files", []))
    skip_globs += _normalize_excludes_to_skip_globs(clean_excl_dirs, clean_excl_files)

    # Globale excl. (valgfritt)
    if bool(c.get("honor_global_excludes", False)):
        g_excl_dirs = list(cfg.get("exclude_dirs", []))
        g_excl_files = list(cfg.get("exclude_files", []))
        skip_globs += _normalize_excludes_to_skip_globs(g_excl_dirs, g_excl_files)

    allow_venv_clean = bool(c.get("allow_venv_clean", False))

    # Visuelle skip-mønstre for venv ved dry-run (gjør det tydelig i utskrift)
    if not allow_venv_clean:
        for d in sorted(_PROTECTED_ENV_DIRS):
            pat = f"**/{d}/**"
            if pat not in skip_globs:
                skip_globs.append(pat)

    dirs, files = _gather_targets(
        root=root,
        enabled=enabled,
        extra_globs=extra_globs,
        skip_globs=skip_globs,
        only=only,
        skip=skip or [],
        allow_venv_clean=allow_venv_clean,
    )

    print(f"Prosjekt: {root}")
    print(f"Fjernes (kataloger): {len(dirs)}")
    for d in dirs:
        try:
            print("  DIR ", d.relative_to(root))
        except Exception:
            print("  DIR ", d)
    print(f"Fjernes (filer): {len(files)}")
    for f in files:
        try:
            print("  FILE", f.relative_to(root))
        except Exception:
            print("  FILE", f)

    if dry_run:
        print("Dry-run: ingen filer/kataloger ble slettet.\nBruk --yes for å utføre.")
        return

    ok = 0
    fail = 0
    # Små, robuste slettefunksjoner (ingen rekursive symlink-follow)
    for d in dirs:
        try:
            for sub in d.rglob("*"):
                try:
                    if sub.is_file() or sub.is_symlink():
                        sub.unlink(missing_ok=True)
                except Exception:
                    pass
            # Slett tomme kataloger (bottom-up)
            for sub in sorted([q for q in d.rglob("*") if q.is_dir()], reverse=True):
                try:
                    sub.rmdir()
                except Exception:
                    pass
            d.rmdir()
            ok += 1
        except Exception:
            fail += 1

    for f in files:
        try:
            f.unlink(missing_ok=True)
            ok += 1
        except Exception:
            fail += 1

    print(f"Slettet: {ok} • Feilet: {fail}")
