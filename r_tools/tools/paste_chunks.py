# ./tools/r_tools/tools/paste_chunks.py
from __future__ import annotations

import base64
import fnmatch
import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# --------------------------------------------------------------------------------------------------
# Konfig / typer
# --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PasteConfig:
    project_root: Path
    out_dir: Path
    max_lines: int
    allow_binary: bool
    filename_search: bool
    include: list[str]
    exclude: list[str]
    only_globs: list[str]
    skip_globs: list[str]

# --------------------------------------------------------------------------------------------------
# Hjelpere for glob/filvalg (speiler oppførselen i search/replace mht filename_search)
# --------------------------------------------------------------------------------------------------

def _normalize_globs(globs: Iterable[str] | None, filename_search: bool) -> list[str]:
    """
    Normaliserer globs. Når filename_search=True:
      - rene filnavn uten '/' → '**/<navn>'
      - ellers beholdes mønsteret.
    """
    out: list[str] = []
    for g in globs or []:
        s = str(g).strip()
        if not s:
            continue
        is_pure_filename = ("/" not in s) and not any(ch in s for ch in "*?[]")
        if filename_search and is_pure_filename:
            out.append(f"**/{s}")
        else:
            out.append(s)
    return out

def _under_root(p: Path, root: Path) -> bool:
    try:
        p.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False

def _gather_candidates(
    root: Path,
    include: list[str],
    exclude: list[str],
    only_globs: list[str],
    skip_globs: list[str],
) -> list[Path]:
    """
    Samle kandidater fra include-globs, filtrer bort exclude/skip, og evt. innsnevr til only_globs.
    Returnerer sortert unik liste (absolutte Path).
    """
    inc: list[str] = include or ["**/*.*"]
    exc: list[str] = exclude or []
    only: list[str] = only_globs or []
    skip: list[str] = skip_globs or []

    # 1) Inkluder via globs
    gathered: set[Path] = set()
    for pat in inc:
        for p in root.glob(pat):
            if p.is_file():
                gathered.add(p.resolve())

    # 2) Ekskluder via exclude/skip (relativ sti mot root)
    def _rel_posix(p: Path) -> str | None:
        try:
            return p.resolve().relative_to(root.resolve()).as_posix()
        except Exception:
            return None

    def _excluded_by_globs(rel_posix: str, globs: list[str]) -> bool:
        return any(fnmatch.fnmatch(rel_posix, g) for g in globs)

    filtered: list[Path] = []
    for p in sorted(gathered):
        rel = _rel_posix(p)
        if rel is None:
            continue
        if _excluded_by_globs(rel, exc):
            continue
        if _excluded_by_globs(rel, skip):
            continue
        filtered.append(p)

    # 3) only_globs (hvis satt) → behold bare filer som matcher minst én only_glob
    if only:
        only_filtered: list[Path] = []
        for p in filtered:
            rel = _rel_posix(p)
            if rel is None:
                continue
            if any(fnmatch.fnmatch(rel, g) for g in only):
                only_filtered.append(p)
        filtered = only_filtered

    return filtered

# --------------------------------------------------------------------------------------------------
# Binær/tekst-deteksjon og trygg lesing
# --------------------------------------------------------------------------------------------------

def _looks_binary(data: bytes) -> bool:
    """
    Enkel og robust sjekk:
      - inneholder NUL-byte?
      - høy andel kontrolltegn?
    """
    if not data:
        return False
    if b"\x00" in data:
        return True
    # Tell kontrolltegn (0x00–0x08, 0x0E–0x1F) – ignorer \t \n \r \f \v
    text_whitelist = {0x09, 0x0A, 0x0D, 0x0C, 0x0B}
    ctrl = sum(1 for b in data if b < 0x20 and b not in text_whitelist)
    # Heuristikk: > 30% kontrolltegn → binært
    return (ctrl / len(data)) > 0.30

