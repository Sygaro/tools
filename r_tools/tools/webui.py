# /home/reidar/tools/r_tools/tools/webui.py
from __future__ import annotations
import io, json, time, os
from contextlib import redirect_stdout
from pathlib import Path
from typing import TypedDict, Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Body
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from ..config import load_config
from .code_search import run_search
from .paste_chunks import run_paste
from .format_code import run_format
from .clean_temp import run_clean
from .gh_raw import run_gh_raw
from .backup_integration import run_backup, get_backup_info
from .diag_dropbox import diag_dropbox

# Kataloger
TOOLS_ROOT = Path(__file__).resolve().parents[2]  # .../tools
CONFIG_DIR = Path(os.environ.get("RTOOLS_CONFIG_DIR", str(TOOLS_ROOT / "configs"))).resolve()

print(f"[webui] TOOLS_ROOT = {TOOLS_ROOT}")
print(f"[webui] CONFIG_DIR = {CONFIG_DIR}  (env RTOOLS_CONFIG_DIR={os.environ.get('RTOOLS_CONFIG_DIR')!r})")
print(f"[webui] projects_config.json exists? {(CONFIG_DIR / 'projects_config.json').is_file()}")

class ProjectEntry(TypedDict):
    name: str
    path: str
    abs_path: str
    exists: bool

def _load_projects() -> List[ProjectEntry]:
    cfg_path = CONFIG_DIR / "projects_config.json"
    if not cfg_path.is_file():
        raise FileNotFoundError(f"Fant ikke {cfg_path}")
    data = json.loads(cfg_path.read_text(encoding="utf-8"))
    projects = data.get("projects")
    if not isinstance(projects, list):
        raise ValueError(f"{cfg_path}: 'projects' må være en liste")

    out: List[ProjectEntry] = []
    for i, p in enumerate(projects):
        if not isinstance(p, dict) or "name" not in p or "path" not in p:
            raise ValueError(f"{cfg_path}: item[{i}] mangler 'name' eller 'path'")
        raw_path = str(p["path"])
        base = TOOLS_ROOT  # relativ tolkes fra /tools
        abs_path = (Path(raw_path).expanduser()
                    if Path(raw_path).is_absolute()
                    else (base / raw_path)).resolve()
        out.append(ProjectEntry(
            name=str(p["name"]),
            path=raw_path,
            abs_path=str(abs_path),
            exists=abs_path.exists(),
        ))
    if not out:
        raise ValueError(f"{cfg_path}: 'projects' er tom")
    return out

def _load_recipes() -> List[Dict[str, Any]]:
    rc = CONFIG_DIR / "recipes_config.json"
    if not rc.is_file():
        return []
    data = json.loads(rc.read_text(encoding="utf-8"))
    return list(data.get("recipes", []))

