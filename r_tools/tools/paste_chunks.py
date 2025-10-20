# ./tools/r_tools/tools/paste_chunks.py
from __future__ import annotations

import hashlib
import io
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class PasteCfg:
    project_root: Path
    out_dir: Path
    max_lines: int
    allow_binary: bool
    filename_search: bool
    include: list[str]
    exclude: list[str]
    only_globs: list[str]
    skip_globs: list[str]
    # globale ekskluderinger
    global_exclude_dirs: list[str]
    global_exclude_files: list[str]

# ---------- små hjelpere ----------

def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()

def _read_text(path: Path) -> tuple[str, int]:
    data = path.read_text(encoding="utf-8", errors="replace")
    return data, data.count("\n") + (0 if data.endswith("\n") else 1)

def _is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except Exception:
        return True
    return b"\x00" in chunk

def _normalize_globs(globs: Iterable[str], *, filename_search: bool) -> list[str]:
    """
    Når filename_search=True og mønsteret er et 'rent filnavn' (ingen '/', ingen wildcard),
    genererer vi TO mønstre:
      - <navn>            (fanger root-filer: '.env', '.gitignore')
      - **/<navn>         (fanger filer dypere i treet)
    """
    out: list[str] = []
    for g in globs or []:
        s = str(g).strip()
        if not s:
            continue
        # normaliser './foo' -> 'foo'
        if s.startswith("./"):
            s = s[2:]
        is_pure_filename = ("/" not in s) and not any(ch in s for ch in "*?[]")
        if filename_search and is_pure_filename:
            # Legg til begge for å matche både root og underkataloger
            out.append(s)
            out.append(f"**/{s}")
        else:
            out.append(s)
    return out

def _match_any_rel(patterns: list[str], rel_posix: str) -> bool:
    import fnmatch

    for pat in patterns or []:
        if fnmatch.fnmatch(rel_posix, pat):
            return True
    return False

# ---- exclude_dirs: del opp i (1) navn, (2) sti-baser, (3) globs ----

def _split_dir_excludes(root: Path, items: Iterable[str]) -> tuple[list[str], list[Path], list[str]]:
    """
    Returnerer:
      - names:   rene katalognavn uten / og uten wildcard (eks: '__pycache__', '.git')
      - bases:   bestemte katalogstier (absolutte eller relative til root) uten wildcard
      - globs:   globs som matcher relativ katalog-sti (eks: 'dist/**', 'build*')
    NB: ingen resolve(); vi vil ikke følge symlinker.
    """
    names: list[str] = []
    bases: list[Path] = []
    globs: list[str] = []
    for raw in items or []:
        s = str(raw).strip()
        if not s:
            continue
        has_wild = any(ch in s for ch in "*?[]")
        has_slash = "/" in s
        if not has_wild and not has_slash:
            names.append(s)
        elif not has_wild:
            # sti uten wildcard → base
            p = Path(s)
            bases.append(p if p.is_absolute() else (root / p))
        else:
            # glob (matcher mot relativ sti)
            globs.append(s)
    return names, bases, globs

def _under_any_base(path: Path, bases: list[Path]) -> bool:
    for b in bases:
        try:
            path.relative_to(b)
            return True
        except Exception:
            continue
    return False

def _has_any_dirname(path_under_root: Path, names: list[str]) -> bool:
    # Sjekk om noen av delene i den RELATIVE stien er i names
    for part in path_under_root.parts:
        if part in names:
            return True
    return False

def _iter_include_candidates(root: Path, include: list[str]) -> Iterable[Path]:
    """
    Iterator over kandidater fra include-globs. Returnerer *absolutte* stier,
    men uten å resolve symlinker.
    """
    seen: set[Path] = set()
    for pat in include:
        for p in root.glob(pat):
            if p.is_file():
                if p not in seen:
                    seen.add(p)
                    yield p

def _effective_include_list(pcfg: PasteCfg) -> list[str]:
    # Hvis include er tom, fall tilbake til bred default (“alle filer med punktum”)
    return pcfg.include or ["*.*", "**/*.*"]