def _read_utf8_strict(path: Path, sniff_bytes: int = 8192) -> tuple[bool, str | bytes]:
    """
    Returnerer (is_text, content). For tekst: content=str (utf-8-strict).
    For binært: content=bytes.
    """
    with open(path, "rb") as f:
        head = f.read(sniff_bytes)
        if _looks_binary(head):
            # tidlig klassifisering
            rest = f.read()  # les resten for evt. base64
            return False, head + rest
        # prøv streng utf-8 decode (strikt)
        try:
            # Les hele filen i minne. For forventede prosjektfiler er dette ok.
            # (Hvis du ønsker streaming-diff senere kan vi gjøre inkrementell decode)
            data = head + f.read()
            text = data.decode("utf-8", errors="strict")
            return True, text
        except UnicodeDecodeError:
            # Dekode feilet → behandle som binært
            rest = f.read()
            return False, head + rest  # (rest er tom her; med strict-try før f.read() null)

# --------------------------------------------------------------------------------------------------
# Chunk-writer (samler flere filer i én paste_XXXX.txt med linjetak)
# --------------------------------------------------------------------------------------------------

class ChunkWriter:
    def __init__(self, out_dir: Path, max_lines: int) -> None:
        self.out_dir = out_dir
        self.max_lines = max(50, int(max_lines))  # vern mot altfor små verdier
        self._current_lines = 0
        self._index = 0
        self._cur_path: Path | None = None
        self._cur_fp = None  # type: ignore[var-annotated]
        self._written_files: list[Path] = []

        self.out_dir.mkdir(parents=True, exist_ok=True)

    def _open_new(self) -> None:
        if self._cur_fp:
            self._cur_fp.close()
        self._index += 1
        filename = f"paste_{self._index:04d}.txt"
        self._cur_path = (self.out_dir / filename).resolve()
        self._cur_fp = open(self._cur_path, "w", encoding="utf-8", newline="\n")
        self._current_lines = 0
        self._written_files.append(self._cur_path)

    def _ensure_capacity(self, lines_needed: int) -> None:
        if self._cur_fp is None:
            self._open_new()
            return
        if self._current_lines + lines_needed > self.max_lines:
            self._open_new()

    def write_block(
        self,
        project_root: Path,
        file_path: Path,
        content_text: str,
        chunk_idx: int,
        chunk_total: int,
    ) -> None:
        """
        Skriver en filblokk i samme format som du viste tidligere.
        content_text må være ferdig-tekst (utf-8), ikke inkludere trailing newline (vi håndterer).
        """
        rel = file_path.resolve().relative_to(project_root.resolve()).as_posix()
        lines = content_text.splitlines()
        # Bygg overskrift + kodeblokk
        sha256 = hashlib.sha256(content_text.encode("utf-8")).hexdigest()
        header = [
            "===== BEGIN FILE =====",
            f"PATH: {rel}",
            f"LINES: {len(lines)}",
            f"CHUNK: {chunk_idx}/{chunk_total}",
            f"SHA256: {sha256}",
            "----- BEGIN CODE -----",
        ]
        footer = [
            "----- END CODE -----",
            "===== END FILE =====",
        ]
        needed = len(header) + len(lines) + len(footer)
        self._ensure_capacity(needed)

        assert self._cur_fp is not None
        for ln in header:
            self._cur_fp.write(ln + "\n")
        for ln in lines:
            self._cur_fp.write(ln + "\n")
        for ln in footer:
            self._cur_fp.write(ln + "\n")
        self._current_lines += needed

    def close(self) -> None:
        if self._cur_fp:
            self._cur_fp.close()
            self._cur_fp = None

    @property
    def written_files(self) -> list[Path]:
        return list(self._written_files)

# --------------------------------------------------------------------------------------------------
# Kjernefunksjon
# --------------------------------------------------------------------------------------------------

