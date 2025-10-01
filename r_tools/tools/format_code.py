# /home/reidar/tools/r_tools/tools/format_code.py
"""
Formatterings-pipeline:
- prettier (via npx), black, ruff
- Whitespace-cleanup (styrt via config):
  * Alltid: fjern trailing spaces, normaliser LF + eksakt 1 sluttlinje
  * Alltid: trim tomlinjer i start/slutt av fil
  * Alltid: kollaps serier av tomlinjer til maks N (N = cleanup.max_consecutive_blanks, default 1)
  * Hvis cleanup.compact_blocks=true:
      - Python: fjern tom linje etter blokksstart (linjer som ender med ':'),
        unntatt hvis neste ikke-tomme er docstring; fjern tom linje før
        else/elif/except/finally.
      - {}-språk: fjern tom linje etter '{' og før '}'/'};'
  * Hopper over filendelser definert i cleanup.exclude_exts
Hvorfor: gi kontroll på hvor aggressiv innstramming skal være og hvilke filer som ryddes.
"""
from __future__ import annotations
import subprocess
import shutil
import sys
import fnmatch
from pathlib import Path
from typing import Dict, List, Optional, Iterable

# ---------- Runner utils ----------

def _which_tool(name: str) -> Optional[str]:
    """Finn binær i samme venv som sys.executable, ellers i PATH."""
    exe = Path(sys.executable)
    candidate = exe.with_name(name)
    if candidate.exists() and candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    return None

def _run(cmd: List[str], dry: bool) -> int:
    print("▶", " ".join(cmd))
    if dry:
        return 0
    try:
        # Viktig: stderr→stdout, så web-UI fanger alt
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if proc.stdout:
            # videreskriv til vår stdout (fanges av webui._capture)
            print(proc.stdout, end="")
        return proc.returncode
    except FileNotFoundError:
        print(f"Verktøy ikke funnet: {cmd[0]}")
        return 127

# ---------- Cleanup: helpers ----------

_TEXT_EXTS_DEFAULT = [
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".css",
    ".scss",
    ".html",
    ".json",
    ".sh",
    ".c",
    ".h",
    ".cpp",
]

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def _write_if_changed(path: Path, new_text: str) -> bool:
    old = _read_text(path)
    if old != new_text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False

