# /home/reidar/tools/r_tools/cli.py
from __future__ import annotations
import argparse
from pathlib import Path
from .config import load_config, load_config_info
from .tools.code_search import run_search
from .tools.paste_chunks import run_paste
from .tools.gh_raw import run_gh_raw
from .tools.format_code import run_format

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rt", description="Tools CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="Søk i prosjektfiler")
    sp.add_argument("terms", nargs="*", help="Regex-termin(e). Tom → bruk config.")
    sp.add_argument("--project", type=Path)
    sp.add_argument("--ext", nargs="*")
    sp.add_argument("--include-dir", nargs="*", default=[])
    sp.add_argument("--exclude-dir", nargs="*", default=[])
    sp.add_argument("--exclude-file", nargs="*", default=[])
    sp.add_argument("--case-sensitive", action="store_true")
    sp.add_argument("--no-color", action="store_true")
    sp.add_argument("--count", action="store_true")
    sp.add_argument("--max-size", type=int, default=2_000_000)

    pp = sub.add_parser("paste", help="Lag innlimingsklare filer (chunks)")
    pp.add_argument("--project", type=Path, help="Overstyr paste.root")
    pp.add_argument("--out", type=Path, help="Overstyr paste.out_dir")
    pp.add_argument("--max-lines", type=int, help="Overstyr paste.max_lines")
    pp.add_argument("--allow-binary", action="store_true")
    pp.add_argument("--include", action="append", default=None)
    pp.add_argument("--exclude", action="append", default=None)
    pp.add_argument("--list-only", action="store_true")

    gp = sub.add_parser("gh-raw", help="List raw GitHub-URLer for repo tree")
    gp.add_argument("--user"); gp.add_argument("--repo"); gp.add_argument("--branch")
    gp.add_argument("--path-prefix", default=""); gp.add_argument("--json", action="store_true")

    fp = sub.add_parser("format", help="Kjør prettier/black/ruff ihht config")
    fp.add_argument("--dry-run", action="store_true")

    lp = sub.add_parser("list", help="Vis config-kilder/verdier og opprinnelse (diff)")
    lp.add_argument("--tool", choices=["search", "paste", "gh_raw", "format"], help="Begrens til et verktøy")
    lp.add_argument("--project", type=Path)

    return p

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.cmd == "search":
        cli_overrides = {}
        if args.ext: cli_overrides["include_extensions"] = args.ext
        if args.exclude_dir or args.include_dir or args.exclude_file:
            cli_overrides.setdefault("exclude_dirs", []); cli_overrides.setdefault("exclude_files", [])
            cli_overrides["exclude_dirs"] += args.exclude_dir
            cli_overrides["exclude_files"] += args.exclude_file
        if args.case_sensitive: cli_overrides["case_insensitive"] = False
        cfg = load_config("search_config.json", args.project, cli_overrides or None)
        run_search(cfg=cfg, terms=args.terms or None,
                   use_color=not args.no_color, show_count=args.count, max_size=args.max_size)
        return

    if args.cmd == "paste":
        ov = {"paste": {}}
        if args.out:        ov["paste"]["out_dir"] = str(args.out)
        if args.project:    ov["paste"]["root"] = str(args.project)
        if args.max_lines:  ov["paste"]["max_lines"] = args.max_lines
        if args.allow_binary: ov["paste"]["allow_binary"] = True
        if args.include:    ov["paste"]["include"] = args.include
        if args.exclude:    ov["paste"]["exclude"] = args.exclude
        cfg = load_config("paste_config.json", None, ov)
        run_paste(cfg, list_only=args.list_only)
        return

    if args.cmd == "gh-raw":
        ov = {"gh_raw": {}}
        if args.user: ov["gh_raw"]["user"] = args.user
        if args.repo: ov["gh_raw"]["repo"] = args.repo
        if args.branch: ov["gh_raw"]["branch"] = args.branch
        if args.path_prefix is not None: ov["gh_raw"]["path_prefix"] = args.path_prefix
        cfg = load_config("gh_raw_config.json", None, ov)
        run_gh_raw(cfg, as_json=args.json)
        return

    if args.cmd == "format":
        cfg = load_config("format_config.json")
        run_format(cfg, dry_run=args.dry_run)
        return

    if args.cmd == "list":
        tool_to_cfg = {
            None: None, "search": "search_config.json", "paste": "paste_config.json",
            "gh_raw": "gh_raw_config.json", "format": "format_config.json"
        }
        cfg, info = load_config_info(tool_to_cfg[args.tool] if args.tool else None,
                                     project_override=args.project)

        print("== Kilder ==")
        for k in ["tools_root", "global_config", "tool_config", "project_file", "project_override"]:
            print(f"{k:18}: {info.get(k)}")

        # Velg utsnitt
        if args.tool == "search":
            eff = {k: cfg.get(k) for k in ["project_root","include_extensions","exclude_dirs","exclude_files","case_insensitive","search_terms"]}
            base = "search"
        elif args.tool == "paste":
            eff = cfg.get("paste", {})
            base = "paste"
        elif args.tool == "gh_raw":
            eff = cfg.get("gh_raw", {})
            base = "gh_raw"
        elif args.tool == "format":
            eff = cfg.get("format", {})
            base = "format"
        else:
            eff = cfg; base = ""

        print("\n== Effektiv config ==")
        import json as _json
        print(_json.dumps(eff, indent=2, ensure_ascii=False))

        # Provenance/diff
        print("\n== Opprinnelse (siste skriver vinner) ==")
        prov = info.get("provenance", {})
        def show_prov(ns: str):
            for k in sorted(prov):
                if ns and not k.startswith(ns + "."):  # filtrer på namespace
                    continue
                src = prov[k]
                print(f"{k:40} ← {src}")
        if base:
            show_prov(base)
        else:
            show_prov("")  # alt
        return

if __name__ == "__main__":
    main()
