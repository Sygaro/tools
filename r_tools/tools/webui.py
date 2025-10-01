# /home/reidar/tools/r_tools/tools/webui.py
from __future__ import annotations
import io
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from ..config import load_config
from .code_search import run_search
from .paste_chunks import run_paste
from .format_code import run_format
from .clean_temp import run_clean
from .gh_raw import run_gh_raw

TOOLS_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = TOOLS_ROOT / "configs"

def _load_projects() -> List[Dict[str, str]]:
    import json
    cfg_path = CONFIG_DIR / "projects_config.json"
    if not cfg_path.is_file():
        guesses = []
        for name in ["countdown", "tools"]:
            p = Path.home() / name
            if p.exists():
                guesses.append({"name": name, "path": str(p)})
        return guesses or [{"name": "current", "path": str(Path.cwd())}]
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    return list(data.get("projects", []))

def _load_recipes() -> List[Dict[str, Any]]:
    """Hvorfor: gi UI-klikkbare forhåndsvalg uten å hardkode i frontend."""
    import json
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

app = FastAPI(title="r_tools UI", default_response_class=JSONResponse)

INDEX_HTML = """<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>r_tools UI</title>
<style>
  :root{--pad:14px;--gap:12px;--radius:14px;font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial;}
  body{margin:0;background:#0b0c10;color:#e9ecef}
  header{padding:var(--pad);background:#11131a;border-bottom:1px solid #1b1f2a;position:sticky;top:0}
  main{padding:var(--pad);max-width:1100px;margin:0 auto}
  .row{display:grid;gap:var(--gap)}
  @media(min-width:1080px){.row{grid-template-columns:repeat(2,1fr)}}
  .card{background:#121622;border:1px solid #1b2030;border-radius:var(--radius);padding:var(--pad);box-shadow:0 6px 16px rgba(0,0,0,.25)}
  h1{font-size:20px;margin:0}
  h2{font-size:18px;margin:6px 0 12px}
  label{display:block;margin:8px 0 4px}
  input[type=text],input[type=number],textarea,select{width:100%;padding:10px;background:#0e1220;color:#e6eef9;border:1px solid #23304a;border-radius:10px}
  textarea{min-height:160px;font-family:ui-monospace,Menlo,Consolas,monospace}
  .btn{display:inline-block;padding:10px 14px;border-radius:10px;border:1px solid #2b3550;background:#1a2340;color:#dce6ff;cursor:pointer}
  .btn:hover{background:#223055}
  .inline{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .muted{color:#9fb0c9;font-size:12px}
  .pill{display:inline-block;padding:4px 8px;border-radius:9999px;background:#19223c;border:1px solid #263356;margin:2px}
</style>
</head>
<body>
<header class="inline">
  <h1 style="flex:1">r_tools UI</h1>
  <div>
    <label for="project">Prosjekt</label>
    <select id="project"></select>
  </div>
  <button class="btn" id="refresh">Oppdater</button>
</header>
<main>
  <section class="card" id="recipes_card">
    <h2>Oppskrifter</h2>
    <div id="recipes"></div>
    <p class="muted">Klikk for å kjøre med forhåndsvalgte parametere. Oppskrifter kommer fra <code>configs/recipes_config.json</code>.</p>
  </section>

  <div class="row">
    <section class="card">
      <h2>Search</h2>
      <label>Termer (regex, separert med komma)</label>
      <input id="search_terms" type="text" placeholder="f.eks: import\\s+os, class"/>
      <div class="inline">
        <label><input type="checkbox" id="search_all"/> Krev alle termer (--all)</label>
        <label><input type="checkbox" id="search_case"/> Skill store/små (--case-sensitive)</label>
        <label>Max size <input id="search_max" type="number" value="2000000"/></label>
      </div>
      <div class="inline"><button class="btn" id="run_search">Kjør search</button></div>
      <label>Resultat</label><textarea id="out_search" readonly></textarea>
      <p class="muted">Tomt felt → bruker ev. <code>search_terms</code> fra config.</p>
    </section>

    <section class="card">
      <h2>Paste</h2>
      <div class="inline">
        <label><input type="checkbox" id="paste_list_only"/> Kun liste</label>
        <label><input type="checkbox" id="paste_filename_search" checked/> Filnavn-søk globalt</label>
        <label>Max linjer<input id="paste_max" type="number" value="4000"/></label>
      </div>
      <label>Out dir (relativ til prosjekt)</label>
      <input id="paste_out" type="text" placeholder="paste_out"/>
      <label>Include (linje per mønster)</label>
      <textarea id="paste_include" placeholder="**/*.py&#10;README.md"></textarea>
      <label>Exclude (linje per mønster)</label>
      <textarea id="paste_exclude" placeholder="**/.git/**&#10;**/venv/**"></textarea>
      <div class="inline"><button class="btn" id="run_paste">Kjør paste</button></div>
      <label>Resultat</label><textarea id="out_paste" readonly></textarea>
    </section>

    <section class="card">
      <h2>Format</h2>
      <div class="inline"><label><input type="checkbox" id="format_dry" /> Dry-run</label></div>
      <div class="inline"><button class="btn" id="run_format">Kjør format</button></div>
      <label>Resultat</label><textarea id="out_format" readonly></textarea>
      <p class="muted">Bruker prettier/black/ruff + cleanup fra config.</p>
    </section>

    <section class="card">
      <h2>Clean</h2>
      <div class="inline">
        <label><input type="checkbox" id="clean_yes" /> Utfør sletting</label>
        <label><input type="checkbox" id="clean_dry" /> Dry-run</label>
      </div>
      <label>Begrens til mål (komma-separert)</label>
      <input id="clean_what" type="text" placeholder="pycache,ruff_cache"/>
      <label>Skip mål (komma-separert)</label>
      <input id="clean_skip" type="text" placeholder="node_modules"/>
      <div class="inline"><button class="btn" id="run_clean">Kjør clean</button></div>
      <label>Resultat</label><textarea id="out_clean" readonly></textarea>
    </section>

    <section class="card">
      <h2>GH Raw</h2>
      <label>Path prefix</label>
      <input id="gh_prefix" type="text" placeholder="app/routes"/>
      <div class="inline"><button class="btn" id="run_gh">List raw-URLer</button></div>
      <label>Resultat</label><textarea id="out_gh" readonly></textarea>
    </section>
  </div>
</main>

<script>
const PREF_KEY = (proj) => `rtools:prefs:${proj}`;

async function fetchProjects() {
  const r = await fetch('/api/projects');
  const data = await r.json();
  const sel = document.getElementById('project');
  const prev = sel.value;
  sel.innerHTML = '';
  data.projects.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.path; opt.textContent = p.name + ' — ' + p.path;
    sel.appendChild(opt);
  });
  sel.value = prev || (data.projects[0]?.path || '');
  loadPrefs();
}

async function fetchRecipes() {
  const r = await fetch('/api/recipes');
  const data = await r.json();
  const root = document.getElementById('recipes');
  root.innerHTML = '';
  (data.recipes || []).forEach((rec, idx) => {
    const row = document.createElement('div');
    row.className = 'inline';
    const btn = document.createElement('button');
    btn.className = 'btn';
    btn.textContent = rec.name || `Oppskrift ${idx+1}`;
    btn.onclick = async () => {
      await runTool(rec.tool, {args: rec.args || {}}, guessOutputTarget(rec.tool));
    };
    const info = document.createElement('span');
    info.className = 'muted';
    info.textContent = rec.desc || '';
    row.appendChild(btn);
    row.appendChild(info);
    root.appendChild(row);
  });
  if ((data.recipes || []).length === 0) {
    const p = document.createElement('p');
    p.className='muted';
    p.textContent='Ingen oppskrifter funnet.';
    root.appendChild(p);
  }
}

function guessOutputTarget(tool){
  return tool === 'search' ? 'out_search'
       : tool === 'paste'  ? 'out_paste'
       : tool === 'format' ? 'out_format'
       : tool === 'clean'  ? 'out_clean'
       : 'out_gh';
}

function currentProject(){ return document.getElementById('project').value; }

function savePrefs(){
  const proj = currentProject();
  if(!proj) return;
  const prefs = {
    search_terms: document.getElementById('search_terms').value,
    search_all: document.getElementById('search_all').checked,
    search_case: document.getElementById('search_case').checked,
    search_max: document.getElementById('search_max').value,
    paste_list_only: document.getElementById('paste_list_only').checked,
    paste_filename_search: document.getElementById('paste_filename_search').checked,
    paste_max: document.getElementById('paste_max').value,
    paste_out: document.getElementById('paste_out').value,
    paste_include: document.getElementById('paste_include').value,
    paste_exclude: document.getElementById('paste_exclude').value,
    format_dry: document.getElementById('format_dry').checked,
    clean_yes: document.getElementById('clean_yes').checked,
    clean_dry: document.getElementById('clean_dry').checked,
    clean_what: document.getElementById('clean_what').value,
    clean_skip: document.getElementById('clean_skip').value,
    gh_prefix: document.getElementById('gh_prefix').value
  };
  localStorage.setItem(PREF_KEY(proj), JSON.stringify(prefs));
}

function loadPrefs(){
  const proj = currentProject();
  if(!proj) return;
  const raw = localStorage.getItem(PREF_KEY(proj));
  if(!raw) return;
  try{
    const p = JSON.parse(raw);
    const set = (id,val,chk=false)=>{ const el=document.getElementById(id); if(!el) return; if(chk) el.checked=!!val; else el.value = val ?? el.value; };
    set('search_terms', p.search_terms);
    set('search_all', p.search_all, true);
    set('search_case', p.search_case, true);
    set('search_max', p.search_max);
    set('paste_list_only', p.paste_list_only, true);
    set('paste_filename_search', p.paste_filename_search, true);
    set('paste_max', p.paste_max);
    set('paste_out', p.paste_out);
    set('paste_include', p.paste_include);
    set('paste_exclude', p.paste_exclude);
    set('format_dry', p.format_dry, true);
    set('clean_yes', p.clean_yes, true);
    set('clean_dry', p.clean_dry, true);
    set('clean_what', p.clean_what);
    set('clean_skip', p.clean_skip);
    set('gh_prefix', p.gh_prefix);
  }catch{}
}

['project','search_terms','search_all','search_case','search_max',
 'paste_list_only','paste_filename_search','paste_max','paste_out','paste_include','paste_exclude',
 'format_dry','clean_yes','clean_dry','clean_what','clean_skip','gh_prefix'
].forEach(id=>{
  document.addEventListener('change', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
  document.addEventListener('input', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
});

document.getElementById('project').addEventListener('change', loadPrefs);
document.getElementById('refresh').onclick = ()=>{ fetchProjects(); fetchRecipes(); };

async function runTool(tool, payload, outId) {
  payload = payload || {};
  const projectPath = currentProject();
  payload.project = projectPath;
  payload.tool = tool;
  const r = await fetch('/api/run', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const data = await r.json();
  document.getElementById(outId).value = data.output || data.error || '';
}

document.getElementById('run_search').onclick = () => {
  const terms = document.getElementById('search_terms').value.trim();
  runTool('search',{
    args:{
      terms: terms ? terms.split(',').map(s=>s.trim()).filter(Boolean) : [],
      case_sensitive: document.getElementById('search_case').checked,
      all: document.getElementById('search_all').checked,
      max_size: parseInt(document.getElementById('search_max').value || '2000000',10)
    }
  }, 'out_search');
};

document.getElementById('run_paste').onclick = () => {
  const inc = document.getElementById('paste_include').value.split('\\n').map(s=>s.trim()).filter(Boolean);
  const exc = document.getElementById('paste_exclude').value.split('\\n').map(s=>s.trim()).filter(Boolean);
  runTool('paste',{
    args:{
      list_only: document.getElementById('paste_list_only').checked,
      out_dir: document.getElementById('paste_out').value.trim(),
      max_lines: parseInt(document.getElementById('paste_max').value || '4000',10),
      filename_search: document.getElementById('paste_filename_search').checked,
      include: inc,
      exclude: exc
    }
  }, 'out_paste');
};

document.getElementById('run_format').onclick = () => {
  runTool('format', { args:{ dry_run: document.getElementById('format_dry').checked } }, 'out_format');
};

document.getElementById('run_clean').onclick = () => {
  const what = document.getElementById('clean_what').value.trim();
  const skip = document.getElementById('clean_skip').value.trim();
  runTool('clean', { args:{
    yes: document.getElementById('clean_yes').checked,
    dry_run: document.getElementById('clean_dry').checked,
    what: what ? what.split(',').map(s=>s.trim()).filter(Boolean) : [],
    skip: skip ? skip.split(',').map(s=>s.trim()).filter(Boolean) : []
  } }, 'out_clean');
};

document.getElementById('run_gh').onclick = () => {
  runTool('gh-raw', { args:{ path_prefix: document.getElementById('gh_prefix').value.trim() } }, 'out_gh');
};

fetchProjects(); fetchRecipes(); loadPrefs();
</script>
</body></html>
"""

