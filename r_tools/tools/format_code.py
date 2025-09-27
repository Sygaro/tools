# /home/reidar/tools/r_tools/tools/format_code.py
"""
Formatterings-pipeline for r_tools:
- prettier (via npx), black, ruff
- whitespace-cleanup (kollaps tomlinjer, fjern "unaturlige" tomlinjer i blokker)
Regler er konservative for å unngå semantikkendringer.
"""
from __future__ import annotations
import subprocess
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Iterable, Tuple

# ---------- Runner utils ----------

def _which_tool(name: str) -> Optional[str]:
    """Hvorfor: finn binær i samme venv som sys.executable, ellers i PATH."""
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
        return subprocess.run(cmd, check=False).returncode
    except FileNotFoundError:
        print(f"Verktøy ikke funnet: {cmd[0]}")
        return 127

# ---------- Cleanup: helpers ----------

_TEXT_EXTS_DEFAULT = [".py", ".js", ".ts", ".tsx", ".css", ".scss", ".html", ".json", ".sh", ".c", ".h", ".cpp"]

def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")

def _write_if_changed(path: Path, new_text: str) -> bool:
    old = _read_text(path)
    if old != new_text:
        path.write_text(new_text, encoding="utf-8")
        return True
    return False

def _strip_trailing_spaces(lines: List[str]) -> List[str]:
    return [ln.rstrip() for ln in lines]

def _collapse_blank_runs(lines: List[str]) -> List[str]:
    out: List[str] = []
    blank_streak = 0
    for ln in lines:
        if ln.strip() == "":
            blank_streak += 1
            if blank_streak <= 1:
                out.append("")
        else:
            blank_streak = 0
            out.append(ln)
    # trim start
    while out and out[0] == "":
        out.pop(0)
    # trim end
    while out and out[-1] == "":
        out.pop()
    return out

def _py_remove_blank_after_def(lines: List[str]) -> List[str]:
    """Fjern tom linje rett etter def/class, med docstring-unntak."""
    out: List[str] = []
    n = len(lines)
    i = 0
    while i < n:
        out.append(lines[i])
        cur = lines[i].strip()
        if cur.endswith(":") and (cur.startswith("def ") or cur.startswith("class ")):
            # kandidat: neste linje tom?
            if i + 1 < n and lines[i + 1].strip() == "":
                # behold tomlinje hvis neste ikke-tomme er docstring
                j = i + 2
                while j < n and lines[j].strip() == "":
                    j += 1
                if j < n:
                    nx = lines[j].lstrip()
                    if not (nx.startswith('"""') or nx.startswith("'''")):
                        # dropp enkelt tomlinje
                        i += 1  # hopp over tomlinjen
        i += 1
    return out

def _brace_lang_remove_unneeded_blanks(lines: List[str]) -> List[str]:
    """For språk med {}-blokker: fjern tom etter '{' og før '}'."""
    out: List[str] = []
    n = len(lines)
    for idx, ln in enumerate(lines):
        stripped = ln.strip()
        # skip tom linje rett etter '{'
        if stripped == "" and idx > 0 and lines[idx - 1].strip().endswith("{"):
            # men behold hvis neste ikke-tomme er '}' (da kan én blank gi luft – vi fjerner uansett her for konsistens)
            continue
        # skip tom linje rett før '}'
        if stripped == "" and idx + 1 < n and lines[idx + 1].strip().startswith("}"):
            continue
        out.append(ln)
    return out

def _normalize_newlines(text: str) -> str:
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    # sørg for nøyaktig én sluttlinje
    if not t.endswith("\n"):
        t += "\n"
    return t

def _cleanup_text(text: str, ext: str) -> str:
    """Konservativ whitespace-opprydding per filtype."""
    t = _normalize_newlines(text)
    lines = t.split("\n")
    # fjern trailing spaces først
    lines = _strip_trailing_spaces(lines)
    # språkspesifikk blokk-logikk
    low = ext.lower()
    if low == ".py":
        lines = _py_remove_blank_after_def(lines)
    elif low in {".js", ".ts", ".tsx", ".css", ".scss", ".json", ".c", ".h", ".cpp"}:
        lines = _brace_lang_remove_unneeded_blanks(lines)
    # kollaps generelt
    lines = _collapse_blank_runs(lines)
    # rejoin + avslutt med newline
    return "\n".join(lines) + "\n"

def _iter_cleanup_targets(project_root: Path, paths: List[str], exts: List[str]) -> Iterable[Path]:
    """Finn filer å rydde: rekursivt under oppgitte paths (eller root)."""
    roots: List[Path] = []
    if paths:
        for p in paths:
            pp = (project_root / p) if not Path(p).is_absolute() else Path(p)
            if pp.exists():
                roots.append(pp)
    else:
        roots.append(project_root)

    seen: set[Path] = set()
    for base in roots:
        if base.is_file():
            if base.suffix.lower() in exts:
                yield base.resolve()
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in exts:
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

    changed = 0
    total = 0
    for file_path in _iter_cleanup_targets(project_root, paths, exts):
        total += 1
        try:
            original = _read_text(file_path)
            new_text = _cleanup_text(original, file_path.suffix)
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

    # prettier (valgfritt)
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

    # whitespace cleanup (etter formattere for minst mulig konflikt)
    _run_cleanup(cfg, dry_run)

    if rc != 0:
        print(f"Noen formattere returnerte kode {rc}")
