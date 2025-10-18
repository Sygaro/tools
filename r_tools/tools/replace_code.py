# ./tools/r_tools/tools/replace_code.py
from __future__ import annotations

import difflib
import fnmatch
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class ReplaceConfig:
    project_root: Path
    include: list[str]  # globs (relativt til project_root), f.eks. **/*.py
    exclude: list[str]  # globs (rel. til project_root)
    max_size: int  # bytes
    case_sensitive: bool  # True = skill store/små
    regex: bool  # True = ‘find’ tolkes som regex
    backup: bool  # True = skriv .bak ved endringer
    dry_run: bool  # True = ikke skriv
    show_diff: bool  # True = unified diff
    # Global excludes fra global_config.json
    global_exclude_dirs: list[str]
    global_exclude_files: list[str]

def _listify(v: object) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v]
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    return []

def _read_cfg(cfg: dict, args_overrides: dict | None) -> ReplaceConfig:
    root = Path(cfg.get("project_root", ".")).resolve()
    rcfg = dict(cfg.get("replace", {}))
    include = _listify(rcfg.get("include"))
    exclude = _listify(rcfg.get("exclude"))
    max_size = int(rcfg.get("max_size", 2_000_000))
    # defaults fra UI/CLI om de er gitt der
    ao: dict[str, Any] = args_overrides or {}
    if "include" in ao and ao["include"] not in (None, [], ""):
        include = _listify(ao["include"])
    if "exclude" in ao and ao["exclude"] not in (None, [], ""):
        exclude = _listify(ao["exclude"])
    if "max_size" in ao and ao["max_size"]:
        max_size = int(ao["max_size"])
    # oppførsel
    case_sensitive = bool(ao.get("case_sensitive", rcfg.get("case_sensitive", False)))  # default: False
    regex = bool(ao.get("regex", rcfg.get("regex", True)))  # default: True
    backup = bool(ao.get("backup", rcfg.get("backup", True)))  # default: True
    dry_run = bool(ao.get("dry_run", rcfg.get("dry_run", True)))  # default: True
    show_diff = bool(ao.get("show_diff", rcfg.get("show_diff", False)))  # default: False
    # globale ekskluderinger (kommer fra load_config → global_config.json)
    g_excl_dirs = _listify(cfg.get("exclude_dirs"))
    g_excl_files = _listify(cfg.get("exclude_files"))
    # dersom include ikke er satt i config: fornuftig standard
    if not include:
        include = [
            "**/*.py",
            "**/*.js",
            "**/*.ts",
            "**/*.tsx",
            "**/*.css",
            "**/*.scss",
            "**/*.html",
            "**/*.json",
            "**/*.md",
            "**/*.txt",
            "**/*.sh",
            "**/*.yml",
            "**/*.yaml",
            "**/*.toml",
            "**/*.ini",
            "**/*.cfg",
            "**/*.c",
            "**/*.h",
            "**/*.cpp",
        ]
    # dersom exclude ikke er satt i config: tom liste (globale tar uansett)
    exclude = list(exclude or [])
    return ReplaceConfig(
        project_root=root,
        include=include,
        exclude=exclude,
        max_size=max_size,
        case_sensitive=case_sensitive,
        regex=regex,
        backup=backup,
        dry_run=dry_run,
        show_diff=show_diff,
        global_exclude_dirs=g_excl_dirs,
        global_exclude_files=g_excl_files,
    )

def _build_abs_excluded_dirs(root: Path, exclude_dirs: list[str]) -> list[Path]:
    out: list[Path] = []
    for d in exclude_dirs:
        p = Path(d)
        out.append((p if p.is_absolute() else (root / p)).resolve())
    return out

def _should_skip_by_dirs(root: Path, abs_excl_dirs: list[Path], p: Path) -> bool:
    parent = p.parent
    for ex in abs_excl_dirs:
        try:
            parent.resolve().relative_to(ex)
            return True
        except Exception:
            continue
    return False

def _split_rel_globs_vs_names(exclude_files: list[str]) -> tuple[list[str], list[str]]:
    rel_globs = [g for g in exclude_files if any(ch in g for ch in "*?[]")]
    rel_names = [g for g in exclude_files if not any(ch in g for ch in "*?[]")]
    return rel_globs, rel_names

def _iter_candidates(cfg: ReplaceConfig) -> Iterable[Path]:
    """
    Finn kandidater ut fra include/exclude + globale excludes:
    - include/exclude: globs relative til project_root
    - global_exclude_dirs: kataloger som ekskluderes (absolutt-resolvert)
    - global_exclude_files: basenavn eller globs på RELATIVE paths
    """
    root = cfg.project_root
    abs_excl_dirs = _build_abs_excluded_dirs(root, cfg.global_exclude_dirs)
    g_rel_globs, g_rel_names = _split_rel_globs_vs_names(cfg.global_exclude_files)
    gathered: set[Path] = set()
    # Inkluder
    for pat in cfg.include:
        for p in root.glob(pat):
            if p.is_file():
                gathered.add(p.resolve())

    # Lokal exclude-globs (rel mot root)
    def _excluded_by_local_globs(rel_posix: str) -> bool:
        return any(fnmatch.fnmatch(rel_posix, pat) for pat in cfg.exclude)

    for p in sorted(gathered):
        if _should_skip_by_dirs(root, abs_excl_dirs, p):
            continue
        # global exclude (basenavn)
        if p.name in g_rel_names:
            continue
        # global exclude (relativ glob)
        rel = p.resolve().relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, g) for g in g_rel_globs):
            continue
        # lokal exclude (relativ glob)
        if _excluded_by_local_globs(rel):
            continue
        # størrelse
        try:
            if p.stat().st_size > cfg.max_size:
                continue
        except Exception:
            continue
        yield p