class RunPayload(BaseModel):
    tool: str
    project: Optional[str] = None
    args: Dict[str, Any] = {}

@app.get("/", response_class=HTMLResponse)
def index():
    return HTMLResponse(INDEX_HTML)

@app.get("/api/projects")
def api_projects():
    return {"projects": _load_projects()}

@app.get("/api/recipes")
def api_recipes():
    return {"recipes": _load_recipes()}

@app.post("/api/run")
def api_run(body: RunPayload):
    tool = body.tool
    project_path = Path(body.project).resolve() if body.project else None
    args = body.args or {}
    tool_cfg = {
        "search": "search_config.json",
        "paste": "paste_config.json",
        "gh-raw": "gh_raw_config.json",
        "format": "format_config.json",
        "clean": "clean_config.json",
    }.get(tool, None)

    ov: Dict[str, Any] = {}
    if project_path:
        ov["project_root"] = str(project_path)

    try:
        if tool == "search":
            cfg = load_config(tool_cfg, project_path, ov or None)
            out = _capture(run_search, cfg=cfg, terms=args.get("terms") or None,
                           use_color=False, show_count=True,
                           max_size=int(args.get("max_size", 2_000_000)),
                           require_all=bool(args.get("all", False)))
            return {"output": out}
        if tool == "paste":
            pov: Dict[str, Any] = {"paste": {}}
            for key in ["out_dir", "max_lines", "include", "exclude", "filename_search"]:
                if key in args and args[key] not in (None, ""):
                    pov["paste"][key] = args[key]
            cfg = load_config(tool_cfg, project_path, pov)
            out = _capture(run_paste, cfg=cfg, list_only=bool(args.get("list_only", False)))
            return {"output": out}
        if tool == "format":
            cfg = load_config(tool_cfg, project_path, ov or None)
            out = _capture(run_format, cfg=cfg, dry_run=bool(args.get("dry_run", False)))
            return {"output": out}
        if tool == "clean":
            cfg = load_config("clean_config.json", project_path, ov or None)
            out = _capture(run_clean, cfg=cfg, only=args.get("what") or None,
                           skip=args.get("skip") or [],
                           dry_run=bool(args.get("dry_run", True)) if not bool(args.get("yes", False)) else False)
            return {"output": out}
        if tool == "gh-raw":
            gov = {"gh_raw": {}}
            if "path_prefix" in args:
                gov["gh_raw"]["path_prefix"] = args["path_prefix"]
            cfg = load_config(tool_cfg, project_path, gov)
            out = _capture(run_gh_raw, cfg=cfg, as_json=False)
            return {"output": out}
        raise HTTPException(status_code=400, detail=f"Ukjent tool: {tool}")
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    
# --- Favicon (hindrer 404 i loggen) -----------------------------------------
@app.get("/favicon.ico")
def favicon():
    # Returner en minimal transparent PNG (1x1) – eller bytt til 204 for ingen ikon.
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc``\x00"
        b"\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(content=png_1x1, media_type="image/png")
