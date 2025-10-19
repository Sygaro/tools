# ./tools/r_tools/tools/webui.py
from __future__ import annotations

import io
import json
import os
import time
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, TypedDict

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.gzip import GZipMiddleware
from starlette.requests import Request

from ..config import deep_merge, load_config
from .backup_integration import get_backup_info, run_backup
from .clean_temp import run_clean
from .code_search import run_search
from .diag_dropbox import diag_dropbox
from .format_code import run_format
from .gh_raw import run_gh_raw
from .paste_chunks import run_paste
from .replace_code import run_replace

# Kataloger
TOOLS_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = Path(os.environ.get("RTOOLS_CONFIG_DIR", str(TOOLS_ROOT / "configs"))).resolve()
WEBUI_DIR = TOOLS_ROOT / "r_tools" / "webui_app"

def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def _external_index_html() -> str | None:
    idx = WEBUI_DIR / "index.html"
    if idx.is_file():
        return _read_text_safe(idx)
    return None

print(f"[webui] TOOLS_ROOT = {TOOLS_ROOT}")
print(f"[webui] CONFIG_DIR = {CONFIG_DIR}  (env RTOOLS_CONFIG_DIR={os.environ.get('RTOOLS_CONFIG_DIR')!r})")
print(f"[webui] projects_config.json exists? {(CONFIG_DIR / 'projects_config.json').is_file()}")

class ProjectEntry(TypedDict):
    name: str
    path: str
    abs_path: str
    exists: bool

def _load_projects() -> list[ProjectEntry]:
    cfg_path = CONFIG_DIR / "projects_config.json"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Fant ikke {cfg_path}")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    projects = data.get("projects")
    if not isinstance(projects, list):
        raise ValueError(f"{cfg_path}: 'projects' må være en liste")
    out: list[ProjectEntry] = []
    for i, p in enumerate(projects):
        if not isinstance(p, dict) or "name" not in p or "path" not in p:
            raise ValueError(f"{cfg_path}: item[{i}] mangler 'name' eller 'path'")
        raw_path = str(p["path"])
        base = TOOLS_ROOT
        abs_path = (Path(raw_path).expanduser() if Path(raw_path).is_absolute() else (base / raw_path)).resolve()
        out.append(ProjectEntry(name=str(p["name"]), path=raw_path, abs_path=str(abs_path), exists=abs_path.exists()))
    if not out:
        raise ValueError(f"{cfg_path}: 'projects' er tom")
    return out

def _load_recipes() -> list[dict[str, Any]]:
    rc = CONFIG_DIR / "recipes_config.json"
    if not rc.is_file():
        return []
    data = json.loads(rc.read_text(encoding="utf-8"))
    return list(data.get("recipes", []))

def _capture(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()

def _safe_clean_paste_out(out_dir: Path) -> None:
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for p in out_dir.glob("paste_*.txt"):
            try:
                if p.is_file() or p.is_symlink():
                    p.unlink(missing_ok=True)
            except Exception:
                pass
    except Exception:
        pass

app = FastAPI(title="r_tools UI", default_response_class=JSONResponse)
app.add_middleware(GZipMiddleware, minimum_size=600)

if (WEBUI_DIR / "static").is_dir():
    app.mount("/static", StaticFiles(directory=str(WEBUI_DIR / "static")), name="static")

@app.middleware("http")
async def add_static_cache_headers(request: Request, call_next):
    response = await call_next(request)
    try:
        if request.url.path.startswith("/static/"):
            response.headers.setdefault("Cache-Control", "public, max-age=31536000, immutable")
    except Exception:
        pass
    return response

class RunPayload(BaseModel):
    tool: str
    project: str | None = None
    args: dict[str, Any] = {}

@app.get("/", response_class=HTMLResponse)
def index():
    external = _external_index_html()
    if not external:
        raise HTTPException(
            status_code=500,
            detail=f"Mangler {WEBUI_DIR / 'index.html'} – opprett filene i r_tools/webui_app/ (se /static).",
        )
    return HTMLResponse(external)

@app.get("/api/projects")
def api_projects():
    cfgp = str((CONFIG_DIR / "projects_config.json").resolve())
    try:
        projs = _load_projects()
        return {"projects": projs, "config": cfgp}
    except Exception as e:
        return {"projects": [], "error": f"{type(e).__name__}: {e}", "config": cfgp}

@app.get("/api/recipes")
def api_recipes():
    try:
        return {"recipes": _load_recipes()}
    except Exception:
        return {"recipes": []}

@app.get("/api/clean-config")
def api_clean_config(project: str | None = Query(None)):
    cfg = load_config("clean_config.json", Path(project).resolve() if project else None, None)
    return {"clean": cfg.get("clean", {})}

@app.get("/api/clean-targets")
def api_clean_targets_get(project: str | None = Query(None)):
    cfg = load_config("clean_config.json", Path(project).resolve() if project else None, None)
    return {"targets": (cfg.get("clean", {}) or {}).get("targets", {})}

@app.post("/api/clean-targets")
def api_clean_targets_set(project: str | None = Query(None), body: dict[str, Any] = Body(...)):
    targets = body.get("targets") or {}
    if not isinstance(targets, dict):
        raise HTTPException(status_code=400, detail="targets må være et objekt")
    path = CONFIG_DIR / "clean_config.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        if "clean" not in data or not isinstance(data["clean"], dict):
            data["clean"] = {}
    else:
        data = {"clean": {}}
    data["clean"]["targets"] = targets
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "message": f"Lagret targets til {path}"}

