# ./tools/r_tools/tools/code_search.py
from __future__ import annotations

import fnmatch
import os
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class SearchConfig:
    project_root: Path
    include_extensions: list[str]
    exclude_dirs: list[str]
    exclude_files: list[str]
    case_insensitive: bool
    search_terms: list[str] | None  # default fra config (kan være None)

def _normalize_exts(exts: Sequence[str]) -> list[str]:
    out: list[str] = []
    for e in exts:
        e = e.strip()
        if not e:
            continue
        if not e.startswith("."):
            e = "." + e
        out.append(e.lower())
    return sorted(set(out))

def _read_cfg(cfg: dict) -> SearchConfig:
    root = Path(cfg.get("project_root", ".")).resolve()
    return SearchConfig(
        project_root=root,
        include_extensions=_normalize_exts(cfg.get("include_extensions", [])),
        exclude_dirs=list(cfg.get("exclude_dirs", [])),
        exclude_files=list(cfg.get("exclude_files", [])),
        case_insensitive=bool(cfg.get("case_insensitive", True)),
        search_terms=(cfg.get("search_terms") or None),
    )

def _within_any_excluded_dir(path: Path, excluded_abs: list[Path]) -> bool:
    # Sjekk om path ligger under en ekskludert katalog
    for ex in excluded_abs:
        try:
            path.resolve().relative_to(ex)
            return True
        except Exception:
            continue
    return False

def _iter_files(
    root: Path,
    include_extensions: list[str],
    exclude_dirs: list[str],
    exclude_files: list[str],
    limit_dirs: list[str] | None,
    limit_exts: list[str] | None,
) -> Iterator[Path]:
    """
    Gå gjennom prosjektet og yield passende filer.
    - Respekterer globale exclude_dirs/exclude_files.
    - limit_dirs (valgfrie): kun under disse katalogene (relativt til root). Tom liste = ingen begrensning.
    - limit_exts (valgfrie): begrens til disse endelsene (overstyrer include_extensions hvis gitt).
    """
    eff_exts = _normalize_exts(limit_exts or include_extensions)
    # For exclude_dirs: bygg absolutt-liste
    abs_excl_dirs: list[Path] = []
    for d in exclude_dirs or []:
        pd = Path(d)
        abs_excl_dirs.append((pd if pd.is_absolute() else (root / pd)).resolve())
    # limit_dirs → absolutte baser
    abs_limits: list[Path] | None = None
    if limit_dirs is not None:
        if len(limit_dirs) == 0:
            abs_limits = []  # “ingen” = yield ingenting
        else:
            tmp: list[Path] = []
            for d in limit_dirs:
                p = (Path(d) if Path(d).is_absolute() else (root / d)).resolve()
                if p.exists() and p.is_dir():
                    tmp.append(p)
            abs_limits = tmp
    # exclude_files supporterer både basenavn og glob på relativ sti
    rel_globs = [g for g in (exclude_files or []) if any(ch in g for ch in "*?[]")]
    rel_names = set(g for g in (exclude_files or []) if not any(ch in g for ch in "*?[]"))

    # Hjelper: sjekk limit_dirs
    def _under_limit_dir(p: Path) -> bool:
        if abs_limits is None:
            return True
        for base in abs_limits:
            try:
                p.resolve().relative_to(base)
                return True
            except Exception:
                continue
        return False

    # Traversér
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        pdir = Path(dirpath)
        # Prune dirnames i sanntid for ytelse (unngå å gå inn i ekskluderte)
        keep: list[str] = []
        for d in dirnames:
            cand = (pdir / d).resolve()
            if _within_any_excluded_dir(cand, abs_excl_dirs):
                continue
            # Hvis limit_dirs er i bruk: hopp over grener som ikke er under noen limit
            if abs_limits is not None and not _under_limit_dir(cand):
                # men vi må fortsatt slippe gjennom hvis noen limit ligger lenger ned (typisk ikke),
                # dette er greit siden vi allerede beregner _under_limit_dir for cand (dir).
                continue
            keep.append(d)
        dirnames[:] = keep
        # Filtrér filer
        for fname in filenames:
            p = (pdir / fname).resolve()
            # Endelse
            if p.suffix.lower() not in eff_exts:
                continue
            # Limits + excludes
            if not _under_limit_dir(p):
                continue
            if _within_any_excluded_dir(p.parent, abs_excl_dirs):
                continue
            # exclude_files via basenavn
            if p.name in rel_names:
                continue
            # exclude_files via glob på relativ sti
            rel = p.resolve().relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, g) for g in rel_globs):
                continue
            yield p

def _compile_terms(terms: Sequence[str], case_insensitive: bool) -> list[re.Pattern[str]]:
    flags = re.MULTILINE
    if case_insensitive:
        flags |= re.IGNORECASE
    patterns: list[re.Pattern[str]] = []
    for t in terms:
        t = t.strip()
        if not t:
            continue
        patterns.append(re.compile(t, flags))
    return patterns

def _match_line(line: str, pats: list[re.Pattern[str]], require_all: bool) -> bool:
    if not pats:
        return False
    hits = [p.search(line) is not None for p in pats]
    return all(hits) if require_all else any(hits)

def _read_text_safely(path: Path, max_size: int) -> str | None:
    try:
        if path.stat().st_size > max_size:
            return None
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None

