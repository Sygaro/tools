# /home/reidar/tools/r_tools/tools/code_search.py
from __future__ import annotations
import os, re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Dict, Tuple
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)

@dataclass
class SearchConfig:
    project_root: Path
    include_extensions: List[str]
    exclude_dirs: List[str]
    exclude_files: List[str]
    case_insensitive: bool

def _compile_patterns(terms: Iterable[str], flags: int) -> List[re.Pattern]:
    return [re.compile(t, flags=flags) for t in terms]

def _should_include(path: Path, cfg: SearchConfig) -> bool:
    if not any(str(path).endswith(ext) for ext in cfg.include_extensions):
        return False
    if path.name in set(cfg.exclude_files):
        return False
    parts = set(path.parts)
    if any(ex in parts for ex in cfg.exclude_dirs):
        return False
    return True

def _highlight(line: str, patterns: List[re.Pattern], use_color: bool) -> str:
    if not use_color:
        return line.rstrip("\n")
    out = line.rstrip("\n")
    for pat in patterns:
        out = pat.sub(lambda m: f"{Fore.YELLOW}{m.group(0)}{Style.RESET_ALL}", out)
    return out

def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, _, filenames in os.walk(root):
        for f in filenames:
            yield Path(dirpath) / f

def run_search(cfg: Dict, terms: List[str] | None, use_color: bool, show_count: bool, max_size: int) -> None:
    sc = SearchConfig(
        project_root=Path(cfg["project_root"]),
        include_extensions=list(cfg["include_extensions"]),
        exclude_dirs=list(cfg["exclude_dirs"]),
        exclude_files=list(cfg["exclude_files"]),
        case_insensitive=bool(cfg.get("case_insensitive", True)),
    )
    search_terms = terms if terms else list(cfg.get("search_terms", []))
    if not search_terms:
        print("Ingen søketermer. Angi termer eller legg til i config.")
        return

    flags = re.IGNORECASE if sc.case_insensitive else 0
    patterns = _compile_patterns(search_terms, flags)

    total_hits = 0
    for file_path in _iter_files(sc.project_root):
        try:
            if not _should_include(file_path, sc):
                continue
            if file_path.stat().st_size > max_size:
                continue
            matches: List[Tuple[int, str]] = []
            with file_path.open("r", encoding="utf-8", errors="ignore") as f:
                for idx, line in enumerate(f, 1):
                    if any(p.search(line) for p in patterns):
                        matches.append((idx, _highlight(line, patterns, use_color)))
            if matches:
                if show_count:
                    print(f"{Fore.CYAN}{file_path}{Style.RESET_ALL}  (+{len(matches)} treff)")
                for ln, content in matches:
                    print(f"{Fore.CYAN}{file_path}:{ln}:{Style.RESET_ALL} {content}")
                total_hits += len(matches)
        except Exception as e:
            print(f"{Fore.RED}Feil på {file_path}: {e}{Style.RESET_ALL}")
    print(f"{Fore.GREEN}Totalt treff: {total_hits}{Style.RESET_ALL}")