# -------- Git hjelpe-endepunkt (remotes/branches) --------
@app.get("/api/git/branches")
def api_git_branches(project: str | None = Query(None)):
    from .git_tools import list_branches, current_branch
    cfg = load_config("git_config.json", Path(project).resolve() if project else None, None)
    root = Path(cfg.get("project_root", ".")).resolve()
    try:
        arr = list_branches(root)
        cur = current_branch(root)
        return {"branches": arr, "current": cur}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "branches": [], "current": None}


@app.get("/api/git/remotes")
def api_git_remotes(project: str | None = Query(None)):
    from .git_tools import list_remotes as _list_rm
    cfg = load_config("git_config.json", Path(project).resolve() if project else None, None)
    root = Path(cfg.get("project_root", ".")).resolve()
    try:
        arr = _list_rm(root)
        return {"remotes": arr}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "remotes": []}

@app.post("/api/run")
def api_run(body: RunPayload):
    tool = body.tool
    project_path = Path(body.project).resolve() if body.project else None
    args = body.args or {}
    t0 = time.time()

    tool_cfg = {
        "search": "search_config.json",
        "replace": "replace_config.json",
        "paste": "paste_config.json",
        "gh-raw": "gh_raw_config.json",
        "format": "format_config.json",
        "clean": "clean_config.json",
        "git": "git_config.json",
    }.get(tool, None)

    ov: dict[str, Any] = {}
    if project_path:
        ov["project_root"] = str(project_path)

    try:
        if tool == "search":
            if "case_sensitive" in args:
                ov["case_insensitive"] = not bool(args.get("case_sensitive"))
            cfg = load_config(tool_cfg, project_path, ov or None)
            out = _capture(
                run_search,
                cfg=cfg,
                terms=(args.get("terms") or None),
                use_color=False,
                show_count=True,
                max_size=int(args.get("max_size", 2_000_000)),
                require_all=bool(args.get("all", False)),
                files_only=bool(args.get("files_only", False)),
                path_mode=str(args.get("path_mode", "relative")),
                limit_dirs=(args.get("limit_dirs") or None),
                limit_exts=(args.get("limit_exts") or None),
                include=(args.get("include") or None),
                exclude=(args.get("exclude") or None),
                filename_search=bool(args.get("filename_search", False)),
            )
            dt = int((time.time() - t0) * 1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        elif tool == "paste":
            pov: dict[str, Any] = {"paste": {}}
            for key in ["out_dir", "max_lines", "include", "exclude", "filename_search"]:
                if key in args and args[key] not in (None, ""):
                    if key in ("include", "exclude") and args[key] == []:
                        continue
                    pov["paste"][key] = args[key]
            cfg = load_config(tool_cfg, project_path, pov if pov["paste"] else None)
            list_only = bool(args.get("list_only", False))
            if not list_only:
                project_root = Path(cfg.get("project_root", ".")).resolve()
                eff_out = Path(cfg.get("paste", {}).get("out_dir", "paste_out"))
                out_path = (eff_out if eff_out.is_absolute() else (project_root / eff_out)).resolve()
                _safe_clean_paste_out(out_path)
            out = _capture(run_paste, cfg=cfg, list_only=list_only)
            dt = int((time.time() - t0) * 1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        elif tool == "format":
            cfg = load_config(tool_cfg, project_path, ov or None)
            override = args.get("override") or None
            if isinstance(override, dict):
                cfg = deep_merge(cfg, override)
            out = _capture(run_format, cfg=cfg, dry_run=bool(args.get("dry_run", False)))
            dt = int((time.time() - t0) * 1000)
            rc = 0
            if "Traceback (most recent call last)" in out or "[error]" in out:
                rc = 2
            return {"output": out, "summary": {"rc": rc, "duration_ms": dt}}

        elif tool == "clean":
            cov: dict[str, Any] = {"clean": {}}
            if "targets" in args and isinstance(args["targets"], dict):
                cov["clean"]["targets"] = args["targets"]
            if "extra_globs" in args:
                cov["clean"]["extra_globs"] = args["extra_globs"]
            if "skip_globs" in args:
                cov["clean"]["skip_globs"] = args["skip_globs"]
            cfg = load_config("clean_config.json", project_path, cov if cov["clean"] else None)
            mode = (args.get("mode") or "dry").lower()
            perform = mode == "apply"
            dry_run = not perform
            out = _capture(run_clean, cfg=cfg, only=args.get("what") or None, skip=args.get("skip") or [], dry_run=dry_run)
            dt = int((time.time() - t0) * 1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        elif tool == "backup":
            rc, text = run_backup(args or {})
            dt = int((time.time() - t0) * 1000)
            return {"output": text, "rc": rc, "summary": {"rc": rc, "duration_ms": dt}}

        elif tool == "gh-raw":
            gov = {"gh_raw": {}}
            if "path_prefix" in args:
                gov["gh_raw"]["path_prefix"] = args["path_prefix"]
            cfg = load_config(tool_cfg, project_path, gov)
            out = _capture(run_gh_raw, cfg=cfg, as_json=False)
            dt = int((time.time() - t0) * 1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        elif tool == "replace":
            rov: dict[str, Any] = {"replace": {}}
            for k_src, k_dst in [("include", "include"), ("exclude", "exclude"), ("max_size", "max_size")]:
                if k_src in args and args[k_src] not in (None, "", []):
                    rov["replace"][k_dst] = args[k_src]
            cfg = load_config(tool_cfg, project_path, rov if rov["replace"] else None)
            out = _capture(
                run_replace,
                cfg=cfg,
                find=args.get("find", ""),
                replace=args.get("replace", ""),
                regex=bool(args.get("regex", True)),
                case_sensitive=bool(args.get("case_sensitive", False)),
                include=args.get("include") or None,
                exclude=args.get("exclude") or None,
                max_size=int(args.get("max_size", cfg.get("replace", {}).get("max_size", 2_000_000))),
                dry_run=bool(args.get("dry_run", True)),
                backup=bool(args.get("backup", True)),
                show_diff=bool(args.get("show_diff", True)),
                filename_search=bool(args.get("filename_search", False)),
            )
            dt = int((time.time() - t0) * 1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        # i api_run (git-grenen)
        elif tool == "git":
            # RIKTIG import
            from .git_tools import run_git, list_branches, list_remotes, current_branch
            cfg = load_config(tool_cfg, project_path, None)
            out = run_git(cfg, args.get("action","status"), args)
            dt = int((time.time()-t0)*1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}


        else:
            raise HTTPException(status_code=400, detail=f"Ukjent tool: {tool}")

    except Exception as e:
        dt = int((time.time() - t0) * 1000)
        return {"error": f"{type(e).__name__}: {e}", "summary": {"rc": 1, "duration_ms": dt}}

class PreviewPayload(BaseModel):
    project: str | None = None
    path: str

@app.post("/api/format-preview")
def api_format_preview(body: PreviewPayload):
    project_path = Path(body.project).resolve() if body.project else None
    rel = body.path.strip()
    if not rel:
        raise HTTPException(status_code=400, detail="path er påkrevd")
    cfg = load_config("format_config.json", project_path, None)
    project_root = Path(cfg.get("project_root", ".")).resolve()
    abs_path = (project_root / rel).resolve()
    try:
        abs_path.relative_to(project_root)
    except Exception:
        raise HTTPException(status_code=400, detail="path må være relativ til project_root")
    from .format_code import format_preview
    try:
        text = format_preview(cfg, rel_path=rel)
        return {"output": text}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}

@app.get("/api/backup-info")
def api_backup_info():
    try:
        return {"backup": get_backup_info()}
    except Exception as e:
        return {"backup": {"error": f"{type(e).__name__}: {e}"}}

@app.get("/api/backup-profiles")
def api_backup_profiles():
    try:
        info = get_backup_info()
        return {
            "path": info.get("profiles"),
            "exists": info.get("profiles_exists"),
            "default": info.get("profiles_default"),
            "names": info.get("profiles_names") or [],
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "path": None, "exists": False, "default": None, "names": []}

@app.get("/api/diag/dropbox")
def api_diag_dropbox():
    rc, txt = diag_dropbox()
    return {"rc": rc, "output": txt}

@app.get("/api/debug-config")
def api_debug_config():
    tools_root = Path(__file__).resolve().parents[2]
    cfg_dir = CONFIG_DIR
    files = [
        ("projects_config.json", cfg_dir / "projects_config.json"),
        ("recipes_config.json", cfg_dir / "recipes_config.json"),
        ("search_config.json", cfg_dir / "search_config.json"),
        ("paste_config.json", cfg_dir / "paste_config.json"),
        ("format_config.json", cfg_dir / "format_config.json"),
        ("clean_config.json", cfg_dir / "clean_config.json"),
        ("gh_raw_config.json", cfg_dir / "gh_raw_config.json"),
        ("global_config.json", cfg_dir / "global_config.json"),
        ("backup_config.json", cfg_dir / "backup_config.json"),
        ("backup_profiles.json", cfg_dir / "backup_profiles.json"),
        ("git_config.json", cfg_dir / "git_config.json"),
    ]
    return {
        "tools_root": str(tools_root),
        "config_dir": str(cfg_dir),
        "env_RTOOLS_CONFIG_DIR": os.environ.get("RTOOLS_CONFIG_DIR"),
        "files": [{"name": n, "path": str(p), "exists": p.exists()} for n, p in files],
    }

CONFIG_WHITELIST = [
    "global_config.json",
    "projects_config.json",
    "recipes_config.json",
    "search_config.json",
    "paste_config.json",
    "format_config.json",
    "clean_config.json",
    "gh_raw_config.json",
    "backup_config.json",
    "backup_profiles.json",
    "git_config.json",
]

def _safe_cfg_path(name: str) -> Path:
    if name not in CONFIG_WHITELIST:
        raise HTTPException(status_code=400, detail=f"Ugyldig config-navn: {name}")
    p = (CONFIG_DIR / name).resolve()
    if p.parent != CONFIG_DIR.resolve():
        raise HTTPException(status_code=400, detail="Forsøk på å nå utenfor CONFIG_DIR")
    return p

@app.get("/api/config-files")
def api_config_files():
    items = []
    for n in CONFIG_WHITELIST:
        p = _safe_cfg_path(n)
        items.append({"name": n, "path": str(p), "exists": p.exists()})
    return {"config_dir": str(CONFIG_DIR), "files": items}

@app.get("/api/config")
def api_config_get(name: str = Query(..., description="Filnavn i whitelist")):
    p = _safe_cfg_path(name)
    if not p.exists():
        return {"name": name, "path": str(p), "exists": False, "content": "", "json": None}
    txt = p.read_text(encoding="utf-8")
    try:
        parsed = json.loads(txt)
    except Exception as e:
        return {"name": name, "path": str(p), "exists": True, "content": txt, "json_error": str(e)}
    return {"name": name, "path": str(p), "exists": True, "content": json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"}

@app.post("/api/config")
def api_config_put(name: str = Query(..., description="Filnavn i whitelist"), body: dict[str, Any] = Body(...)):
    p = _safe_cfg_path(name)
    content = body.get("content", "")
    if not isinstance(content, str):
        raise HTTPException(status_code=400, detail="content må være streng")
    try:
        parsed = json.loads(content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Ugyldig JSON: {e}")
    p.write_text(json.dumps(parsed, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"ok": True, "name": name, "path": str(p)}

@app.get("/favicon.ico")
def favicon():
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc``\x00"
        b"\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(content=png_1x1, media_type="image/png")
# Trygge UI-innstillinger (globale)
@app.get("/api/settings")
def api_settings():
    cfg_dir = CONFIG_DIR
    global_path = cfg_dir / "global_config.json"
    g = {}
    if global_path.is_file():
        try:
            g = json.loads(global_path.read_text(encoding="utf-8")) or {}
        except Exception:
            g = {}
    backup_path = cfg_dir / "backup_config.json"
    b = {}
    if backup_path.is_file():
        try:
            bb = json.loads(backup_path.read_text(encoding="utf-8")) or {}
            b["script"] = (bb.get("backup", {}) or {}).get("script")
        except Exception:
            b = {}
    return {
        "config_dir": str(cfg_dir),
        "global": {
            "default_project": g.get("default_project"),
            "default_tool": g.get("default_tool"),
        },
        "backup": b,
    }

@app.post("/api/settings")
def api_settings_save(body: dict[str, Any]):
    cfg_dir = CONFIG_DIR
    # global_config.json
    global_path = cfg_dir / "global_config.json"
    try:
        g = json.loads(global_path.read_text(encoding="utf-8")) if global_path.is_file() else {}
    except Exception:
        g = {}
    g["default_project"] = body.get("default_project") or None
    g["default_tool"] = body.get("default_tool") or None
    global_path.write_text(json.dumps(g, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # backup_config.json (kun script)
    backup_path = cfg_dir / "backup_config.json"
    try:
        b_all = json.loads(backup_path.read_text(encoding="utf-8")) if backup_path.is_file() else {}
    except Exception:
        b_all = {}
    b_all.setdefault("backup", {})
    if (body.get("backup_script") or "") == "":
        b_all["backup"].pop("script", None)
    else:
        b_all["backup"]["script"] = body.get("backup_script")
    backup_path.write_text(json.dumps(b_all, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {"ok": True}