def _print_default(
    root: Path,
    file_path: Path,
    lines: list[tuple[int, str]],
) -> None:
    rel = file_path.relative_to(root).as_posix()
    print(f"== {rel} ==")
    for ln, text in lines:
        print(f"{ln:5d}: {text.rstrip()}")
    print("")

def _print_files_only(
    root: Path,
    files: list[Path],
    path_mode: str,
) -> None:
    seen: set[Path] = set()
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        out = f.as_posix() if path_mode == "full" else f.relative_to(root).as_posix()
        print(out)

def _normalize_globs(globs: list[str] | None, filename_search: bool) -> list[str]:
    patterns: list[str] = []
    for g in globs or []:
        s = g.strip()
        if not s:
            continue
        if filename_search and ("/" not in s):
            patterns.append(f"**/{s}")  # foo.py, *.py, cli* → **/foo.py, **/*.py, **/cli*
        else:
            patterns.append(s)
    return patterns

def _file_iter_with_globs(
    project_root: Path,
    include_globs: list[str] | None,
    exclude_globs: list[str] | None,
    max_size: int,
) -> Iterable[Path]:
    inc = _normalize_globs(include_globs, filename_search=False) if include_globs else []
    exc = _normalize_globs(exclude_globs, filename_search=False) if exclude_globs else []
    root_abs = project_root.resolve()

    def _under_root(p: Path) -> bool:
        try:
            p.resolve().relative_to(root_abs)
            return True
        except Exception:
            return False

    # Kandidater kun fra include (hvis oppgitt)
    candidates: list[Path] = []
    for pat in inc:
        for p in project_root.glob(pat):
            if p.is_file():
                candidates.append(p.resolve())

    def _is_excluded(p: Path) -> bool:
        try:
            rel = p.resolve().relative_to(project_root).as_posix()
        except Exception:
            return True  # utenfor root → ut
        for pat in exc:
            if fnmatch.fnmatch(rel, pat):
                return True
        return False

    seen: set[Path] = set()
    for p in candidates:
        if p in seen:
            continue
        seen.add(p)
        if not _under_root(p):
            continue
        if _is_excluded(p):
            continue
        try:
            if p.stat().st_size > max_size:
                continue
        except Exception:
            continue
        yield p

def run_search(
    cfg: dict,
    terms: list[str] | None = None,
    use_color: bool = False,
    show_count: bool = False,
    max_size: int = 2_000_000,
    require_all: bool = False,
    files_only: bool = False,
    path_mode: str = "relative",
    limit_dirs: list[str] | None = None,
    limit_exts: list[str] | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    filename_search: bool = False,
) -> None:
    project_root = Path(cfg.get("project_root", ".")).resolve()
    scfg = _read_cfg(cfg)
    eff_terms = terms if (terms and len(terms) > 0) else (scfg.search_terms or [])
    pats = _compile_terms(eff_terms, case_insensitive=scfg.case_insensitive)
    # UI/CLI > config
    include = include if include not in (None, []) else (cfg.get("search", {}) or {}).get("include") or None
    exclude = exclude if exclude not in (None, []) else (cfg.get("search", {}) or {}).get("exclude") or None
    # Globaliser filnavn/mønstre uten “/”
    if filename_search and include:
        include = _normalize_globs(include, filename_search=True)
    if filename_search and exclude:
        exclude = _normalize_globs(exclude, filename_search=True)
    # Hent effektive extensions (limit_exts > config)
    eff_exts = set(_normalize_exts(limit_exts or scfg.include_extensions))
    # Pre-kandidater:
    #  - Hvis include er spesifisert → bruk glob-iteratoren (rask for målrettet søk)
    #  - Ellers → bruk eksisterende, prunede os.walk-baserte iteratoren (_iter_files)
    if include:
        pre_iter = list(_file_iter_with_globs(project_root, include, exclude, max_size))
    else:
        pre_iter = list(
            _iter_files(
                root=project_root,
                include_extensions=(list(eff_exts) if eff_exts else scfg.include_extensions),
                exclude_dirs=scfg.exclude_dirs,
                exclude_files=scfg.exclude_files,
                limit_dirs=limit_dirs,
                limit_exts=limit_exts,
            )
        )
    # Ekstra ekskludering med exclude (dersom _iter_files ble brukt)
    exc = _normalize_globs(exclude, filename_search=False) if (exclude and not include) else []

    def _is_excluded_rel(p: Path) -> bool:
        if not exc:
            return False
        try:
            rel = p.resolve().relative_to(project_root).as_posix()
        except Exception:
            return True
        return any(fnmatch.fnmatch(rel, pat) for pat in exc)

    files: list[Path] = []
    for p in pre_iter:
        if eff_exts and (p.suffix.lower() not in eff_exts):
            continue
        if _is_excluded_rel(p):
            continue
        files.append(p)
    matched_files: list[Path] = []
    for f in files:
        text = _read_text_safely(f, max_size)
        if text is None:
            continue
        lines = text.splitlines()
        hits: list[tuple[int, str]] = []
        for i, line in enumerate(lines, start=1):
            if _match_line(line, pats, require_all=require_all):
                hits.append((i, line))
        if not hits:
            continue
        matched_files.append(f)
        if not files_only:
            _print_default(project_root, f, hits)
    if files_only:
        _print_files_only(project_root, matched_files, path_mode)
    if show_count:
        print(f"\nTreffende filer: {len(matched_files)}")