def _normalize_newlines(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    if not t.endswith("\n"):
        t += "\n"
    return t

def _strip_trailing_spaces(lines: List[str]) -> List[str]:
    return [ln.rstrip() for ln in lines]

def _trim_file_blank_edges(lines: List[str]) -> List[str]:
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return lines

def _collapse_blank_runs(lines: List[str], keep: int = 1) -> List[str]:
    out: List[str] = []
    streak = 0
    for ln in lines:
        if ln.strip() == "":
            streak += 1
            if streak <= keep:
                out.append("")
        else:
            streak = 0
            out.append(ln)
    return out

# ---------- Python-specific (kompakte blokker) ----------

def _is_docstring_start(line: str) -> bool:
    s = line.lstrip()
    return s.startswith('"""') or s.startswith("'''")

def _py_remove_blank_after_any_block(lines: List[str]) -> List[str]:
    """Fjern tomlinje etter ALLE blokkslinjer (slutter med ':'), unntak for docstring."""
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        out.append(lines[i])
        cur = lines[i].rstrip()
        if cur.endswith(":"):
            # dropp én tomlinje hvis neste ikke-tomme ikke er docstring
            if i + 1 < n and lines[i + 1].strip() == "":
                j = i + 2
                while j < n and lines[j].strip() == "":
                    j += 1
                if j < n and not _is_docstring_start(lines[j]):
                    i += 1
        i += 1
    return out

def _py_remove_blank_before_block_followups(lines: List[str]) -> List[str]:
    """Fjern tomlinje før else/elif/except/finally."""
    followups = ("else:", "elif ", "except", "finally:")
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if (
            i + 1 < n
            and lines[i].strip() == ""
            and any(lines[i + 1].lstrip().startswith(t) for t in followups)
        ):
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return out

# ---------- {}-languages (kompakte blokker) ----------

def _brace_lang_remove_unneeded_blanks(lines: List[str]) -> List[str]:
    """Fjern tom linje etter '{' og før '}'/'};'."""
    out: List[str] = []
    n = len(lines)
    for idx, ln in enumerate(lines):
        stripped = ln.strip()
        if stripped == "":
            prev = lines[idx - 1].strip() if idx > 0 else ""
            nxt = lines[idx + 1].strip() if idx + 1 < n else ""
            if prev.endswith("{"):
                continue
            if nxt.startswith("}") or nxt.startswith("};"):
                continue
        out.append(ln)
    return out

# ---------- Cleanup orchestrator ----------

def _cleanup_text(
    text: str, ext: str, compact_blocks: bool, max_consecutive_blanks: int
) -> str:
    """Konservativ først; stram opp blokker hvis compact_blocks=True; kollaps tomlinjer til maks N."""
    t = _normalize_newlines(text)
    lines = t.split("\n")

    lines = _strip_trailing_spaces(lines)
    lines = _trim_file_blank_edges(lines)

    low = ext.lower()
    if compact_blocks:
        if low == ".py":
            lines = _py_remove_blank_after_any_block(lines)
            lines = _py_remove_blank_before_block_followups(lines)
        elif low in {
            ".js",
            ".ts",
            ".tsx",
            ".css",
            ".scss",
            ".json",
            ".c",
            ".h",
            ".cpp",
        }:
            lines = _brace_lang_remove_unneeded_blanks(lines)

    # Kollaps serier av tomlinjer til maks N
    keep_n = max(0, int(max_consecutive_blanks))
    lines = _collapse_blank_runs(lines, keep=keep_n)
    lines = _trim_file_blank_edges(lines)

    return "\n".join(lines) + "\n"

def _iter_cleanup_targets(
    project_root: Path,
    paths: List[str],
    exts: List[str],
    exclude_exts: List[str],
    exclude_dirs: List[str],  # ← NYTT
    exclude_files: List[str],  # ← NYTT (basenavn eller glob/relativ sti)
) -> Iterable[Path]:
    """Finn filer å rydde: rekursivt under oppgitte paths (eller root).
    Respekterer exclude_dirs og exclude_files fra global_config.json.
    """
    # Bygg absolutt liste over ekskluderte kataloger
    abs_excl_dirs: List[Path] = []
    for d in exclude_dirs or []:
        pd = Path(d)
        abs_excl_dirs.append(
            (pd if pd.is_absolute() else (project_root / pd)).resolve()
        )

    def _is_within_excluded(p: Path) -> bool:
        # sjekk om p ligger under en ekskludert mappe
        for ex in abs_excl_dirs:
            try:
                p.resolve().relative_to(ex)
                return True
            except Exception:
                continue
        return False

    # For filer: tillat både basenavn og glob over relativ sti
    rel_globs = [g for g in (exclude_files or []) if any(ch in g for ch in "*?[]")]
    rel_names = set(
        g for g in (exclude_files or []) if not any(ch in g for ch in "*?[]")
    )

    roots: List[Path] = []
    if paths:
        for p in paths:
            pp = (project_root / p) if not Path(p).is_absolute() else Path(p)
            if pp.exists():
                roots.append(pp)
    else:
        roots.append(project_root)

    seen: set[Path] = set()
    excl = {e.lower() for e in exclude_exts}
    inc = {e.lower() for e in exts}

    def _want(p: Path) -> bool:
        # ekskluder via dirs
        if _is_within_excluded(p.parent):
            return False
        sfx = p.suffix.lower()
        if sfx in excl:
            return False
        if sfx not in inc:
            return False
        # ekskluder via filer (basenavn)
        if p.name in rel_names:
            return False
        # ekskluder via globs over RELATIV sti
        rel = p.resolve().relative_to(project_root).as_posix()
        for g in rel_globs:
            if fnmatch.fnmatch(rel, g):
                return False
        return True

    for base in roots:
        if base.is_file():
            if _want(base):
                yield base.resolve()
            continue
        for p in base.rglob("*"):
            if p.is_file() and _want(p):
                rp = p.resolve()
                if rp not in seen:
                    seen.add(rp)
                    yield rp

def _run_cleanup(cfg: Dict, dry_run: bool) -> None:
    fmt = cfg.get("format", {})
    cln = fmt.get("cleanup", {})
    if not cln or not cln.get("enable", False):
        return

    project_root = Path(cfg.get("project_root", ".")).resolve()
    paths = list(cln.get("paths", []))
    exts = [e.lower() for e in (cln.get("exts") or _TEXT_EXTS_DEFAULT)]
    exclude_exts = [e.lower() for e in (cln.get("exclude_exts") or [])]
    compact_blocks = bool(cln.get("compact_blocks", True))
    max_consecutive_blanks = int(cln.get("max_consecutive_blanks", 1))

    # ← HENT fra global_config.json (toppnivå)
    global_excl_dirs = list(cfg.get("exclude_dirs", []))
    global_excl_files = list(cfg.get("exclude_files", []))

    changed = 0
    total = 0
    for file_path in _iter_cleanup_targets(
        project_root,
        paths,
        exts,
        exclude_exts,
        exclude_dirs=global_excl_dirs,
        exclude_files=global_excl_files,
    ):
        total += 1
        try:
            original = _read_text(file_path)
            new_text = _cleanup_text(
                original,
                file_path.suffix,
                compact_blocks=compact_blocks,
                max_consecutive_blanks=max_consecutive_blanks,
            )
            if original != new_text:
                print(f"⟳ cleanup {file_path}")
                if not dry_run:
                    _write_if_changed(file_path, new_text)
                changed += 1
        except Exception as e:
            print(f"Feil under cleanup {file_path}: {e}")

    print(f"Cleanup: {changed}/{total} filer endret")

# ---------- Public API ----------

def run_format(cfg: Dict, dry_run: bool = False) -> None:
    fmt = cfg.get("format", {})
    rc = 0

    # prettier
    pr = fmt.get("prettier", {})
    if pr.get("enable", False):
        npx = _which_tool("npx") or "npx"
        if shutil.which(npx) or npx != "npx":
            for g in pr.get("globs", []):
                rc |= _run([npx, "prettier", "--write", g], dry_run)
        else:
            print("npx ikke funnet – hopper over prettier.")

    # black
    bl = fmt.get("black", {})
    if bl.get("enable", False):
        black_bin = _which_tool("black")
        if black_bin:
            rc |= _run([black_bin] + bl.get("paths", []), dry_run)
        else:
            print("black ikke funnet i PATH – prøver fallback via python -m black …")
            rc |= _run([sys.executable, "-m", "black"] + bl.get("paths", []), dry_run)

    # ruff
    rf = fmt.get("ruff", {})
    if rf.get("enable", False):
        ruff_bin = _which_tool("ruff")
        if ruff_bin:
            rc |= _run([ruff_bin] + rf.get("args", []), dry_run)
        else:
            print("ruff ikke funnet i PATH – prøver fallback via python -m ruff …")
            rc |= _run([sys.executable, "-m", "ruff"] + rf.get("args", []), dry_run)

    # Whitespace-cleanup til slutt
    _run_cleanup(cfg, dry_run)

    if rc != 0:
        print(f"Noen formattere returnerte kode {rc}")
