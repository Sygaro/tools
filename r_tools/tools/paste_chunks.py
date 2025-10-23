# ./tools/r_tools/tools/paste_chunks.py
from __future__ import annotations

import hashlib
import re
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
# --- First-fit pakking for paste-bøtter (med soft overflow) ---

@dataclass
class PasteItem:
    """Representerer én filblokk som skal inn i en paste_XY.txt."""

    rel_path: str  # kun til index/logging
    rendered: str  # hele teksten (inkl. headers/footers/kode)
    lines: int  # antall linjer i rendered (brukes for pakking)

def _first_fit_pack(items: list[PasteItem], capacity: int, soft_overflow: int = 0) -> list[list[PasteItem]]:
    """
    First-fit bin packing:
      - Legg element i første bøtte som har plass (capacity + soft_overflow).
      - Start ny bøtte hvis ingen eksisterende har plass.
      - Elementer > (capacity + soft_overflow) får egen bøtte (vi splitter aldri filer).
    """
    limit_cap = max(1, int(capacity))
    limit_soft = max(0, int(soft_overflow))

    buckets: list[list[PasteItem]] = []
    used: list[int] = []

    for it in items:
        # for store elementer får egen bøtte (kan overskride limit – vi splitter aldri en fil)
        if it.lines > limit_cap + limit_soft:
            buckets.append([it])
            used.append(it.lines)
            continue

        placed = False
        for i, u in enumerate(used):
            if u + it.lines <= limit_cap + limit_soft:
                buckets[i].append(it)
                used[i] = u + it.lines
                placed = True
                break
        if not placed:
            buckets.append([it])
            used.append(it.lines)

    return buckets

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
    Skriver paste_out/paste_XX.txt og en samlet paste_out/index.txt

    cfg-uttak:
      - toppnivå: project_root, exclude_dirs, exclude_files
      - under "paste":
          out_dir, max_lines, allow_binary, filename_search, include, exclude, only_globs, skip_globs
          NYTT:
            target_files: int         -> fordel blokker jevnt over N filer (overstyrer max_lines-beregning)
            soft_overflow: int        -> tillat inntil X ekstra linjer per fil ut over capacity
            force_single_file: bool   -> skriv alt i én fil (ignorer kapasitetsregler)
            blank_lines: "keep"|"collapse"|"drop"  -> håndtering av tomlinjer i KODE
            allow_split: bool         -> tillat splitting av store filer
            split_chunk_lines: int   -> maks linjer per chunk når split brukes
    """
    root = Path(cfg.get("project_root", ".")).resolve()
    pc = cfg.get("paste", {}) or {}
    out_dir_cfg = pc.get("out_dir", "paste_out")
    out_abs = Path(out_dir_cfg) if Path(out_dir_cfg).is_absolute() else (root / out_dir_cfg)

    # Nye opsjoner
    target_files = int(pc.get("target_files", 0) or 0)
    soft_overflow = int(pc.get("soft_overflow", 0) or 0)
    force_single = bool(pc.get("force_single_file", False))
    blank_policy = str(pc.get("blank_lines", "keep")).strip().lower()  # "keep" | "collapse" | "drop"
    allow_split = bool(pc.get("allow_split", False))
    split_chunk_lines = int(pc.get("split_chunk_lines", 0) or 0)

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

    # --- Bygg fulle filblokker (med headers/footers) som PasteItem ---
    items: list[PasteItem] = []
    total_item_lines = 0  # summen av blokklinjer (inkl. header/footer)

    for file_path in files:
        # hopp binærfiler hvis ikke tillatt
        if not pcfg.allow_binary and _is_binary(file_path):
            continue

        try:
            rel = file_path.relative_to(root).as_posix()
        except Exception:
            # kan ikke relativisere – hopp over
            continue

        text, orig_code_lines = _read_text(file_path)

        # --- komprimer tomlinjer i KODE etter ønske ---
        if blank_policy in ("drop", "collapse"):
            lines = text.splitlines()
            if blank_policy == "drop":
                lines = [ln for ln in lines if ln.strip() != ""]
            else:  # "collapse" -> maks 1 tomlinje
                out_lines: list[str] = []
                blank_streak = 0
                for ln in lines:
                    if ln.strip() == "":
                        blank_streak += 1
                        if blank_streak <= 1:
                            out_lines.append("")
                    else:
                        blank_streak = 0
                        out_lines.append(ln)
                lines = out_lines
            text = "\n".join(lines)
        # sørg for avsluttende newline for kodeblokk
        if not text.endswith("\n"):
            text += "\n"

        # rapporter linjer ETTER eventuell komprimering (practical for packing)
        code_line_count = text.count("\n")  # counts trailing newline as line -> that's intended

        footer = ["----- END CODE -----", "===== END FILE ====="]

        # Hvis splitting er aktivert OG kodelinjer overstiger split_chunk_lines => split
        if allow_split and split_chunk_lines > 0 and code_line_count > split_chunk_lines:
            # del kode-delen i chunker med maks split_chunk_lines per chunk
            lines_with_end = text.splitlines(keepends=True)
            chunks = [ "".join(lines_with_end[i:i+split_chunk_lines]) for i in range(0, len(lines_with_end), split_chunk_lines) ]
            total_chunks = len(chunks)
            for ci, chunk_text in enumerate(chunks, start=1):
                # sørg for newline på chunk (split-preserving)
                if not chunk_text.endswith("\n"):
                    chunk_text += "\n"
                chunk_lines = chunk_text.count("\n")
                sha_chunk = _sha256_bytes(chunk_text.encode("utf-8", errors="replace"))
                header = [
                    "===== BEGIN FILE =====",
                    f"PATH: {rel}",
                    f"TOTAL_LINES: {code_line_count}",
                    f"LINES: {chunk_lines}",
                    f"CHUNK: {ci}/{total_chunks}",
                    f"SHA256: {sha_chunk}",
                    "----- BEGIN CODE -----",
                ]
                rendered = "\n".join(header) + "\n" + chunk_text + "\n".join(footer) + "\n"
                block_lines = rendered.count("\n")
                total_item_lines += block_lines
                items.append(PasteItem(rel_path=rel, rendered=rendered, lines=block_lines))
            # ferdig med denne filen
            continue

        # Ikke split: lag vanlig item (ingen splitting)
        sha = _sha256_bytes(text.encode("utf-8", errors="replace"))
        header = [
            "===== BEGIN FILE =====",
            f"PATH: {rel}",
            f"TOTAL_LINES: {code_line_count}",
            f"LINES: {code_line_count}",
            "CHUNK: 1/1",
            f"SHA256: {sha}",
            "----- BEGIN CODE -----",
        ]
        rendered = "\n".join(header) + "\n" + text + "\n".join(footer) + "\n"
        block_lines = rendered.count("\n")
        total_item_lines += block_lines
        items.append(PasteItem(rel_path=rel, rendered=rendered, lines=block_lines))

    # FFD (sortér m. fallende størrelse for bedre packing)
    items.sort(key=lambda it: it.lines, reverse=True)

    # --- Finn kapasitet og pakk ---
    if force_single:
        buckets = [items] if items else []
    else:
        import math

        if target_files and target_files > 0:
            ideal = max(1, math.ceil(total_item_lines / target_files))
            # hold max_lines som øvre hard grense med mindre soft_overflow tillater overskridelse
            capacity = min(ideal, int(pcfg.max_lines))
        else:
            capacity = int(pcfg.max_lines)

        buckets = _first_fit_pack(items, capacity, soft_overflow=soft_overflow)

    # --- Skriv ut bøttene som paste_01.txt, paste_02.txt, ... + lag index.txt ---
    written: list[tuple[Path, int]] = []
    # index_sections: list per paste-file; hver seksjon er list av (display_rel, code_lines)
    index_sections: list[list[tuple[str,int]]] = []
    total_lines_written = 0

    for idx, bucket in enumerate(buckets, start=1):
        paste_path = pcfg.out_dir / f"paste_{idx:02d}.txt"
        section_rows: list[tuple[str,int]] = []
        with paste_path.open("w", encoding="utf-8") as fh:
            for it in bucket:
                fh.write(it.rendered)
                # hent LINES og CHUNK for visning i index
                try:
                    m_lines = re.search(r"^LINES:\s+(\d+)$", it.rendered, flags=re.M)
                    code_lines = int(m_lines.group(1)) if m_lines else 0
                except Exception:
                    code_lines = 0
                # finn chunk info (valgfritt for visning)
                m_chunk = re.search(r"^CHUNK:\s*(\d+)\/(\d+)", it.rendered, flags=re.M)
                if m_chunk:
                    disp = f"{it.rel_path} ({m_chunk.group(1)}/{m_chunk.group(2)})"
                else:
                    disp = it.rel_path
                section_rows.append((disp, code_lines))
        lines_this = sum(it.lines for it in bucket)
        total_lines_written += lines_this
        written.append((paste_path, lines_this))
        index_sections.append(section_rows)

    # Logg per paste-fil
    for p, n in written:
        print(f"skrev {p.name}  ({n} linjer)")

    # Skriv index.txt med nytt format: seksjonsvis (Del X av totalt Y deler:)
    idx_path = pcfg.out_dir / "index.txt"
    total_paste_files = len(written)
    with idx_path.open("w", encoding="utf-8") as fh:
        fh.write("# index over innhold i paste_*.txt\n")
        fh.write("# Format per seksjon:\n")
        fh.write("# Del <pastefile_number> av totalt <tpastefile_number> deler:\n")
        fh.write("# <relativ/path> | <linjer>\n\n")
        for i, section in enumerate(index_sections, start=1):
            fh.write(f"Del {i} av totalt {total_paste_files} deler:\n")
            for rel_disp, ln in section:
                fh.write(f"{rel_disp}  |  {ln} linjer\n")
            fh.write("\n")
        fh.write("\n# Genererte filer:\n")
        for p, _ in written:
            fh.write(p.name + "\n")
        # total filer = antall oppføringer i sections
        total_entries = sum(len(s) for s in index_sections)
        fh.write(f"\nTotalt filer: {total_entries}\n")
        fh.write(f"Antall paste-filer: {len(written)}\n")

    # Slutt-rapport til stdout (for UI)
    print("\n== Oppsummering ==")
    print(f"Totalt filer: {sum(len(s) for s in index_sections)}")
    total_code_lines = 0
    for section in index_sections:
        for _, ln in section:
            try:
                total_code_lines += int(ln)
            except Exception:
                pass
    print(f"Totalt linjer: {total_code_lines}")
    print(f"Antall paste-filer: {len(written)}")
    try:
        print(f"Index: {idx_path.relative_to(pcfg.project_root).as_posix()}")
    except Exception:
        print(f"Index: {idx_path.as_posix()}")
