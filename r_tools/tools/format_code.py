# ./tools/r_tools/tools/format_code.py
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

Viktig: Denne implementasjonen er bakoverkompatibel med eksisterende format_config.json:
- prettier.extra_args støttes
- black.args støttes
- ruff.args støttes (overstyrer autogenererte arguments hvis satt)
"""
from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

# ---------- Runner utils ----------
def _which_tool(name: str) -> str | None:
    exe = Path(sys.executable)
    candidate = exe.with_name(name)
    if candidate.exists() and candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    return None

def _run(cmd: list[str], dry: bool, cwd: Path | None = None) -> int:
    print("▶", " ".join(cmd))
    if dry:
        return 0
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(cwd) if cwd else None,
        )
        if proc.stdout:
            print(proc.stdout, end="")
        return proc.returncode
    except FileNotFoundError:
        print(f"Verktøy ikke funnet: {cmd[0]}")
        return 127

# ---------- Robust npx-deteksjon ----------
def _find_highest_nvm_npx(nvm_dir: Path) -> Path | None:
    versions_dir = nvm_dir / "versions" / "node"
    if not versions_dir.is_dir():
        return None
    best_key: tuple[int, int, int] | None = None
    best_path: Path | None = None
    for vdir in versions_dir.iterdir():
        if not vdir.is_dir():
            continue
        m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)$", vdir.name)
        if not m:
            continue
        major, minor, patch = map(int, m.groups())
        cand = vdir / "bin" / "npx"
        if cand.is_file() and os.access(cand, os.X_OK):
            key = (major, minor, patch)
            if best_key is None or key > best_key:
                best_key = key
                best_path = cand
    return best_path

def _find_npx(project_root: Path, fmt_cfg: dict) -> tuple[str | None, str]:
    override = (fmt_cfg.get("npx_path") or "").strip()
    if override:
        p = Path(override).expanduser().resolve()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p), f"Bruker npx fra format.npx_path: {p}"
        note = f"format.npx_path satt til {override}, men fant ikke kjørbar fil – prøver auto-detektering."
    else:
        note = ""
    found = shutil.which("npx")
    if found:
        return found, (note + (", " if note else "") + f"Fant npx i PATH: {found}")
    local_npx = project_root / "node_modules" / ".bin" / "npx"
    if local_npx.is_file() and os.access(local_npx, os.X_OK):
        return str(local_npx), (note + (", " if note else "") + f"Fant lokal npx: {local_npx}")
    nvm_dir_env = os.environ.get("NVM_DIR")
    if nvm_dir_env:
        cand = _find_highest_nvm_npx(Path(nvm_dir_env).expanduser())
        if cand:
            return str(cand), (note + (", " if note else "") + f"Fant npx via $NVM_DIR: {cand}")
    cand = _find_highest_nvm_npx(Path.home() / ".nvm")
    if cand:
        return str(cand), (note + (", " if note else "") + f"Fant npx via ~/.nvm: {cand}")
    return None, (note + (", " if note else "") + "npx ikke funnet via PATH, prosjekt eller NVM.")

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

def _strip_trailing_spaces(lines: list[str]) -> list[str]:
    return [ln.rstrip() for ln in lines]

def _trim_file_blank_edges(lines: list[str]) -> list[str]:
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return lines

def _collapse_blank_runs(lines: list[str], keep: int = 1) -> list[str]:
    out: list[str] = []
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

def _py_remove_blank_after_any_block(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        out.append(lines[i])
        cur = lines[i].rstrip()
        if cur.endswith(":"):
            if i + 1 < n and lines[i + 1].strip() == "":
                j = i + 2
                while j < n and lines[j].strip() == "":
                    j += 1
                if j < n and not _is_docstring_start(lines[j]):
                    i += 1
        i += 1
    return out

def _py_remove_blank_before_block_followups(lines: list[str]) -> list[str]:
    followups = ("else:", "elif ", "except", "finally:")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if i + 1 < n and lines[i].strip() == "" and any(lines[i + 1].lstrip().startswith(t) for t in followups):
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return out

# ---------- {}-languages (kompakte blokker) ----------
def _brace_lang_remove_unneeded_blanks(lines: list[str]) -> list[str]:
    out: list[str] = []
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
def _cleanup_text(text: str, ext: str, compact_blocks: bool, max_consecutive_blanks: int) -> str:
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
    keep_n = max(0, int(max_consecutive_blanks))
    lines = _collapse_blank_runs(lines, keep=keep_n)
    lines = _trim_file_blank_edges(lines)
    return "\n".join(lines) + "\n"

def _iter_cleanup_targets(
    project_root: Path,
    paths: list[str],
    exts: list[str],
    exclude_exts: list[str],
    exclude_dirs: list[str],
    exclude_files: list[str],
) -> Iterable[Path]:
    abs_excl_dirs: list[Path] = []
    for d in exclude_dirs or []:
        pd = Path(d)
        abs_excl_dirs.append((pd if pd.is_absolute() else (project_root / pd)).resolve())

    def _is_within_excluded(p: Path) -> bool:
        for ex in abs_excl_dirs:
            try:
                p.resolve().relative_to(ex)
                return True
            except Exception:
                continue
        return False

    rel_globs = [g for g in (exclude_files or []) if any(ch in g for ch in "*?[]")]
    rel_names = set(g for g in (exclude_files or []) if not any(ch in g for ch in "*?[]"))
    roots: list[Path] = []
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
        if _is_within_excluded(p.parent):
            return False
        sfx = p.suffix.lower()
        if sfx in excl:
            return False
        if sfx not in inc:
            return False
        if p.name in rel_names:
            return False
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

def _run_cleanup(cfg: dict, dry_run: bool) -> None:
    fmt = cfg.get("format", {})
    cln = fmt.get("cleanup", {})
    if not cln or not cln.get("enable", False):
        return
    project_root = Path(cfg.get("project_root", ".")).resolve()
    paths = list(cln.get("paths", []))
    exts = [e.lower() for e in (_as_list(cln.get("exts")) or _TEXT_EXTS_DEFAULT)]
    exclude_exts = [e.lower() for e in _as_list(cln.get("exclude_exts") or [])]
    compact_blocks = bool(cln.get("compact_blocks", True))
    max_consecutive_blanks = int(cln.get("max_consecutive_blanks", 1))
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

# ---------- helpers ----------
def _as_csv_string(v: object) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (list, tuple)):
        return ",".join(str(x).strip() for x in v if str(x).strip())
    return ""

def _as_list(v: object) -> list[str]:
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        return [s.strip() for s in v.split(",") if s.strip()]
    return []

def _list_or_empty(v: object) -> list[str]:
    return [str(x) for x in v] if isinstance(v, (list, tuple)) else ([] if v in (None, "", False) else [str(v)])

# ---------- Public API ----------
def run_format(cfg: dict, dry_run: bool = False) -> None:
    """
    Beholder oppførselen din, men legger til støtte for:
      - format.prettier.extra_args (liste)
      - format.black.args (liste)
      - format.ruff.args (liste): hvis satt, brukes den som “fasit”
    """
    fmt = cfg.get("format", {})
    rc = 0
    project_root = Path(cfg.get("project_root", ".")).resolve()

    def _danger_label(p: Path) -> str | None:
        p = p.resolve()
        home = Path.home().resolve()
        if p == home:
            return "hjemmekatalogen (~)"
        if p == p.anchor:
            return "rotkatalogen (/)"
        return None

    danger = _danger_label(project_root)
    allow_home = bool(fmt.get("allow_home", False))
    if danger and not allow_home:
        print(f"[format] Sikkerhet: project_root er {danger}. Avbryter for å unngå å formatere hele maskinen.")
        print(
            "[format] Kjør med --project <mappe> (f.eks. --project ~/tools) eller sett format.allow_home=true i configs/format_config.json."
        )
        return

    # ---------- Prettier ----------
    pr = fmt.get("prettier", {})
    if pr.get("enable", False):
        npx_path, why = _find_npx(project_root, fmt)
        npx_bin = npx_path or _which_tool("npx") or shutil.which("npx")
        if npx_bin:
            if npx_path and why:
                print(f"[format] {why}")

            base_args = ["prettier", "--write", "--log-level", "warn"]

            # “Ny” modell (valgfri)
            if pr.get("printWidth") is not None:
                base_args += ["--print-width", str(int(pr["printWidth"]))]
            if pr.get("tabWidth") is not None:
                base_args += ["--tab-width", str(int(pr["tabWidth"]))]
            if pr.get("singleQuote", False):
                base_args += ["--single-quote"]
            if pr.get("semi") is False:
                base_args += ["--no-semi"]
            if pr.get("trailingComma"):
                base_args += ["--trailing-comma", str(pr["trailingComma"])]

            # Bakoverkompatibelt: ekstra args som i din config
            for a in _as_list(pr.get("extra_args")):
                base_args.append(a)

            globs = _as_list(pr.get("globs")) or ["**/*.{html,css,js,ts,tsx,json,yml,yaml,md}"]
            ignores = _as_list(pr.get("ignore"))
            ignores = (ignores or []) + ["!**/._*", "!**/.DS_Store"]
            patterns = globs + ignores

            rc |= _run([npx_bin] + base_args + patterns, dry_run, cwd=project_root)
        else:
            print("[format] npx ikke funnet – hopper over prettier.")

    # ---------- Black ----------
    bl = fmt.get("black", {})
    if bl.get("enable", False):
        black_bin = _which_tool("black")
        cmd = [black_bin] if black_bin else [sys.executable, "-m", "black"]

        # “Ny” modell (valgfri)
        if bl.get("line_length") is not None:
            cmd += ["--line-length", str(int(bl["line_length"]))]
        tgt_csv = _as_csv_string(bl.get("target"))
        if tgt_csv:
            for tv in [t.strip() for t in tgt_csv.split(",") if t.strip()]:
                cmd += ["--target-version", tv]

        # Bakoverkompatibelt: args-liste
        cmd += _as_list(bl.get("args"))

        paths = _as_list(bl.get("paths")) or ["./"]
        rc |= _run(cmd + paths, dry_run, cwd=project_root)

    # ---------- Ruff ----------
    rf = fmt.get("ruff", {})
    if rf.get("enable", False):
        # Hvis eksplisitte args finnes i config, bruk dem (bakoverkompatibelt)
        explicit_args = _as_list(rf.get("args"))
        if explicit_args:
            args = explicit_args
        else:
            args = ["check", "./"]
            if rf.get("fix", True):
                args.append("--fix")
            if rf.get("unsafe_fixes", False):
                args.append("--unsafe-fixes")
            if rf.get("preview", False):
                args.append("--preview")
            sel_csv = _as_csv_string(rf.get("select"))
            ign_csv = _as_csv_string(rf.get("ignore"))
            if sel_csv:
                args += ["--select", sel_csv]
            if ign_csv:
                args += ["--ignore", ign_csv]

        ruff_bin = _which_tool("ruff")
        if ruff_bin:
            rc |= _run([ruff_bin] + args, dry_run, cwd=project_root)
        else:
            rc |= _run([sys.executable, "-m", "ruff"] + args, dry_run, cwd=project_root)

    # Whitespace-cleanup til slutt
    _run_cleanup(cfg, dry_run)
    if rc != 0:
        print(f"Noen formattere returnerte kode {rc}")

def _unified_diff_str(before: str, after: str, rel: str) -> str:
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"{rel} (før)",
        tofile=f"{rel} (etter)",
        lineterm="",
        n=3,
    )
    return "".join(diff)

def format_preview(cfg: dict, rel_path: str) -> str:
    fmt = cfg.get("format", {})
    project_root = Path(cfg.get("project_root", ".")).resolve()
    target = (project_root / rel_path).resolve()
    try:
        target.relative_to(project_root)
    except Exception:
        raise ValueError("rel_path må peke under project_root")
    if not target.is_file():
        raise FileNotFoundError(f"Fant ikke fil: {rel_path}")

    out: list[str] = []
    rel = target.relative_to(project_root).as_posix()
    ext = target.suffix.lower()
    dry = True

    pr = fmt.get("prettier", {})
    if pr.get("enable", False):
        npx_path, why = _find_npx(project_root, fmt)
        npx_bin = npx_path or _which_tool("npx") or shutil.which("npx")
        if npx_bin:
            globs = _as_list(pr.get("globs")) or []
            matched = any(target.match(g.replace("**/", "**/*").replace("./", "")) or fnmatch.fnmatch(rel, g) for g in globs)
            if matched:
                rc = _run([npx_bin, "prettier", "--check", rel], dry, cwd=project_root)
                if rc == 1:
                    out.append(f"[prettier] {rel}: ville bli endret (viser ikke diff)")
                elif rc == 0:
                    out.append(f"[prettier] {rel}: ingen endringer")
                else:
                    out.append(f"[prettier] {rel}: kunne ikke avgjøre (rc={rc})")
        else:
            out.append("[prettier] npx ikke funnet – hopper over prettier-sjekk")

    bl = fmt.get("black", {})
    if bl.get("enable", False) and ext == ".py":
        black_bin = _which_tool("black")
        cmd = [black_bin] if black_bin else [sys.executable, "-m", "black"]
        cmd += ["--diff", rel]
        out.append(f"\n[black --diff] {rel}\n")
        _run(cmd, dry, cwd=project_root)

    rf = fmt.get("ruff", {})
    if rf.get("enable", False) and ext == ".py":
        args = ["check", rel, "--fix", "--diff"]
        if rf.get("preview", False):
            args.append("--preview")
        sel = (rf.get("select") or "").strip()
        ign = (rf.get("ignore") or "").strip()
        if sel:
            args += ["--select", sel]
        if ign:
            args += ["--ignore", ign]
        out.append(f"\n[ruff --diff] {rel}\n")
        ruff_bin = _which_tool("ruff")
        if ruff_bin:
            _run([ruff_bin] + args, dry, cwd=project_root)
        else:
            _run([sys.executable, "-m", "ruff"] + args, dry, cwd=project_root)

    cln = fmt.get("cleanup", {}) or {}
    if cln.get("enable", False):
        try:
            before = _read_text(target)
            new_text = _cleanup_text(
                before,
                target.suffix,
                compact_blocks=bool(cln.get("compact_blocks", True)),
                max_consecutive_blanks=int(cln.get("max_consecutive_blanks", 1)),
            )
            if before != new_text:
                out.append(f"\n[cleanup diff] {rel}\n")
                out.append(_unified_diff_str(before, new_text, rel))
            else:
                out.append(f"\n[cleanup] {rel}: ingen endringer")
        except Exception as e:
            out.append(f"[cleanup] feil for {rel}: {e}")

    text = "\n".join(out).rstrip() + ("\n" if out else "")
    return text if text.strip() else f"Ingen endringer for {rel}\n"