def _read_cfg(cfg: dict) -> PasteConfig:
    p = cfg.get("paste", {}) or {}
    root = Path(p.get("root", cfg.get("project_root", "."))).resolve()
    out = Path(p.get("out_dir", "paste_out"))
    out = out if out.is_absolute() else (root / out)
    max_lines = int(p.get("max_lines", 4000))
    allow_binary = bool(p.get("allow_binary", False))
    filename_search = bool(p.get("filename_search", False))

    include = _normalize_globs(p.get("include") or ["*.*", "**/*.*"], filename_search)
    exclude = _normalize_globs(p.get("exclude") or [], filename_search)
    only_globs = _normalize_globs(p.get("only_globs") or [], filename_search)
    skip_globs = _normalize_globs(p.get("skip_globs") or [], filename_search)

    return PasteConfig(
        project_root=root,
        out_dir=out.resolve(),
        max_lines=max_lines,
        allow_binary=allow_binary,
        filename_search=filename_search,
        include=list(include),
        exclude=list(exclude),
        only_globs=list(only_globs),
        skip_globs=list(skip_globs),
    )

def _format_binary_block(data: bytes, project_root: Path, file_path: Path) -> str:
    """
    Returnerer en enkel, sikker representasjon for binærfiler.
    Hvis du vil ha hex i stedet for base64 kan vi endre dette med et lite flagg senere.
    """
    b64 = base64.b64encode(data).decode("ascii")
    rel = file_path.resolve().relative_to(project_root.resolve()).as_posix()
    return f"# BINARY FILE (base64) — {rel}\n" f"# length={len(data)} bytes\n" f"{b64}\n"

def _iter_indexed(files: list[Path]) -> Iterator[tuple[int, int, Path]]:
    total = len(files)
    for i, p in enumerate(files, start=1):
        yield i, total, p

def run_paste(cfg: dict, list_only: bool = False) -> None:
    """
    Genererer én eller flere paste_XXXX.txt i 'paste_out' (eller valgt out_dir).
    - Skriver ingen filer når list_only=True; da listas kun kandidatfiler.
    - Hver paste-fil holder seg under paste.max_lines (default 4000).
    """
    pcfg = _read_cfg(cfg)
    root = pcfg.project_root

    if not root.exists() or not root.is_dir():
        print(f"[paste] Ugyldig project root: {root}")
        return

    files = _gather_candidates(
        root=root,
        include=pcfg.include,
        exclude=pcfg.exclude,
        only_globs=pcfg.only_globs,
        skip_globs=pcfg.skip_globs,
    )

    # Listevisning
    if list_only:
        print(f"[paste] Project: {root}")
        print(f"[paste] Matchede filer: {len(files)}")
        for p in files:
            try:
                print(p.resolve().relative_to(root.resolve()).as_posix())
            except Exception:
                print(p.as_posix())
        return

    writer = ChunkWriter(pcfg.out_dir, pcfg.max_lines)
    skipped_bin: list[str] = []
    written_count = 0

    try:
        for idx, total, path in _iter_indexed(files):
            is_text, payload = _read_utf8_strict(path)
            if not is_text and not pcfg.allow_binary:
                # hopp over binære filer
                rel = path.resolve().relative_to(root.resolve()).as_posix()
                skipped_bin.append(rel)
                continue

            if is_text:
                text = payload if isinstance(payload, str) else payload.decode("utf-8", errors="replace")
            else:
                # base64-innpakkede binærfiler som tekst
                assert isinstance(payload, (bytes, bytearray))
                text = _format_binary_block(bytes(payload), root, path)

            writer.write_block(
                project_root=root,
                file_path=path,
                content_text=text.rstrip("\n"),
                chunk_idx=idx,
                chunk_total=total,
            )
            written_count += 1
    finally:
        writer.close()

    # Oppsummering
    print(f"[paste] Project: {root}")
    print(f"[paste] Filer funnet : {len(files)}")
    print(f"[paste] Filer skrevet: {written_count}")
    if skipped_bin:
        print(f"[paste] Hoppet over binær (allow_binary=false): {len(skipped_bin)}")
        for rel in skipped_bin:
            print(f"  - {rel}")
    out_files = writer.written_files
    if out_files:
        print("[paste] Output:")
        for p in out_files:
            print(f"  - {p}")
    else:
        print("[paste] Ingen output generert (ingen matchende filer).")