def _gather_files(pcfg: PasteCfg) -> list[Path]:
    root = pcfg.project_root

    include_globs = _normalize_globs(_effective_include_list(pcfg), filename_search=pcfg.filename_search)
    exclude_globs = _normalize_globs(pcfg.exclude, filename_search=pcfg.filename_search)
    only_globs = list(pcfg.only_globs or [])
    skip_globs = list(pcfg.skip_globs or [])

    # Globale ekskluderinger (kataloger og filer)
    dir_names, dir_bases, dir_globs = _split_dir_excludes(root, pcfg.global_exclude_dirs)
    # Global exclude files: basenavn vs globs på relativ filsti
    g_rel_file_globs = [g for g in (pcfg.global_exclude_files or []) if any(ch in g for ch in "*?[]")]
    g_rel_file_names = set(g for g in (pcfg.global_exclude_files or []) if not any(ch in g for ch in "*?[]"))

    # Kandidater fra include
    cands = list(_iter_include_candidates(root, include_globs))
    files: list[Path] = []
    for p in cands:
        # relativ sti (uten resolve)
        try:
            rel = p.relative_to(root)
        except Exception:
            # Utenfor root? hopp over for sikkerhets skyld
            continue
        rel_posix = rel.as_posix()

        # --- katalog-ekscluderinger ---
        # 1) navn hvor som helst i stien
        if _has_any_dirname(rel.parent, dir_names):
            continue
        # 2) under spesifikk base-katalog
        if _under_any_base(p.parent, dir_bases):
            continue
        # 3) matcher relativ katalog-glob (sjekk mappen, og hele rel-stien for sikkerhet)
        if _match_any_rel(dir_globs, rel.parent.as_posix()) or _match_any_rel(dir_globs, rel_posix):
            continue

        # --- globale fil-ekscluderinger ---
        if p.name in g_rel_file_names:
            continue
        if _match_any_rel(g_rel_file_globs, rel_posix):
            continue

        # --- lokale exclude/only/skip ---
        if _match_any_rel(exclude_globs, rel_posix):
            continue
        if only_globs and not _match_any_rel(only_globs, rel_posix):
            continue
        if skip_globs and _match_any_rel(skip_globs, rel_posix):
            continue

        files.append(p)

    # Deterministisk sortering (uten resolve)
    return sorted(files, key=lambda x: x.relative_to(root).as_posix())

# ---------- hovedfunksjon ----------

