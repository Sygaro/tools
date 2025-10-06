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

TOOLS_ROOT = Path(__file__).resolve().parents[2]
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
        base = TOOLS_ROOT
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
  :root{--bg:#0f1116;--surface:#181b24;--border:#262c3f;--text:#e6ebf5;--muted:#9ca9c9;--primary:#3b82f6;--primary2:#4f9ef8;--radius:12px;--pad:16px;--gap:14px}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;line-height:1.5}
  header{display:flex;gap:var(--gap);align-items:center;padding:var(--pad);background:rgba(24,27,36,.85);backdrop-filter:blur(10px);border-bottom:1px solid var(--border);position:sticky;top:0;z-index:10}
  header h1{flex:1;font-size:20px;margin:0;font-weight:600}
  main{padding:var(--pad);max-width:1100px;margin:0 auto}
  .row{display:grid;gap:var(--gap)}
  @media(min-width:1080px){.row{grid-template-columns:repeat(2,1fr)}}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:var(--pad);box-shadow:0 4px 12px rgba(0,0,0,.3);transition:transform .1s ease, box-shadow .2s ease}
  .card:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.35)}
  h2{font-size:18px;margin:6px 0 14px;font-weight:600}
  label{display:block;margin:8px 0 4px}
  input[type=text],input[type=number],textarea,select{width:100%;padding:10px;background:#0e1220;color:var(--text);border:1px solid var(--border);border-radius:var(--radius)}
  textarea{min-height:160px;font-family:ui-monospace,Menlo,Consolas,monospace}
  .btn{display:inline-block;padding:8px 12px;border-radius:999px;border:none;background:linear-gradient(135deg,var(--primary),var(--primary2));color:#fff;font-weight:600;font-size:14px;cursor:pointer;transition:all .2s ease;box-shadow:0 2px 4px rgba(0,0,0,.25)}
  .btn:hover{filter:brightness(1.05);transform:translateY(-1px)}
  .btn[disabled]{opacity:.6;cursor:not-allowed}
  .inline{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
  .muted{color:var(--muted);font-size:13px}
  .grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  @media(min-width:840px){.grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
  .lamp{display:inline-block;width:10px;height:10px;margin-left:8px;border-radius:50%;background:#4a4f63;border:1px solid #2a2f44;vertical-align:middle;box-shadow:0 0 0 0 rgba(0,0,0,.0);transition:background .2s ease, box-shadow .2s ease}
  .lamp.busy{background:#d1a300;box-shadow:0 0 0 6px rgba(209,163,0,.1);animation:pulse 1.2s infinite}
  .lamp.ok{background:#18a957;box-shadow:0 0 0 6px rgba(24,169,87,.12)}
  .lamp.err{background:#d14c4c;box-shadow:0 0 0 6px rgba(209,76,76,.12)}
  @keyframes pulse{0%{box-shadow:0 0 0 0 rgba(209,163,0,.22)}70%{box-shadow:0 0 0 8px rgba(209,163,0,.0)}100%{box-shadow:0 0 0 0 rgba(0,0,0,.0)}}
  .summary{font-size:12px;color:var(--muted);margin:6px 0 0}
  .sum-ok{color:#94f39d}.sum-err{color:#ffa0a0}
</style>
</head>
<body>
<header class="inline">
  <h1 style="flex:1">r_tools UI</h1>

  <!-- Global status -->
  <div class="inline" style="gap:6px;">
    <span class="muted">Init</span><span class="lamp" id="status_init"></span>
  </div>
  <div class="inline" style="gap:6px;">
    <span class="muted">Verktøy</span><span class="lamp" id="status_global"></span>
    <span id="status_label" class="muted">(ingen)</span>
  </div>

  <div>
    <label for="project">Prosjekt</label>
    <select id="project" title="Defineres i tools/configs/projects_config.json"></select>
  </div>
  <button class="btn" id="refresh">Oppdater</button>
</header>
<main>
  <section class="card" id="recipes_card">
    <h2>Oppskrifter</h2>
    <div id="recipes"></div>
    <p class="muted">Oppskrifter kommer fra <code>tools/configs/recipes_config.json</code>.</p>
  </section>

  <div class="row">
    <section class="card">
      <h2>Search <span class="lamp" id="status_search"></span></h2>
      <label>Termer (regex, separert med komma)</label>
      <input id="search_terms" type="text" placeholder="f.eks: import\\s+os, class"/>
      <div class="inline">
        <label><input type="checkbox" id="search_all"/> Krev alle termer (--all)</label>
        <label><input type="checkbox" id="search_case"/> Skill store/små (--case-sensitive)</label>
        <label>Max size <input id="search_max" type="number" value="2000000"/></label>
      </div>
      <div class="inline"><button class="btn" id="run_search">Kjør search</button></div>
      <textarea id="out_search" readonly></textarea>
      <div id="sum_search" class="summary"></div>
      <p class="muted">Tomt felt → bruker ev. <code>search_terms</code> fra config.</p>
    </section>

    <section class="card">
      <h2>Paste <span class="lamp" id="status_paste"></span></h2>
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
      <textarea id="out_paste" readonly></textarea>
      <div id="sum_paste" class="summary"></div>
    </section>

    <section class="card">
      <h2>Format <span class="lamp" id="status_format"></span></h2>
      <div class="inline"><label><input type="checkbox" id="format_dry" /> Dry-run</label></div>
      <div class="inline"><button class="btn" id="run_format">Kjør format</button></div>
      <textarea id="out_format" readonly></textarea>
      <div id="sum_format" class="summary"></div>
      <p class="muted">Bruker prettier/black/ruff + cleanup fra config.</p>
    </section>

    <section class="card">
      <h2>Clean <span class="lamp" id="status_clean"></span></h2>
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
        <div class="inline">
          <button class="btn" id="save_clean_targets">Lagre targets</button>
        </div>
      </div>
      <label>Begrens til mål (komma-separert)</label>
      <input id="clean_what" type="text" placeholder="pycache,ruff_cache"/>
      <label>Skip mål (komma-separert)</label>
      <input id="clean_skip" type="text" placeholder="node_modules"/>
      <div class="inline"><button class="btn" id="run_clean">Kjør clean</button></div>
      <textarea id="out_clean" readonly></textarea>
      <div id="sum_clean" class="summary"></div>
    </section>

    <section class="card">
      <h2>GH Raw <span class="lamp" id="status_gh"></span></h2>
      <label>Path prefix</label>
      <input id="gh_prefix" type="text" placeholder="app/routes"/>
      <div class="inline"><button class="btn" id="run_gh">List raw-URLer</button></div>
      <textarea id="out_gh" readonly></textarea>
      <div id="sum_gh-raw" class="summary"></div>
    </section>

    <section class="card">
      <h2>Backup <span class="lamp" id="status_backup"></span></h2>
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
      <div class="inline">
        <button class="btn" id="run_backup">Kjør backup</button>
        <button class="btn" id="run_backup_env">Env-sjekk</button>
      </div>
      <textarea id="out_backup" readonly></textarea>
      <div id="sum_backup" class="summary"></div>
      <p class="muted">Profiler leses fra <code>tools/configs/backup_profiles.json</code>. Script-sti i <code>tools/configs/backup_config.json</code> kan være relativ til <code>~/tools</code>.</p>
    </section>
  </div>
</main>

<script>
const PREF_KEY = (proj) => `rtools:prefs:${proj}`;

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

async function withStatus(key, outId, fn) {
  setStatus(key, 'busy');
  setGlobalStatus('busy', `Kjører: ${key}`);
  const out = document.getElementById(outId);
  if (out) out.value = '';
  try {
    const result = await fn();
    setStatus(key, 'ok');
    setGlobalStatus('ok', `Sist: ${key}`);
    return result;
  } catch (e) {
    setStatus(key, 'err');
    setGlobalStatus('err', `Feil: ${key}`);
    if (out) out.value = String(e?.message || e);
    throw e;
  }
}

/* Debug-beskjed med join('\n') */
async function checkDebugConfigBanner(){
  try{
    const r = await fetch('/api/debug-config');
    const d = await r.json();
    const miss = (d.files || []).filter(f => !f.exists);
    if (miss.length){
      const lines = [
        '[webui] Mangler config:',
        ' - ' + miss.map(m => m.name).join('\n - '),
        `CONFIG_DIR= ${d.config_dir}`,
        `env RTOOLS_CONFIG_DIR= ${d.env_RTOOLS_CONFIG_DIR}`
      ];
      console.warn(lines.join('\n'));
      alert(
        [
          `En eller flere config-filer mangler i ${d.config_dir}:`,
          ' - ' + miss.map(m => m.name).join('\n - ')
        ].join('\n')
      );
    }
  } catch(e) {
    console.error('debug-config feilet:', e);
  }
}

function currentProject(){ return document.getElementById('project').value; }

function guessOutputTarget(tool){
  return tool === 'search' ? 'out_search'
       : tool === 'paste'  ? 'out_paste'
       : tool === 'format' ? 'out_format'
       : tool === 'clean'  ? 'out_clean'
       : tool === 'backup' ? 'out_backup'
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
    alert(
      [
        'Kunne ikke laste prosjekter.',
        '',
        data.error,
        '',
        'Forventet fil:',
        data.config
      ].join('\n')
    );
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

  sel.value = firstValid || (projs[0]?.abs_path || '');

  if (projs.length && projs.every(p => !p.exists)) {
    alert(
      [
        'Ingen av prosjektene i projects_config.json finnes på disk.',
        '',
        'Sjekk stiene.'
      ].join('\n')
    );
  }

  await fetchCleanConfig();
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
      await withStatus(rec.tool, guessOutputTarget(rec.tool), async () => {
        return runTool(rec.tool, {args: rec.args || {}}, guessOutputTarget(rec.tool));
      });
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

/* Self-check av API/konfig ved init */
async function selfCheck(){
  try{
    const [projRes, dbgRes] = await Promise.all([
      fetch('/api/projects').then(r=>r.json()),
      fetch('/api/debug-config').then(r=>r.json())
    ]);
    const missing = (dbgRes.files||[]).filter(f=>!f.exists).map(f=>f.name);
    const projErr = !!projRes.error;
    if (!projErr && missing.length === 0){
      setLamp('status_init','ok');
      console.log('[webui] self-check OK');
    } else {
      setLamp('status_init','err');
      const msgs = [
        'Self-check feilet:',
        projErr ? ` - /api/projects: ${projRes.error}` : null,
        missing.length ? ` - Mangler config: ${missing.join(', ')}` : null
      ].filter(Boolean);
      console.warn(msgs.join('\n'));
    }
  }catch(e){
    setLamp('status_init','err');
    console.error('Self-check exception:', e);
  }
}

/* Pref-lagring */
['project','search_terms','search_all','search_case','search_max',
 'paste_list_only','paste_filename_search','paste_max','paste_out','paste_include','paste_exclude',
 'format_dry','clean_what','clean_skip','gh_prefix'
].forEach(id=>{
  document.addEventListener('change', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
  document.addEventListener('input', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
});

document.getElementById('project').addEventListener('change', async ()=>{
  loadPrefs();
  await fetchCleanConfig();
});

document.addEventListener('change', (e)=>{
  if (e.target && (e.target.id === 'clean_mode_dry' || e.target.id === 'clean_mode_apply')) {
    updateCleanWarning();
  }
});

document.getElementById('refresh').onclick = async ()=>{
  await fetchProjects();
  await fetchRecipes();
  await fetchBackupInfo();
  await fetchBackupProfiles();
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
    const ok = confirm(
      [
        'Dette vil SLETTE filer.',
        'Er du sikker på at du vil fortsette?'
      ].join('\n')
    );
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
    await checkDebugConfigBanner();
    await selfCheck();
    loadPrefs();
    updateCleanWarning();
    console.log("[webui] init OK");
  } catch (e) {
    setLamp('status_init','err');
    console.error("[webui] init failed:", e);
    alert(
      [
        "UI-init feilet.",
        "Sjekk nettleserkonsollen for detaljer."
      ].join('\n')
    );
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

@app.get("/favicon.ico")
def favicon():
    png_1x1 = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\x0bIDATx\x9cc``\x00"
        b"\x00\x00\x02\x00\x01\xe2!\xbc3\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    return Response(content=png_1x1, media_type="image/png")

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