def _capture(fn, *args, **kwargs) -> str:
    """Fang stdout fra run_* verktøy for UI-visning."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        fn(*args, **kwargs)
    return buf.getvalue()

app = FastAPI(title="r_tools UI", default_response_class=JSONResponse)

# RÅ streng for å unngå Python-escapes som ødelegger innebygd JS
INDEX_HTML = r"""<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>r_tools UI</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
  :root{
    --bg:#0f1116;--surface:#181b24;--border:#262c3f;--text:#e6ebf5;--muted:#9ca9c9;
    --primary:#3b82f6;--primary2:#4f9ef8;--radius:12px;
    --pad:12px;            /* tettere */
    --gap:10px;            /* tettere */
    --maxw:1400px;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;line-height:1.5}
  header{display:flex;gap:var(--gap);align-items:center;padding:var(--pad);background:rgba(24,27,36,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:20}
  header h1{flex:1;font-size:20px;margin:0;font-weight:600}
  main{padding:var(--pad);max-width:var(--maxw);margin:0 auto}
  .row{display:grid;gap:var(--gap);grid-template-columns:repeat(auto-fit,minmax(420px,1fr))}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:12px;box-shadow:0 4px 12px rgba(0,0,0,.3);transition:transform .1s ease, box-shadow .2s ease}
  .card:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.35)}
  label{display:block;margin:8px 0 4px}
  input[type=text],input[type=number],textarea,select{width:100%;padding:10px;background:#0e1220;color:var(--text);border:1px solid var(--border);border-radius:var(--radius)}
  textarea{min-height:160px;font-family:ui-monospace,Menlo,Consolas,monospace}
  .btn{display:inline-block;padding:8px 12px;border-radius:999px;border:none;background:linear-gradient(135deg,var(--primary),var(--primary2));color:#fff;font-weight:600;font-size:14px;cursor:pointer;transition:all .2s ease;box-shadow:0 2px 4px rgba(0,0,0,.25)}
  .btn:hover{filter:brightness(1.05);transform:translateY(-1px)}
  .btn[disabled]{opacity:.6;cursor:not-allowed}
  .inline{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .muted{color:var(--muted);font-size:13px}
  /* Statuslamper */
  .lamp{display:inline-block;width:10px;height:10px;margin-left:8px;border-radius:50%;background:#4a4f63;border:1px solid var(--border);vertical-align:middle;box-shadow:0 0 0 0 rgba(0,0,0,.0);transition:background .2s ease, box-shadow .2s ease}
  .lamp.busy{background:#d1a300;box-shadow:0 0 0 6px rgba(209,163,0,.1);animation:pulse 1.2s infinite}
  .lamp.ok{background:#18a957;box-shadow:0 0 0 6px rgba(24,169,87,.12)}
  .lamp.err{background:#d14c4c;box-shadow:0 0 0 6px rgba(209,76,76,.12)}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(209,163,0,.22)}70%{box-shadow:0 0 0 8px rgba(209,163,0,.0)}100%{box-shadow:0 0 0 0 rgba(0,0,0,.0)}}
  .summary{font-size:12px;color:var(--muted);margin:6px 0 0}

  /* Tabs */
  .tabs{display:flex;gap:8px;align-items:center;margin-left:12px}
  .tab{background:transparent;border:1px solid var(--border);color:var(--text);padding:8px 12px;border-radius:10px;cursor:pointer}
  .tab.active{border-color:var(--primary);box-shadow:0 0 0 2px rgba(59,130,246,0.25) inset}
  .tool{display:none}
  .tool.active{display:block}

  /* Felles action-bar */
  .tool-header{display:flex;align-items:center;gap:12px;margin-bottom:10px}
  .tool-title{display:flex;align-items:center;gap:8px;font-size:18px;font-weight:600}
  .tool-actions{margin-left:auto;display:flex;gap:8px;flex-wrap:wrap}
  .tool-body{margin-top:4px}

  /* Oppskrifter (dropdown) */
  .recipes{position:relative}
  .recipes-btn{padding:8px 12px;border-radius:10px;border:1px solid var(--border);background:transparent;color:var(--text);font-weight:600;cursor:pointer}
  .recipes-pop{position:absolute;right:0;top:120%;background:var(--surface);border:1px solid var(--border);border-radius:12px;box-shadow:0 10px 30px rgba(0,0,0,.35);min-width:260px;padding:8px;display:none;z-index:50}
  .recipes-pop.show{display:block}
  .recipes-pop .row{display:flex;align-items:center;gap:8px;padding:6px 4px}
  .recipes-pop .row button{margin-left:auto}
</style>
</head>
<body>
<header class="inline">
  <h1 style="flex:1">r_tools UI</h1>

  <!-- Globale lamper -->
  <div class="inline" style="gap:6px;">
    <span class="muted">Init</span><span class="lamp" id="status_init"></span>
  </div>
  <div class="inline" style="gap:6px;">
    <span class="muted">Verktøy</span><span class="lamp" id="status_global"></span>
    <span id="status_label" class="muted">(ingen)</span>
  </div>

  <!-- Tabs -->
  <div class="tabs" id="tabs">
    <button class="tab" data-tool="search">Search</button>
    <button class="tab" data-tool="paste">Paste</button>
    <button class="tab" data-tool="format">Format</button>
    <button class="tab" data-tool="clean">Clean</button>
    <button class="tab" data-tool="gh-raw">GH&nbsp;Raw</button>
    <button class="tab" data-tool="backup">Backup</button>
    <button class="tab" data-tool="settings">Settings</button>
  </div>

  <!-- Oppskrifter -->
  <div class="recipes" id="recipes_box">
    <button class="recipes-btn" id="recipes_toggle">Oppskrifter ▾</button>
    <div class="recipes-pop" id="recipes_pop"></div>
  </div>

  <div>
    <label for="project">Prosjekt</label>
    <select id="project" title="Defineres i tools/configs/projects_config.json"></select>
  </div>
  <button class="btn" id="refresh">Oppdater</button>
</header>

<main>
  <div class="row">

    <!-- SEARCH -->
    <section class="card tool tool-search" data-tool="search">
      <div class="tool-header">
        <div class="tool-title">Search <span class="lamp" id="status_search"></span></div>
        <div class="tool-actions">
          <button class="btn" id="run_search">Kjør search</button>
        </div>
      </div>
      <div class="tool-body">
        <label>Termer (regex, separert med komma)</label>
        <input id="search_terms" type="text" placeholder="f.eks: import\\s+os, class"/>
        <div class="inline">
          <label><input type="checkbox" id="search_all"/> Krev alle termer (--all)</label>
          <label><input type="checkbox" id="search_case"/> Skill store/små (--case-sensitive)</label>
          <label>Max size <input id="search_max" type="number" value="2000000"/></label>
        </div>
        <textarea id="out_search" readonly></textarea>
        <p class="muted">Tomt felt → bruker ev. <code>search_terms</code> fra config.</p>
      </div>
    </section>

    <!-- PASTE -->
    <section class="card tool tool-paste" data-tool="paste">
      <div class="tool-header">
        <div class="tool-title">Paste <span class="lamp" id="status_paste"></span></div>
        <div class="tool-actions">
          <button class="btn" id="run_paste">Kjør paste</button>
        </div>
      </div>
      <div class="tool-body">
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
        <textarea id="out_paste" readonly></textarea>
      </div>
    </section>

    <!-- FORMAT -->
    <section class="card tool tool-format" data-tool="format">
      <div class="tool-header">
        <div class="tool-title">Format <span class="lamp" id="status_format"></span></div>
        <div class="tool-actions">
          <label class="inline" style="gap:6px;"><input type="checkbox" id="format_dry"/> Dry-run</label>
          <button class="btn" id="run_format">Kjør format</button>
        </div>
      </div>
      <div class="tool-body">
        <textarea id="out_format" readonly></textarea>
        <p class="muted">Bruker prettier/black/ruff + cleanup fra config.</p>
      </div>
    </section>

    <!-- CLEAN -->
    <section class="card tool tool-clean" data-tool="clean">
      <div class="tool-header">
        <div class="tool-title">Clean <span class="lamp" id="status_clean"></span></div>
        <div class="tool-actions">
          <button class="btn" id="save_clean_targets">Lagre targets</button>
          <button class="btn" id="run_clean">Kjør clean</button>
        </div>
      </div>
      <div class="tool-body">
        <label>Modus</label>
        <div class="inline" role="radiogroup" aria-label="Modus">
          <label><input type="radio" name="clean_mode" id="clean_mode_dry" value="dry" checked/> Dry-run (standard)</label>
          <label><input type="radio" name="clean_mode" id="clean_mode_apply" value="apply"/> Utfør sletting</label>
        </div>
        <div id="clean_warning" class="muted" style="display:none; border:1px solid #803; background:#2a0d12; padding:8px; border-radius:8px;">
          ⚠ Dette vil <b>slette filer</b>. Dobbeltsjekk mål og bruk evt. dry-run først.
        </div>
        <div style="margin-top:8px">
          <label>Mål (fra <code>clean.targets</code>)</label>
          <div id="clean_targets" class="grid"></div>
        </div>
        <label>Begrens til mål (komma-separert)</label>
        <input id="clean_what" type="text" placeholder="pycache,ruff_cache"/>
        <label>Skip mål (komma-separert)</label>
        <input id="clean_skip" type="text" placeholder="node_modules"/>
        <textarea id="out_clean" readonly></textarea>
      </div>
    </section>

    <!-- GH RAW -->
    <section class="card tool tool-gh" data-tool="gh-raw">
      <div class="tool-header">
        <div class="tool-title">GH Raw <span class="lamp" id="status_gh"></span></div>
        <div class="tool-actions">
          <button class="btn" id="run_gh">List raw-URLer</button>
        </div>
      </div>
      <div class="tool-body">
        <label>Path prefix</label>
        <input id="gh_prefix" type="text" placeholder="app/routes"/>
        <textarea id="out_gh" readonly></textarea>
      </div>
    </section>

    <!-- BACKUP -->
    <section class="card tool tool-backup" data-tool="backup">
      <div class="tool-header">
        <div class="tool-title">Backup <span class="lamp" id="status_backup"></span></div>
        <div class="tool-actions">
          <button class="btn" id="run_backup">Kjør backup</button>
          <button class="btn" id="run_backup_env">Env-sjekk</button>
        </div>
      </div>
      <div class="tool-body">
        <div id="bk_info" class="muted"></div>
        <label>Config (valgfri)</label>
        <input id="bk_config" type="text" placeholder="~/backup.json eller ~/tools/configs/backup_profiles.json"/>
        <label>Profil (fra backup_profiles.json)</label>
        <select id="bk_profile_select"></select>
        <div class="inline">
          <label>Project <input id="bk_project" type="text" placeholder="prosjektnavn"/></label>
          <label>Version <input id="bk_version" type="text" placeholder="1.10"/></label>
          <label>Tag <input id="bk_tag" type="text" placeholder="Frontend_OK"/></label>
        </div>
        <div class="inline">
          <label>Source <input id="bk_source" type="text" placeholder="countdown (→ ~/countdown)"/></label>
          <label>Dest <input id="bk_dest" type="text" placeholder="Backups (→ ~/Backups)"/></label>
        </div>
        <div class="inline">
          <label>Format
            <select id="bk_format">
              <option value="">default (zip)</option>
              <option value="zip">zip</option>
              <option value="tar.gz">tar.gz</option>
              <option value="tgz">tgz</option>
            </select>
          </label>
          <label><input type="checkbox" id="bk_hidden"/> Inkluder skjulte</label>
          <label><input type="checkbox" id="bk_list"/> List filer (ingen skriving)</label>
          <label><input type="checkbox" id="bk_dry"/> Dry-run</label>
          <label><input type="checkbox" id="bk_nover"/> Uten versjon</label>
          <label><input type="checkbox" id="bk_noverif"/> Ikke verifiser</label>
        </div>
        <label>Exclude (ett mønster per linje eller kommaseparert)</label>
        <textarea id="bk_exclude" placeholder="*.env&#10;*.sqlite"></textarea>
        <div class="inline">
          <label>Keep <input id="bk_keep" type="number" min="0" value="0"/></label>
          <label>Dropbox path <input id="bk_dbx_path" type="text" placeholder="/Apps/backup_app/countdown"/></label>
          <label>Mode
            <select id="bk_dbx_mode">
              <option value="">default (add)</option>
              <option value="add">add</option>
              <option value="overwrite">overwrite</option>
            </select>
          </label>
        </div>
        <textarea id="out_backup" readonly></textarea>
        <p class="muted">Profiler leses fra <code>tools/configs/backup_profiles.json</code>. Script-sti i <code>tools/configs/backup_config.json</code> kan være relativ til <code>~/tools</code>.</p>
      </div>
    </section>

    <!-- SETTINGS -->
    <section class="card tool tool-settings" data-tool="settings">
      <div class="tool-header">
        <div class="tool-title">Settings <span class="lamp" id="status_settings"></span></div>
        <div class="tool-actions">
          <button class="btn" id="cfg_reload">Reload</button>
          <button class="btn" id="cfg_format">Format</button>
          <button class="btn" id="cfg_save">Lagre</button>
        </div>
      </div>
      <div class="tool-body">
        <div class="inline">
          <label for="set_default_project" style="min-width:180px;">Default project</label>
          <select id="set_default_project"></select>
        </div>
        <div class="inline" style="margin-top:8px;">
          <label for="set_default_tool" style="min-width:180px;">Default tool</label>
          <select id="set_default_tool">
            <option value="">(ingen)</option>
            <option value="search">search</option>
            <option value="paste">paste</option>
            <option value="format">format</option>
            <option value="clean">clean</option>
            <option value="gh-raw">gh-raw</option>
            <option value="backup">backup</option>
          </select>
        </div>
        <div class="inline" style="margin-top:8px;">
          <label for="set_backup_script" style="min-width:180px;">backup.py (sti)</label>
          <input id="set_backup_script" type="text" placeholder="/home/<bruker>/tools/backup_app/backup.py"/>
        </div>

        <hr style="border:none;border-top:1px solid var(--border); margin:14px 0;">

        <div class="inline" style="gap:8px">
          <label for="cfg_file" style="min-width:180px;">Config-fil</label>
          <select id="cfg_file" style="min-width:280px"></select>
          <span class="muted" id="cfg_path"></span>
        </div>
        <label for="cfg_editor">Innhold (JSON)</label>
        <textarea id="cfg_editor" style="min-height:360px"></textarea>

        <p class="muted" style="margin-top:6px">
          Endringer lagres direkte til fil i <code>configs/</code> og påvirker også CLI. —
          CONFIG_DIR: <code id="settings_cfgdir"></code> ·
          <a href="#" id="settings_diag">diagnose</a>
        </p>
        <textarea id="out_settings" readonly></textarea>
      </div>
    </section>

  </div>
</main>

<script>
const PREF_KEY = (proj) => `rtools:prefs:${proj}`;
const ACTIVE_TOOL_KEY = 'rtools:active_tool';
const TOOLS = ['search','paste','format','clean','gh-raw','backup','settings'];

const STATUS_IDS = {
  search: 'status_search',
  paste: 'status_paste',
  format: 'status_format',
  clean: 'status_clean',
  'gh-raw': 'status_gh',
  backup: 'status_backup'
};

function setLamp(id, state){
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('busy','ok','err');
  if (state === 'busy') el.classList.add('busy');
  if (state === 'ok')   el.classList.add('ok');
  if (state === 'err')  el.classList.add('err');
}
function setStatus(key, state) {
  const id = STATUS_IDS[key];
  if (!id) return;
  setLamp(id, state);
}
function setGlobalStatus(state, label){
  setLamp('status_global', state);
  const lab = document.getElementById('status_label');
  if (lab) lab.textContent = label || '(ingen)';
}

/* Tabs */
function setActiveTool(name){
  TOOLS.forEach(t=>{
    const sec = document.querySelector(`.tool[data-tool="${t}"]`);
    const tab = document.querySelector(`.tab[data-tool="${t}"]`);
    if (sec) sec.classList.toggle('active', t === name);
    if (tab) tab.classList.toggle('active', t === name);
  });
  localStorage.setItem(ACTIVE_TOOL_KEY, name);
}
document.getElementById('tabs').addEventListener('click', (e)=>{
  const btn = e.target.closest('.tab');
  if (!btn) return;
  const tool = btn.getAttribute('data-tool');
  setActiveTool(tool);
});

/* Status-wrapper */
async function withStatus(key, outId, fn) {
  if (key) setStatus(key, 'busy');
  setGlobalStatus('busy', key ? `Kjører: ${key}` : 'Kjører');
  const out = document.getElementById(outId);
  if (out) out.value = '';
  try {
    const result = await fn();
    if (key) setStatus(key, 'ok');
    setGlobalStatus('ok', key ? `Sist: ${key}` : 'OK');
    return result;
  } catch (e) {
    if (key) setStatus(key, 'err');
    setGlobalStatus('err', key ? `Feil: ${key}` : 'Feil');
    if (out) out.value = String(e?.message || e);
    throw e;
  }
}

/* Oppskrifter dropdown */
async function fetchRecipes() {
  const r = await fetch('/api/recipes');
  const data = await r.json();
  const pop = document.getElementById('recipes_pop');
  pop.innerHTML = '';
  (data.recipes || []).forEach((rec, idx) => {
    const row = document.createElement('div');
    row.className = 'row';
    const label = document.createElement('div');
    label.className = 'muted';
    label.textContent = rec.name || `Oppskrift ${idx+1}`;
    const btn = document.createElement('button');
    btn.className = 'btn';
    btn.textContent = 'Kjør';
    btn.onclick = async (e) => {
      e.stopPropagation();
      await withStatus(rec.tool, guessOutputTarget(rec.tool), async () => {
        return runTool(rec.tool, {args: rec.args || {}}, guessOutputTarget(rec.tool));
      });
    };
    row.appendChild(label);
    row.appendChild(btn);
    pop.appendChild(row);
  });
  if ((data.recipes || []).length === 0) {
    const p = document.createElement('div');
    p.className = 'muted';
    p.textContent = 'Ingen oppskrifter funnet.';
    pop.appendChild(p);
  }
}
document.getElementById('recipes_toggle').onclick = (e)=>{
  e.stopPropagation();
  document.getElementById('recipes_pop').classList.toggle('show');
};
document.addEventListener('click', ()=> document.getElementById('recipes_pop').classList.remove('show'));

/* Hjelpere */
function currentProject(){ return document.getElementById('project').value; }
function guessOutputTarget(tool){
  return tool === 'search' ? 'out_search'
       : tool === 'paste'  ? 'out_paste'
       : tool === 'format' ? 'out_format'
       : tool === 'clean'  ? 'out_clean'
       : tool === 'backup' ? 'out_backup'
       : tool === 'settings' ? 'out_settings'
       : 'out_gh';
}
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
    set('clean_what', p.clean_what);
    set('clean_skip', p.clean_skip);
    set('gh_prefix', p.gh_prefix);
  }catch{}
}

/* Serverkall */
async function runTool(tool, payload, outId) {
  payload = payload || {};
  const projectPath = currentProject();
  payload.project = projectPath;
  payload.tool = tool;
  const r = await fetch('/api/run', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await r.json();
  const target = document.getElementById(outId);
  if (target) target.value = (data.output || data.error || '').trim();
  return data;
}

async function fetchProjects() {
  const r = await fetch('/api/projects');
  const data = await r.json();
  const sel = document.getElementById('project');
  sel.innerHTML = '';

  if (data.error) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Ingen prosjekter (se konsollen)';
    sel.appendChild(opt);
    console.warn(['Prosjektfeil:', data.error, 'Config:', data.config].join('\n'));
    alert(['Kunne ikke laste prosjekter.','',data.error,'','Forventet fil:',data.config].join('\n'));
    return;
  }

  const projs = data.projects || [];
  let firstValid = '';
  projs.forEach(p => {
    const opt = document.createElement('option');
    const badge = p.exists ? "✓" : "⚠";
    opt.value = p.abs_path;
    opt.textContent = `${badge} ${p.name} — ${p.path}`;
    opt.title = p.exists ? p.abs_path : `Sti finnes ikke: ${p.abs_path}`;
    sel.appendChild(opt);
    if (p.exists && !firstValid) firstValid = p.abs_path;
  });

  const s = await fetch('/api/settings').then(r=>r.json()).catch(()=>({global:{}}));
  const defaultProj = s?.global?.default_project || '';
  if (defaultProj && projs.some(p => p.abs_path === defaultProj)) {
    sel.value = defaultProj;
  } else {
    sel.value = firstValid || (projs[0]?.abs_path || '');
  }

  if (projs.length && projs.every(p => !p.exists)) {
    alert(['Ingen av prosjektene i projects_config.json finnes på disk.','','Sjekk stiene.'].join('\n'));
  }
}

async function fetchCleanConfig() {
  const proj = currentProject();
  const r = await fetch('/api/clean-config?project='+encodeURIComponent(proj));
  const data = await r.json();
  const targets = (data.clean && data.clean.targets) ? data.clean.targets : {};
  const box = document.getElementById('clean_targets');
  box.innerHTML = '';
  const keys = Object.keys(targets);
  if (!keys.length) {
    box.innerHTML = '<span class="muted">Ingen targets definert i clean_config.json</span>';
    return;
  }
  keys.sort().forEach(k=>{
    const id = 'ct_'+k;
    const wrap = document.createElement('label');
    wrap.innerHTML = `<input type="checkbox" id="${id}" ${targets[k] ? 'checked' : ''}/> ${k}`;
    box.appendChild(wrap);
  });
}
async function fetchBackupInfo() {
  const r = await fetch('/api/backup-info');
  const data = await r.json();
  const el = document.getElementById('bk_info');
  if (!el) return;
  if (!data.backup || data.backup.error) {
    el.textContent = 'Backup-info utilgjengelig.';
    return;
  }
  const b = data.backup;
  const scriptBadge = b.script_exists ? '✓' : '⚠';
  const profBadge = b.profiles_exists ? '✓' : '⚠';
  el.textContent = `backup.py: ${scriptBadge} ${b.script} · profiler: ${profBadge} ${b.profiles || '(ingen funnet)'}`;
}
async function fetchBackupProfiles() {
  const r = await fetch('/api/backup-profiles');
  const data = await r.json();
  const sel = document.getElementById('bk_profile_select');
  if (!sel) return;
  sel.innerHTML = '';
  if (!data.names || !data.names.length) {
    const o = document.createElement('option');
    o.value = '';
    o.textContent = '(ingen profiler funnet)';
    sel.appendChild(o);
    return;
  }
  const def = data.default || '';
  const nil = document.createElement('option');
  nil.value = '';
  nil.textContent = '(ingen valgt)';
  sel.appendChild(nil);
  data.names.forEach(name => {
    const o = document.createElement('option');
    o.value = name;
    o.textContent = name + (name === def ? ' (default)' : '');
    sel.appendChild(o);
  });
  sel.value = '';
}

/* Clean-hjelpere */
function currentCleanMode(){
  const dry = document.getElementById('clean_mode_dry').checked;
  return dry ? 'dry' : 'apply';
}
function updateCleanWarning(){
  const warn = document.getElementById('clean_warning');
  if (warn) warn.style.display = currentCleanMode() === 'apply' ? 'block' : 'none';
}
function collectCleanTargets() {
  const box = document.getElementById('clean_targets');
  const inputs = box.querySelectorAll('input[type=checkbox]');
  const t = {};
  inputs.forEach(inp => {
    const k = inp.id.replace(/^ct_/, '');
    t[k] = !!inp.checked;
  });
  return t;
}

/* Settings (globals + JSON config-editor) */
async function loadSettings() {
  const data = await fetch('/api/settings').then(r=>r.json());
  const selProj = document.getElementById('set_default_project');
  selProj.innerHTML = '';
  // kopier prosjektlisten
  const projSel = document.getElementById('project');
  Array.from(projSel.options).forEach(opt => {
    const o = document.createElement('option');
    o.value = opt.value; o.textContent = opt.textContent;
    selProj.appendChild(o);
  });
  selProj.value = data.global?.default_project || '';
  document.getElementById('set_default_tool').value = data.global?.default_tool || '';
  document.getElementById('set_backup_script').value = (data.backup && data.backup.script) || '';
  document.getElementById('settings_cfgdir').textContent = data.config_dir || '';

  // last config-fil-liste for JSON-editor
  await cfgList();
}
async function cfgList(){
  const r = await fetch('/api/config-files'); const d = await r.json();
  const sel = document.getElementById('cfg_file'); const path = document.getElementById('cfg_path');
  sel.innerHTML = '';
  (d.files || []).forEach(f=>{
    const o = document.createElement('option');
    o.value = f.name; o.textContent = `${f.exists ? '✓' : '⚠'} ${f.name}`;
    o.title = f.path; sel.appendChild(o);
  });
  if ((d.files||[]).length){ sel.value = d.files[0].name; path.textContent = d.files[0].path; }
  await cfgLoad();
}
async function cfgLoad(){
  const name = document.getElementById('cfg_file').value;
  setLamp('status_settings','busy');
  const r = await fetch('/api/config?name='+encodeURIComponent(name));
  const d = await r.json();
  document.getElementById('cfg_path').textContent = d.path || '';
  const ta = document.getElementById('cfg_editor');
  ta.value = (d.content || d.error || '').trim();
  setLamp('status_settings', d.error ? 'err' : 'ok');
}
function cfgFormat(){
  const ta = document.getElementById('cfg_editor');
  try{
    const parsed = JSON.parse(ta.value);
    ta.value = JSON.stringify(parsed, null, 2);
  }catch(e){
    alert('Ugyldig JSON: '+e.message);
  }
}
async function cfgSave(){
  const name = document.getElementById('cfg_file').value;
  const content = document.getElementById('cfg_editor').value;
  setLamp('status_settings','busy');
  let parsed;
  try{ parsed = JSON.parse(content); }catch(e){ setLamp('status_settings','err'); return alert('Ugyldig JSON: '+e.message); }
  const r = await fetch('/api/config?name='+encodeURIComponent(name), {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({content: JSON.stringify(parsed)})
  });
  const d = await r.json();
  if (d.ok) setLamp('status_settings','ok'); else setLamp('status_settings','err');
}
document.getElementById('cfg_file').addEventListener('change', cfgLoad);
document.getElementById('cfg_reload').onclick = cfgLoad;
document.getElementById('cfg_format').onclick = cfgFormat;
document.getElementById('cfg_save').onclick = cfgSave;

document.getElementById('settings_diag').onclick = async (e)=>{
  e.preventDefault();
  const dbg = await fetch('/api/debug-config').then(r=>r.json());
  document.getElementById('out_settings').value = JSON.stringify(dbg, null, 2);
};

/* Pref-lagring */
['project','search_terms','search_all','search_case','search_max',
 'paste_list_only','paste_filename_search','paste_max','paste_out','paste_include','paste_exclude',
 'format_dry','clean_what','clean_skip','gh_prefix'
].forEach(id=>{
  document.addEventListener('change', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
  document.addEventListener('input', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
});

/* Endre prosjekt */
document.getElementById('project').addEventListener('change', async ()=>{
  loadPrefs();
  await fetchCleanConfig();
});

/* Modus-warning */
document.addEventListener('change', (e)=>{
  if (e.target && (e.target.id === 'clean_mode_dry' || e.target.id === 'clean_mode_apply')) {
    updateCleanWarning();
  }
});

/* Refresh-knapp */
document.getElementById('refresh').onclick = async ()=>{
  await fetchProjects();
  await fetchRecipes();
  await fetchBackupInfo();
  await fetchBackupProfiles();
  await fetchCleanConfig();
  await loadSettings();
  loadPrefs();
};

/* Knapper */
document.getElementById('run_search').onclick = () => withStatus('search','out_search', async () => {
  const terms = document.getElementById('search_terms').value.trim();
  return runTool('search',{
    args:{
      terms: terms ? terms.split(',').map(s=>s.trim()).filter(Boolean) : [],
      case_sensitive: document.getElementById('search_case').checked,
      all: document.getElementById('search_all').checked,
      max_size: parseInt(document.getElementById('search_max').value || '2000000',10)
    }
  }, 'out_search');
});
document.getElementById('search_terms').addEventListener('keydown', (e)=>{
  if (e.key === 'Enter') document.getElementById('run_search').click();
});

document.getElementById('save_clean_targets').onclick = async () => {
  const targets = collectCleanTargets();
  const proj = currentProject();
  await withStatus('clean','out_clean', async () => {
    const r = await fetch('/api/clean-targets?project='+encodeURIComponent(proj), {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({targets})
    });
    const data = await r.json();
    document.getElementById('out_clean').value =
      (data.message || data.error || JSON.stringify(data, null, 2));
    return data;
  });
};

document.getElementById('run_paste').onclick = () => withStatus('paste','out_paste', async () => {
  const inc = document.getElementById('paste_include').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
  const exc = document.getElementById('paste_exclude').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean);
  return runTool('paste',{
    args:{
      list_only: document.getElementById('paste_list_only').checked,
      out_dir: document.getElementById('paste_out').value.trim(),
      max_lines: parseInt(document.getElementById('paste_max').value || '4000',10),
      filename_search: document.getElementById('paste_filename_search').checked,
      include: inc,
      exclude: exc
    }
  }, 'out_paste');
});

document.getElementById('run_format').onclick = () => withStatus('format','out_format', async () => {
  return runTool('format', { args:{ dry_run: document.getElementById('format_dry').checked } }, 'out_format');
});

document.getElementById('run_clean').onclick = () => withStatus('clean','out_clean', async () => {
  const what = document.getElementById('clean_what').value.trim();
  const skip = document.getElementById('clean_skip').value.trim();
  const targets = collectCleanTargets();
  const mode = currentCleanMode();
  if (mode === 'apply') {
    const ok = confirm(['Dette vil SLETTE filer.','Er du sikker på at du vil fortsette?'].join('\n'));
    if (!ok) return;
  }
  return runTool('clean', { args:{
    mode,
    what: what ? what.split(',').map(s=>s.trim()).filter(Boolean) : [],
    skip: skip ? skip.split(',').map(s=>s.trim()).filter(Boolean) : [],
    targets
  } }, 'out_clean');
});

document.getElementById('run_gh').onclick = () => withStatus('gh-raw','out_gh', async () => {
  return runTool('gh-raw', { args:{ path_prefix: document.getElementById('gh_prefix').value.trim() } }, 'out_gh');
});

if (document.getElementById('run_backup')) {
  document.getElementById('run_backup').onclick = () => withStatus('backup','out_backup', async () => {
    const sel = document.getElementById('bk_profile_select');
    const profile = sel && sel.value ? sel.value.trim() : '';
    const payload = {
      config: document.getElementById('bk_config')?.value.trim(),
      profile: profile || undefined,
      project: document.getElementById('bk_project')?.value.trim(),
      source: document.getElementById('bk_source')?.value.trim(),
      dest: document.getElementById('bk_dest')?.value.trim(),
      version: document.getElementById('bk_version')?.value.trim(),
      tag: document.getElementById('bk_tag')?.value.trim(),
      format: document.getElementById('bk_format')?.value || undefined,
      include_hidden: document.getElementById('bk_hidden')?.checked,
      list: document.getElementById('bk_list')?.checked,
      dry_run: document.getElementById('bk_dry')?.checked,
      no_version: document.getElementById('bk_nover')?.checked,
      no_verify: document.getElementById('bk_noverif')?.checked,
      exclude: document.getElementById('bk_exclude')?.value,
      keep: parseInt(document.getElementById('bk_keep')?.value || '0', 10),
      dropbox_path: document.getElementById('bk_dbx_path')?.value.trim(),
      dropbox_mode: document.getElementById('bk_dbx_mode')?.value || undefined
    };
    return runTool('backup', { args: payload }, 'out_backup');
  });
}
if (document.getElementById('run_backup_env')) {
  document.getElementById('run_backup_env').onclick = async () => {
    await withStatus('backup','out_backup', async () => {
      const r = await fetch('/api/diag/dropbox');
      const data = await r.json();
      document.getElementById('out_backup').value = (data.output || data.error || '').trim();
      return data;
    });
  };
}

/* Init */
Object.keys(STATUS_IDS).forEach(k => setStatus(k, 'idle'));
setLamp('status_global', 'idle');
setLamp('status_init', 'busy');

(async function init(){
  try {
    await fetchProjects();
    await fetchRecipes();
    await fetchBackupInfo();
    await fetchBackupProfiles();
    await fetchCleanConfig();

    // Velg aktiv fane: localStorage > server default > 'search'
    const stored = localStorage.getItem(ACTIVE_TOOL_KEY);
    if (stored && TOOLS.includes(stored)) setActiveTool(stored);
    else {
      const s = await fetch('/api/settings').then(r=>r.json()).catch(()=>({global:{}}));
      setActiveTool(s?.global?.default_tool || 'search');
    }

    await loadSettings();
    loadPrefs();
    updateCleanWarning();
    setLamp('status_init','ok');
    console.log("[webui] init OK");
  } catch (e) {
    setLamp('status_init','err');
    console.error("[webui] init failed:", e);
    alert(["UI-init feilet.","Sjekk nettleserkonsollen for detaljer."].join('\n'));
  }
})();
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
def api_clean_config(project: Optional[str] = Query(None)):
    cfg = load_config("clean_config.json", Path(project).resolve() if project else None, None)
    return {"clean": cfg.get("clean", {})}

@app.get("/api/clean-targets")
def api_clean_targets_get(project: Optional[str] = Query(None)):
    cfg = load_config("clean_config.json", Path(project).resolve() if project else None, None)
    return {"targets": (cfg.get("clean", {}) or {}).get("targets", {})}

@app.post("/api/clean-targets")
def api_clean_targets_set(project: Optional[str] = Query(None), body: Dict[str, Any] = Body(...)):
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

@app.post("/api/run")
def api_run(body: RunPayload):
    tool = body.tool
    project_path = Path(body.project).resolve() if body.project else None
    args = body.args or {}
    t0 = time.time()

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
            out = _capture(run_search, cfg=cfg,
                           terms=args.get("terms") or None,
                           use_color=False, show_count=True,
                           max_size=int(args.get("max_size", 2_000_000)),
                           require_all=bool(args.get("all", False)))
            dt = int((time.time()-t0)*1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        if tool == "paste":
            pov: Dict[str, Any] = {"paste": {}}
            for key in ["out_dir", "max_lines", "include", "exclude", "filename_search"]:
                if key in args and args[key] not in (None, ""):
                    pov["paste"][key] = args[key]
            cfg = load_config(tool_cfg, project_path, pov)
            out = _capture(run_paste, cfg=cfg, list_only=bool(args.get("list_only", False)))
            dt = int((time.time()-t0)*1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        if tool == "format":
            cfg = load_config(tool_cfg, project_path, ov or None)
            out = _capture(run_format, cfg=cfg, dry_run=bool(args.get("dry_run", False)))
            dt = int((time.time()-t0)*1000)
            rc = 0
            if "returnerte kode" in out or "Error:" in out:
                rc = 3
            return {"output": out, "summary": {"rc": rc, "duration_ms": dt}}

        if tool == "clean":
            cov: Dict[str, Any] = {"clean": {}}
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
            out = _capture(run_clean, cfg=cfg,
                           only=args.get("what") or None,
                           skip=args.get("skip") or [],
                           dry_run=dry_run)
            dt = int((time.time()-t0)*1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        if tool == "backup":
            rc, text = run_backup(args or {})
            dt = int((time.time()-t0)*1000)
            return {"output": text, "rc": rc, "summary": {"rc": rc, "duration_ms": dt}}

        if tool == "gh-raw":
            gov = {"gh_raw": {}}
            if "path_prefix" in args:
                gov["gh_raw"]["path_prefix"] = args["path_prefix"]
            cfg = load_config(tool_cfg, project_path, gov)
            out = _capture(run_gh_raw, cfg=cfg, as_json=False)
            dt = int((time.time()-t0)*1000)
            return {"output": out, "summary": {"rc": 0, "duration_ms": dt}}

        raise HTTPException(status_code=400, detail=f"Ukjent tool: {tool}")
    except Exception as e:
        dt = int((time.time()-t0)*1000)
        return {"error": f"{type(e).__name__}: {e}", "summary": {"rc": 1, "duration_ms": dt}}

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
        return {"path": info.get("profiles"),
                "exists": info.get("profiles_exists"),
                "default": info.get("profiles_default"),
                "names": info.get("profiles_names") or []}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}",
                "path": None, "exists": False, "default": None, "names": []}

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
        ("recipes_config.json",  cfg_dir / "recipes_config.json"),
        ("search_config.json",   cfg_dir / "search_config.json"),
        ("paste_config.json",    cfg_dir / "paste_config.json"),
        ("format_config.json",   cfg_dir / "format_config.json"),
        ("clean_config.json",    cfg_dir / "clean_config.json"),
        ("gh_raw_config.json",   cfg_dir / "gh_raw_config.json"),
        ("global_config.json",   cfg_dir / "global_config.json"),
        ("backup_config.json",   cfg_dir / "backup_config.json"),
        ("backup_profiles.json", cfg_dir / "backup_profiles.json"),
    ]
    return {
        "tools_root": str(tools_root),
        "config_dir": str(cfg_dir),
        "env_RTOOLS_CONFIG_DIR": os.environ.get("RTOOLS_CONFIG_DIR"),
        "files": [{"name": n, "path": str(p), "exists": p.exists()} for n, p in files],
    }

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
            "default_tool": g.get("default_tool")
        },
        "backup": b
    }

@app.post("/api/settings")
def api_settings_save(body: Dict[str, Any]):
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

# ---------- Sikker config-IO for JSON-editor i Settings ----------
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
        # Returner rå-innhold + feil dersom filen er korrupt
        return {"name": name, "path": str(p), "exists": True, "content": txt, "json_error": str(e)}
    return {"name": name, "path": str(p), "exists": True, "content": json.dumps(parsed, indent=2, ensure_ascii=False) + "\n"}

@app.post("/api/config")
def api_config_put(
    name: str = Query(..., description="Filnavn i whitelist"),
    body: Dict[str, Any] = Body(...),
):
    # forventer {"content": "..."} med JSON-tekst
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

# Favicon – unngå 404-støy
@app.get("/favicon.ico")
def favicon():
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc``\x00"
        b"\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(content=png_1x1, media_type="image/png")
