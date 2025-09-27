# /home/reidar/tools/r_tools/tools/paste_chunks.py
from __future__ import annotations
from pathlib import Path
from typing import List, Tuple, Dict
import hashlib, os

FRAME_TOP = "===== BEGIN FILE ====="
FRAME_END = "===== END FILE ====="
CODE_BEGIN = "----- BEGIN CODE -----"
CODE_END = "----- END CODE -----"

def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()

def _is_text_utf8(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            data = f.read()
        data.decode("utf-8")
        return True
    except Exception:
        return False

def _read_text_utf8(path: Path) -> str:
    with path.open("rb") as f:
        data = f.read()
    return data.decode("utf-8", errors="replace")

def _normalize_newlines(s: str) -> str:
    return s.replace("\r\n", "\n").replace("\r", "\n")

def _brace_expand_one(pattern: str) -> List[str]:
    start = pattern.find("{")
    if start == -1:
        return [pattern]
    depth = 0
    for i in range(start, len(pattern)):
        if pattern[i] == "{":
            depth += 1
        elif pattern[i] == "}":
            depth -= 1
            if depth == 0:
                inside = pattern[start+1:i]
                before = pattern[:start]
                after = pattern[i+1:]
                parts = [p.strip() for p in inside.split(",") if p.strip()]
                expanded = [before + p + after for p in parts]
                result: List[str] = []
                for e in expanded:
                    result.extend(_brace_expand_one(e))
                return result
    return [pattern]

def _brace_expand(pattern: str) -> List[str]:
    acc = [pattern]; changed = True
    while changed:
        changed = False; new_acc: List[str] = []
        for p in acc:
            expanded = _brace_expand_one(p)
            if len(expanded) > 1 or expanded[0] != p: changed = True
            new_acc.extend(expanded)
        acc = new_acc
    return acc

def _normalize_pattern(pat: str) -> str:
    while pat.startswith("/"): pat = pat[1:]
    return pat

def _expand_patterns(patterns: List[str]) -> List[str]:
    out: List[str] = []
    for pat in patterns or []:
        pat = _normalize_pattern(pat)
        out.extend(_brace_expand(pat))
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq

def _collect_files(root: Path, includes: List[str], excludes: List[str],
                   only_globs: List[str] | None, skip_globs: List[str] | None) -> List[Path]:
    root = root.resolve()
    includes = _expand_patterns(includes)
    excludes = _expand_patterns(excludes)
    only_globs = _expand_patterns(only_globs or [])
    skip_globs = _expand_patterns(skip_globs or [])

    # Pre-filter: bygg kandidat-sett raskt
    candidates: set[Path] = set()
    if only_globs:
        for pat in only_globs:
            for p in root.glob(pat):
                if p.is_file(): candidates.add(p.resolve())
                elif p.is_dir():
                    for sub in p.rglob("*"):
                        if sub.is_file(): candidates.add(sub.resolve())
    else:
        # fallback: inkluder alle filer raskt
        for p in root.rglob("*"):
            if p.is_file(): candidates.add(p.resolve())

    # Skip-globs: fjern tidlig
    for pat in skip_globs:
        for p in root.glob(pat):
            if p.is_file() and p.resolve() in candidates:
                candidates.remove(p.resolve())
            elif p.is_dir():
                for sub in p.rglob("*"):
                    rp = sub.resolve()
                    if sub.is_file() and rp in candidates:
                        candidates.discard(rp)

    # Inkluder/ekskluder: nøyaktig filtrering
    include_set: set[Path] = set()
    for pat in includes:
        for p in root.glob(pat):
            if p.is_file(): include_set.add(p.resolve())

    exclude_set: set[Path] = set()
    for pat in excludes:
        for p in root.glob(pat):
            if p.is_file(): exclude_set.add(p.resolve())
            elif p.exists() and p.is_dir():
                for sub in p.rglob("*"):
                    if sub.is_file(): exclude_set.add(sub.resolve())

    files = sorted([p for p in candidates if p in include_set and p not in exclude_set])
    return files

def _build_framed_block(path: Path, content: str, sha256: str) -> str:
    content = _normalize_newlines(content)
    line_count = content.count("\n") + (0 if content.endswith("\n") else 1)
    header = [
        FRAME_TOP,
        f"PATH: {path.as_posix()}",
        f"LINES: {line_count}",
        "CHUNK: 1/1",
        f"SHA256: {sha256}",
        CODE_BEGIN,
    ]
    footer = [CODE_END, FRAME_END]
    return "\n".join(header) + "\n" + content + "\n" + "\n".join(footer) + "\n"

def _write_chunks(blocks: List[Tuple[Path, str]], out_dir: Path, max_lines: int) -> List[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    outputs: List[Path] = []
    buf: List[str] = []; buf_lines = 0; part = 1
    def flush():
        nonlocal buf, buf_lines, part
        if not buf: return
        out_path = out_dir / f"paste_{part:03d}.txt"
        with out_path.open("w", encoding="utf-8") as f:
            f.write("".join(buf))
        outputs.append(out_path); buf = []; buf_lines = 0
    def count_lines(s: str) -> int:
        return s.count("\n") + (0 if s.endswith("\n") else 1)
    for (_path, block) in blocks:
        block_lines = count_lines(block)
        if buf_lines + block_lines > max_lines and buf:
            flush(); part += 1
        buf.append(block); buf_lines += block_lines
    flush(); return outputs

def _create_index(mapping: List[Tuple[Path, Path]], out_dir: Path) -> Path:
    index_path = out_dir / "INDEX.txt"
    with index_path.open("w", encoding="utf-8") as f:
        f.write("# Index over filer og hvilken paste_NNN.txt de ligger i\n\n")
        current = None
        for out_file, src in mapping:
            if out_file != current:
                f.write(f"\n## {out_file.name}\n"); current = out_file
            f.write(f"- {src.as_posix()}\n")
    return index_path

def _resolve_relative(root: Path, maybe_path: str | None, default_rel: str) -> Path:
    """Hvorfor: tillat relative stier i JSON; gidder ikke absolute."""
    if not maybe_path:
        return (root / default_rel).resolve()
    p = Path(maybe_path)
    if p.is_absolute():
        return p.resolve()
    return (root / p).resolve()

def run_paste(cfg: Dict, list_only: bool = False) -> None:
    pcfg: Dict = cfg.get("paste", {})
    # root default: prosjekt-root (eller ".")
    project_root = Path(cfg.get("project_root", ".")).resolve()
    root = _resolve_relative(project_root, pcfg.get("root", "."), ".")
    out_dir = _resolve_relative(root, pcfg.get("out_dir", "paste_out"), "paste_out")

    includes = list(pcfg.get("include", []))
    excludes = list(pcfg.get("exclude", []))
    only_globs = list(pcfg.get("only_globs", []))
    skip_globs = list(pcfg.get("skip_globs", []))
    max_lines = int(pcfg.get("max_lines", 4000))
    allow_binary = bool(pcfg.get("allow_binary", False))

    sources = _collect_files(root, includes, excludes, only_globs, skip_globs)
    if not sources:
        print("Ingen filer funnet med de angitte mønstrene."); return

    if list_only:
        print(f"{len(sources)} fil(er):")
        for s in sources:
            print("-", s.relative_to(root).as_posix())
        return

    blocks: List[Tuple[Path, str]] = []
    skipped: List[Path] = []
    for src in sources:
        if _is_text_utf8(src):
            text = _read_text_utf8(src)
            digest = _sha256_file(src)
            rel = src.relative_to(root)
            block = _build_framed_block(rel, text, digest)
            blocks.append((src, block))
        else:
            if allow_binary:
                with src.open("rb") as f:
                    data = f.read()
                digest = hashlib.sha256(data).hexdigest()
                rel = src.relative_to(root)
                block = _build_framed_block(rel, data.hex(), digest)
                blocks.append((src, block))
            else:
                skipped.append(src)

    blocks.sort(key=lambda t: t[0].as_posix())
    outputs = _write_chunks(blocks, out_dir, max_lines)

    mapping: List[Tuple[Path, Path]] = []
    for out_file in outputs:
        with out_file.open("r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PATH: "):
                    p = line.strip().split("PATH: ", 1)[1]
                    mapping.append((out_file, Path(p)))
    index_path = _create_index(mapping, out_dir)

    print(f"Skrev {len(outputs)} output-fil(er) til: {out_dir.as_posix()}")
    for p in outputs:
        with p.open("r", encoding="utf-8") as fh:
            lc = sum(1 for _ in fh)
        print(f" - {p.name}  ({lc} linjer)")
    if skipped:
        print("\nHoppet over binær/ikke-UTF8-filer (sett paste.allow_binary=true for å inkludere):")
        for s in skipped:
            print(f" - {s.relative_to(root).as_posix()}")
    print(f"\nINDEX: {index_path.as_posix()}")