def run_paste(cfg: dict, list_only: bool = False) -> None:
    """
    Skriver paste_out/paste_N.txt og en samlet paste_out/index.txt

    cfg-uttak:
      - toppnivå: project_root, exclude_dirs, exclude_files
      - under "paste": out_dir, max_lines, allow_binary, filename_search, include, exclude, only_globs, skip_globs
    """
    root = Path(cfg.get("project_root", ".")).resolve()
    pc = cfg.get("paste", {}) or {}
    out_dir = pc.get("out_dir", "paste_out")
    out_abs = Path(out_dir) if Path(out_dir).is_absolute() else (root / out_dir)

    pcfg = PasteCfg(
        project_root=root,
        out_dir=out_abs,
        max_lines=int(pc.get("max_lines", 4000)),
        allow_binary=bool(pc.get("allow_binary", False)),
        filename_search=bool(pc.get("filename_search", False)),
        include=list(pc.get("include", []) or []),
        exclude=list(pc.get("exclude", []) or []),
        only_globs=list(pc.get("only_globs", []) or []),
        skip_globs=list(pc.get("skip_globs", []) or []),
        global_exclude_dirs=list(cfg.get("exclude_dirs", []) or []),
        global_exclude_files=list(cfg.get("exclude_files", []) or []),
    )

    files = _gather_files(pcfg)

    if list_only:
        print(f"Prosjekt: {root}")
        print(f"Antall filer: {len(files)}")
        for f in files:
            try:
                print(f.relative_to(root).as_posix())
            except Exception:
                print(str(f))
        return

    pcfg.out_dir.mkdir(parents=True, exist_ok=True)

    # Skriv rullerende paste_XX.txt
    index_rows: list[str] = []
    paste_idx = 1
    lines_in_current = 0
    cur: io.StringIO | None = None
    cur_path: Path | None = None

    def _open_new() -> tuple[io.StringIO, Path]:
        nonlocal paste_idx, lines_in_current
        if cur is not None:
            raise RuntimeError("internal: cur must be None before open_new()")
        p = pcfg.out_dir / f"paste_{paste_idx:02d}.txt"
        paste_idx += 1
        lines_in_current = 0
        return io.StringIO(), p

    def _flush(buf: io.StringIO, path: Path) -> int:
        text = buf.getvalue()
        path.write_text(text, encoding="utf-8")
        return text.count("\n") + (0 if text.endswith("\n") else 1)

    # visuelt: liste filer
    print(f"Prosjekt: {root}")
    print(f"Out:      {pcfg.out_dir}")
    print(f"Filer:    {len(files)}")
    print("== Filer ==")
    for f in files:
        try:
            print(f" - {f.relative_to(root).as_posix()}")
        except Exception:
            print(f" - {str(f)}")
    print("")

    for file_path in files:
        # binærhåndtering
        if not pcfg.allow_binary and _is_binary(file_path):
            continue

        # åpne rullerende fil hvis nødvendig
        if cur is None:
            cur, cur_path = _open_new()

        try:
            rel = file_path.relative_to(root).as_posix()
        except Exception:
            continue

        text, line_count = _read_text(file_path)
        sha = _sha256_bytes(text.encode("utf-8", errors="replace"))

        header = [
            "===== BEGIN FILE =====",
            f"PATH: {rel}",
            f"LINES: {line_count}",
            "CHUNK: 1/1",
            f"SHA256: {sha}",
            "----- BEGIN CODE -----",
        ]
        footer = ["----- END CODE -----", "===== END FILE ====="]
        block_lines = len(header) + len(footer) + line_count

        # Ruller hvis nødvendig
        if lines_in_current + block_lines > pcfg.max_lines:
            if cur is not None and cur_path is not None:
                flushed = _flush(cur, cur_path)
                print(f"skrev {cur_path.name}  ({flushed} linjer)")
            cur = None
            cur_path = None
            cur, cur_path = _open_new()

        # Skriv blokk
        for ln in header:
            cur.write(ln + "\n")
        cur.write(text)
        if not text.endswith("\n"):
            cur.write("\n")
        for ln in footer:
            cur.write(ln + "\n")
        lines_in_current += block_lines

        # index-rad
        index_rows.append(f"{rel}  |  {cur_path.name}  |  {line_count} linjer")

    # flush siste
    generated_files: list[Path] = []
    if cur is not None and cur_path is not None:
        flushed = _flush(cur, cur_path)
        generated_files.append(cur_path)
        print(f"skrev {cur_path.name}  ({flushed} linjer)")
    # plukk opp evt. tidligere filer (i tilfelle mange rulleringer)
    for n in range(1, paste_idx - 1):
        generated_files.append(pcfg.out_dir / f"paste_{n:02d}.txt")

    # skriv index.txt for ALLE
    idx_path = pcfg.out_dir / "index.txt"
    idx = io.StringIO()
    idx.write("# index over innhold i paste_*.txt\n")
    idx.write("# format: <relativ/path> | <paste_fil> | <linjer>\n\n")
    for row in index_rows:
        idx.write(row + "\n")
    idx.write("\n# Genererte filer:\n")
    for p in sorted(set(generated_files), key=lambda q: q.name):
        idx.write(p.name + "\n")
    idx.write(f"\nTotalt filer: {len(index_rows)}\n")
    idx.write(f"Antall paste-filer: {len(set(generated_files))}\n")
    idx_path.write_text(idx.getvalue(), encoding="utf-8")

    # slutt-rapport til stdout (UI)
    print("\n== Oppsummering ==")
    print(f"Totalt filer: {len(index_rows)}")
    total_lines = 0
    for row in index_rows:
        try:
            total_lines += int(row.rsplit("|", 1)[-1].strip().split()[0])
        except Exception:
            pass
    print(f"Totalt linjer: {total_lines}")
    print(f"Antall paste-filer: {len(set(generated_files))}")
    print(f"Index: {idx_path.relative_to(pcfg.project_root).as_posix()}")