def _compile(find: str, *, regex: bool, case_sensitive: bool) -> re.Pattern[str]:
    if not regex:
        find = re.escape(find)
    flags = re.MULTILINE
    if not case_sensitive:
        flags |= re.IGNORECASE
    return re.compile(find, flags)

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")

def _make_backup(path: Path) -> Path | None:
    bak = path.with_suffix(path.suffix + ".bak")
    try:
        if bak.exists():
            bak.unlink()
    except Exception:
        pass
    try:
        bak.write_bytes(path.read_bytes())
        return bak
    except Exception:
        return None

def _print_header(cfg: ReplaceConfig, find: str, repl: str) -> None:
    print(f"Prosjekt: {cfg.project_root}")
    print(
        f"Modus: {'dry-run' if cfg.dry_run else 'apply'}  •  Backup: {'på' if cfg.backup else 'av'}  •  Diff: {'på' if cfg.show_diff else 'av'}"
    )
    print(f"Regex: {cfg.regex}  •  Case-sensitive: {cfg.case_sensitive}  •  Max størrelse: {cfg.max_size} bytes")
    print("Include:", ", ".join(cfg.include))
    excl = cfg.exclude[:]
    # vis også globale excludes for transparens
    excl += [f"(global) {g}" for g in (cfg.global_exclude_dirs or [])]
    excl += [f"(global) {g}" for g in (cfg.global_exclude_files or [])]
    print("Exclude:", ", ".join(excl))
    print("")

def _normalize_globs(globs: list[str] | None, filename_search: bool) -> list[str]:
    """
    Normaliserer globs. Når filename_search=True:
    - rene filnavn (ingen '/', ingen jokertegn) → '**/<navn>'
    - globs som '*.py' eller 'src/*.py' beholdes som de er.
    """
    out: list[str] = []
    for g in globs or []:
        s = g.strip()
        if not s:
            continue
        is_pure_filename = ("/" not in s) and not any(ch in s for ch in "*?[]")
        if filename_search and is_pure_filename:
            out.append(f"**/{s}")
        else:
            out.append(s)
    return out

def run_replace(
    cfg: dict,
    find: str,
    replace: str,
    regex: bool = True,
    case_sensitive: bool = False,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_size: int = 2_000_000,
    dry_run: bool = True,
    backup: bool = True,
    show_diff: bool = True,
    filename_search: bool = False,  # ← NYTT
) -> None:
    rcfg = cfg.get("replace", {}) or {}
    # UI overstyrer kun når oppgitt; ellers bruk config
    include = include if include not in (None, []) else rcfg.get("include") or None
    exclude = exclude if exclude not in (None, []) else rcfg.get("exclude") or None
    if not filename_search:
        filename_search = bool(rcfg.get("filename_search", False))
    include = _normalize_globs(include, filename_search) if include else None
    """
    Søk/erstatt over prosjektfiler.
    Parametre fra UI/CLI (args) overstyrer config.replace verdier; global exclude_dirs/files respekteres alltid.
    """
    # Pakk args-overrides for å gi tydelig prioritet over config:
    overrides = {
        "include": include,
        "exclude": exclude,
        "max_size": max_size if max_size is not None else None,
        "regex": regex,
        "case_sensitive": case_sensitive,
        "dry_run": dry_run,
        "backup": backup,
        "show_diff": show_diff,
    }
    rcfg = _read_cfg(cfg, overrides)
    if not find:
        print("Ingen 'find' angitt – avbryter.")
        return
    pat = _compile(find, regex=rcfg.regex, case_sensitive=rcfg.case_sensitive)
    files_considered = 0
    files_changed = 0
    total_replacements = 0
    _print_header(rcfg, find, replace)
    for path in _iter_candidates(rcfg):
        files_considered += 1
        try:
            before = _read_text(path)
        except Exception:
            continue
        new_text, n = pat.subn(replace, before)
        if n <= 0:
            continue
        files_changed += 1
        total_replacements += n
        rel = path.resolve().relative_to(rcfg.project_root).as_posix()
        print(f"⟳ {rel}  ({n} treff)")
        if rcfg.show_diff:
            diff = difflib.unified_diff(
                before.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=f"{rel} (før)",
                tofile=f"{rel} (etter)",
                lineterm="",
                n=3,
            )
            for line in diff:
                print(line, end="")
        if rcfg.dry_run:
            continue
        if rcfg.backup:
            _make_backup(path)
        try:
            _write_text(path, new_text)
        except Exception as e:
            print(f"[ADVARSEL] Klarte ikke å skrive {rel}: {e}")
    print("\n=== Oppsummert ===")
    print(f"Filer vurdert : {files_considered}")
    print(f"Filer endret  : {files_changed}")
    print(f"Erstatninger  : {total_replacements}")
    if rcfg.dry_run:
        print("Dry-run: ingen filer ble skrevet. Kjør med dry_run=False (CLI: --apply, UI: slå av 'Dry-run') for å utføre.")
