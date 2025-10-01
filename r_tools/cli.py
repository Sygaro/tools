# /home/reidar/tools/r_tools/cli.py
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from .config import load_config, load_config_info
from .tools.code_search import run_search
from .tools.clean_temp import run_clean
from .tools.format_code import run_format
from .tools.gh_raw import run_gh_raw
from .tools.paste_chunks import run_paste

VERSION = "0.6.0"

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="rt", description="r_tools CLI")
    p.add_argument("--version", action="store_true", help="Vis versjon og avslutt")
    sub = p.add_subparsers(dest="cmd", required=True)

    # ---- search ----
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
    sp.add_argument(
        "--all", action="store_true", help="Krev at alle termer matcher samme linje"
    )

    # ---- paste ----
    pp = sub.add_parser("paste", help="Lag innlimingsklare filer (chunks)")
    pp.add_argument("--project", type=Path, help="Overstyr paste.root")
    pp.add_argument("--out", type=Path, help="Overstyr paste.out_dir")
    pp.add_argument("--max-lines", type=int, help="Overstyr paste.max_lines")
    pp.add_argument("--allow-binary", action="store_true")
    pp.add_argument("--include", action="append", default=None)
    pp.add_argument("--exclude", action="append", default=None)
    pp.add_argument("--list-only", action="store_true")

    # ---- gh-raw ----
    gp = sub.add_parser("gh-raw", help="List raw GitHub-URLer for repo tree")
    gp.add_argument("--user")
    gp.add_argument("--repo")
    gp.add_argument("--branch")
    gp.add_argument("--path-prefix", default="")
    gp.add_argument("--json", action="store_true")

    # ---- format ----
    fp = sub.add_parser("format", help="Kjør prettier/black/ruff ihht config")
    fp.add_argument("--dry-run", action="store_true")

    # ---- clean ----
    cp = sub.add_parser("clean", help="Slett midlertidige filer/kataloger")
    cp.add_argument("--project", type=Path, help="Overstyr project_root")
    cp.add_argument(
        "--what",
        nargs="*",
        choices=[
            "pycache",
            "pytest_cache",
            "mypy_cache",
            "ruff_cache",
            "coverage",
            "build",
            "dist",
            "editor",
            "ds_store",
            "thumbs_db",
            "node_modules",
        ],
        help="Begrens til disse målene",
    )
    cp.add_argument("--skip", nargs="*", default=[], help="Hopp over disse målene")
    cp.add_argument(
        "--dry-run", action="store_true", help="Vis hva som slettes uten å slette"
    )
    cp.add_argument("--yes", action="store_true", help="Utfør faktisk sletting")
    cp.add_argument("--extra", nargs="*", default=None, help="Tilleggs-globs å slette")

    # ---- serve ----
    sv = sub.add_parser("serve", help="Start web-UI server")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8765)

    # ---- backup ----
    bp = sub.add_parser(
        "backup", help="Kjør backup_app/backup.py med r_tools-integrasjon"
    )
    bp.add_argument("--config")
    bp.add_argument("--profile")
    bp.add_argument("--project")
    bp.add_argument("--source")
    bp.add_argument("--dest")
    bp.add_argument("--version")
    bp.add_argument("--no-version", action="store_true")
    bp.add_argument("--tag")
    bp.add_argument("--format", choices=["zip", "tar.gz", "tgz"])
    bp.add_argument("--include-hidden", action="store_true")
    bp.add_argument("--exclude", action="append", default=[])
    bp.add_argument("--keep", type=int)
    bp.add_argument("--list", action="store_true")
    bp.add_argument("--dry-run", action="store_true")
    bp.add_argument("--no-verify", action="store_true")
    bp.add_argument("--verbose", action="store_true")
    bp.add_argument("--dropbox-path")
    bp.add_argument("--dropbox-mode", choices=["add", "overwrite"])

    # ---- list ----
    lp = sub.add_parser("list", help="Vis effektiv config / meta-info")
    lp.add_argument(
        "--tool",
        choices=["search", "paste", "gh_raw", "format", "clean", "backup"],
        help="Begrens til verktøy",
    )
    lp.add_argument(
        "--project",
        type=Path,
        help="Prosjekt-root for evaluering (overstyrer project_root)",
    )

    return p

