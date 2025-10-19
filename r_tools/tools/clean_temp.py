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

# Vanlige venv/isolerte miljø-kataloger som bør beskyttes
_PROTECTED_ENV_DIRS = {
    ".venv",
    "venv",
    "env",
    ".env",        # noen bruker denne som venv (kan også være .env-fil – håndteres separat)
    ".tox",
    ".conda",
    "conda-env",
}

def _match_any_name(path: Path, names: Iterable[str]) -> bool:
    parts = set(path.parts)
    return any(n in parts for n in names)

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

def _is_inside_venv(path: Path) -> bool:
    """Sjekk oppover i treet etter pyvenv.cfg (marker for venv)."""
    try:
        for parent in [path] + list(path.parents):
            if (parent / "pyvenv.cfg").is_file():
                return True
        return False
    except Exception:
        # Vern ved tvil
        return True

def _gather_targets(
    root: Path,
    enabled: dict[str, bool],
    extra_globs: list[str],
    skip_globs: list[str],
    only: list[str] | None,
    skip: list[str] | None,
    allow_venv_clean: bool,
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

    # 0) Ikke gå inn i beskyttede miljøer (venv, tox, conda, osv.)
    def protect_env_dirs(dirnames: list[str]) -> None:
        if not allow_venv_clean:
            # Mutér dirnames in-place for å hindre traversal
            for protected in list(dirnames):
                if protected in _PROTECTED_ENV_DIRS:
                    dirnames.remove(protected)

    # 1) katalogmål (rask navne-match)
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        # unngå å traversere inn i venv/.venv/env/.tox/...
        protect_env_dirs(dirnames)

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
            # Sikkerhet: ikke slett miljøer
            if not allow_venv_clean and (_is_inside_venv(target) or _match_any_name(target, _PROTECTED_ENV_DIRS)):
                continue
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
                        # Sikkerhet: ikke slett filer inne i venv
                        if not allow_venv_clean and _is_inside_venv(f):
                            continue
                        del_files.append(f.resolve())

    # 3) ekstra globs (kan være filer eller kataloger)
    for pat in extra_globs or []:
        for p in root.glob(pat):
            # Sikkerhet: ikke slett inni venv
            if not allow_venv_clean and _is_inside_venv(p):
                continue
            if p.is_file():
                del_files.append(p.resolve())
            elif p.is_dir():
                del_dirs.append(p.resolve())

    # 4) skip_globs (filter bort – tolkes relativt til root)
    def should_skip(path: Path) -> bool:
        for pat in skip_globs or []:
            # Glob matcher alle aktuelle paths; sammenlikn konkret path
            matches = root.glob(pat) if any(ch in pat for ch in "*?[]") else [root / pat]
            for m in matches:
                try:
                    if m.resolve() == path:
                        return True
                except Exception:
                    # Ved problemer med resolve: hopp over å skippe
                    pass
        return False

    del_dirs = [d for d in sorted(set(del_dirs)) if not should_skip(d)]
    del_files = [f for f in sorted(set(del_files)) if not should_skip(f)]

    return del_dirs, del_files

def _rm_dir(p: Path) -> bool:
    try:
        # Viktig: ikke følge symlinker
        for sub in p.rglob("*"):
            try:
                if sub.is_file() or sub.is_symlink():
                    sub.unlink(missing_ok=True)
            except Exception:
                pass
        # Slett tomme kataloger fra bunnen
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
      "project_root": ".",
      "exclude_dirs": ["data/cache"],    # globale excludes (valgfrie)
      "exclude_files": ["*.sqlite"],     # globale excludes (valgfrie)
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
        "extra_globs": ["*.tmp"],
        "skip_globs": ["**/keep/**"],
        "honor_global_excludes": false,
        "exclude_dirs": ["artifacts"],
        "exclude_files": [".env"],
        "allow_venv_clean": false        # <- NY: default False (vern venv)
      }
    }

    NB:
    - Hvis honor_global_excludes=true vil exclude_dirs/exclude_files fra global_config.json
      bli lagt til som skip_globs her (i tillegg til clean.exclude_*).
    - Når allow_venv_clean=false vil vernet mot venv slå inn (ingen traversal/operasjoner i venv).
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

    allow_venv_clean = bool(c.get("allow_venv_clean", False))

    # Legg til tydelige skip-globs for venv når vern er aktivt (synlig i dry-run)
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
        skip=skip,
        allow_venv_clean=allow_venv_clean,
    )

    print(f"Prosjekt: {root}")
    print(f"Fjernes (kataloger): {len(dirs)}")
    for d in dirs:
        print("  DIR ", d.relative_to(root))
    print(f"Fjernes (filer): {len(files)}")
    for f in files:
        print("  FILE", f.relative_to(root))

    if dry_run:
        print("Dry-run: ingen filer/kataloger ble slettet.\nBruk --yes for å utføre.")
        return

    ok = 0
    fail = 0
    for d in dirs:
        (_rm_dir(d) and (ok := ok + 1)) or (fail := fail + 1)
    for f in files:
        (_rm_file(f) and (ok := ok + 1)) or (fail := fail + 1)
    print(f"Slettet: {ok} • Feilet: {fail}")