def _print_debug_header():
    if os.environ.get("RT_DEBUG") == "1":
        try:
            import r_tools
            import inspect

            print(f"[rt] python: {sys.executable}")
            print(f"[rt] r_tools: {inspect.getsourcefile(r_tools) or r_tools.__file__}")
        except Exception as e:
            print(f"[rt] debug error: {e}")

def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print(f"r_tools {VERSION}")
        return

    _print_debug_header()
    tools_root = Path(__file__).resolve().parents[1]

    if args.cmd == "search":
        cli_overrides: Dict[str, Any] = {}
        if args.ext:
            cli_overrides["include_extensions"] = args.ext
        if args.exclude_dir or args.include_dir or args.exclude_file:
            cli_overrides.setdefault("exclude_dirs", [])
            cli_overrides.setdefault("exclude_files", [])
            cli_overrides["exclude_dirs"] += args.exclude_dir
            cli_overrides["exclude_files"] += args.exclude_file
        if args.case_sensitive:
            cli_overrides["case_insensitive"] = False

        cfg = load_config("search_config.json", args.project, cli_overrides or None)
        run_search(
            cfg=cfg,
            terms=args.terms or None,
            use_color=not args.no_color,
            show_count=args.count,
            max_size=args.max_size,
            require_all=args.all,
        )
        return

    if args.cmd == "paste":
        ov: Dict[str, Any] = {"paste": {}}
        if args.out:
            ov["paste"]["out_dir"] = str(args.out)
        if args.project:
            ov["paste"]["root"] = str(args.project)
        if args.max_lines:
            ov["paste"]["max_lines"] = args.max_lines
        if args.allow_binary:
            ov["paste"]["allow_binary"] = True
        if args.include:
            ov["paste"]["include"] = args.include
        if args.exclude:
            ov["paste"]["exclude"] = args.exclude
        cfg = load_config("paste_config.json", None, ov)
        run_paste(cfg, list_only=args.list_only)
        return

    if args.cmd == "gh-raw":
        ov = {"gh_raw": {}}
        if args.user:
            ov["gh_raw"]["user"] = args.user
        if args.repo:
            ov["gh_raw"]["repo"] = args.repo
        if args.branch:
            ov["gh_raw"]["branch"] = args.branch
        if args.path_prefix is not None:
            ov["gh_raw"]["path_prefix"] = args.path_prefix
        cfg = load_config("gh_raw_config.json", None, ov)
        run_gh_raw(cfg, as_json=args.json)
        return

    if args.cmd == "format":
        cfg = load_config("format_config.json")
        run_format(cfg, dry_run=args.dry_run)
        return

    if args.cmd == "clean":
        ov: Dict[str, Any] = {}
        if args.project:
            ov["project_root"] = str(args.project)
        if args.extra is not None:
            ov.setdefault("clean", {})
            ov["clean"]["extra_globs"] = args.extra
        cfg = load_config("clean_config.json", None, ov)

        perform = bool(args.yes)
        dry_run = not perform
        if args.dry_run:
            dry_run = True

        run_clean(cfg, only=args.what, skip=args.skip, dry_run=dry_run)
        return

    if args.cmd == "backup":
        from .tools.backup_integration import run_backup

        ov: Dict[str, Any] = {}
        for k in [
            "config",
            "profile",
            "project",
            "source",
            "dest",
            "version",
            "tag",
            "format",
            "dropbox_path",
            "dropbox_mode",
        ]:
            v = getattr(args, k.replace("-", "_"))
            if v not in (None, ""):
                ov[k] = v
        # bools
        if args.no_version:
            ov["no_version"] = True
        if args.include_hidden:
            ov["include_hidden"] = True
        if args.list:
            ov["list"] = True
        if args.dry_run:
            ov["dry_run"] = True
        if args.no_verify:
            ov["no_verify"] = True
        if args.verbose:
            ov["verbose"] = True
        if args.exclude:
            ov["exclude"] = args.exclude
        if args.keep is not None:
            ov["keep"] = args.keep

        rc, out = run_backup(ov)
        print(out, end="" if out.endswith("\n") else "\n")
        sys.exit(rc)

    if args.cmd == "serve":
        import signal

        host = getattr(args, "host", "0.0.0.0")
        port = str(getattr(args, "port", 8765))

        try:
            import uvicorn  # noqa: F401
        except Exception as e:
            print(f"[serve] uvicorn mangler i venv: {e}")
            print(
                "Tips: /home/reidar/tools/venv/bin/pip install uvicorn fastapi pydantic"
            )
            sys.exit(1)

        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "r_tools.tools.webui:app",
            "--host",
            host,
            "--port",
            port,
            "--log-level",
            "info",
        ]
        print("[serve] Kommando:", " ".join(cmd))
        print(
            f"[serve] Starter r_tools UI på http://{host}:{port} (Ctrl+C for å stoppe)"
        )

        proc = subprocess.Popen(cmd)
        try:
            rc = proc.wait()
            print(f"[serve] uvicorn avsluttet med kode {rc}")
            sys.exit(rc)
        except KeyboardInterrupt:
            print("\n[serve] Avslutter … (Ctrl+C)")
            try:
                proc.send_signal(signal.SIGINT)
                rc = proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    rc = proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    rc = proc.wait()
            print(f"[serve] Stoppet (exit {rc})")
            sys.exit(0)

    if args.cmd == "list":
        # Egen: backup meta + profiler
        if args.tool == "backup":
            from .tools.backup_integration import get_backup_info

            info_b = get_backup_info()
            print("== Kilder ==")
            print(f"tools_root        : {tools_root}")
            print(f"config_dir        : {info_b.get('config_dir')}")
            print("\n== Backup ==")
            print(f"script            : {info_b.get('script')}")
            print(f"script_exists     : {info_b.get('script_exists')}")
            print(f"profiles          : {info_b.get('profiles')}")
            print(f"profiles_exists   : {info_b.get('profiles_exists')}")
            print(f"default_profile   : {info_b.get('profiles_default')}")
            names = info_b.get("profiles_names") or []
            if names:
                print("profiles_names    :", ", ".join(names))
            return

        # Ordinær config-visning
        tool_to_cfg = {
            None: None,
            "search": "search_config.json",
            "paste": "paste_config.json",
            "gh_raw": "gh_raw_config.json",
            "format": "format_config.json",
            "clean": "clean_config.json",
        }
        cfg, info = load_config_info(
            tool_to_cfg[args.tool] if args.tool else None, project_override=args.project
        )

        print("== Kilder ==")
        for k in [
            "tools_root",
            "global_config",
            "tool_config",
            "project_file",
            "project_override",
        ]:
            print(f"{k:18}: {info.get(k)}")

        if args.tool == "search":
            eff = {
                k: cfg.get(k)
                for k in [
                    "project_root",
                    "include_extensions",
                    "exclude_dirs",
                    "exclude_files",
                    "case_insensitive",
                    "search_terms",
                ]
            }
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
        elif args.tool == "clean":
            eff = cfg.get("clean", {})
            base = "clean"
        else:
            eff = cfg
            base = ""

        print("\n== Effektiv config ==")
        print(json.dumps(eff, indent=2, ensure_ascii=False))

        print("\n== Opprinnelse (siste skriver vinner) ==")
        prov = info.get("provenance", {})
        for k in sorted(prov):
            if base and not k.startswith(base + "."):
                continue
            print(f"{k:40} ← {prov[k]}")
        return

    print(f"Ukjent kommando: {args.cmd!r}")
    sys.exit(2)

if __name__ == "__main__":
    main()
