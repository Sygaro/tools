# /home/reidar/tools/r_tools/tools/webui.py
from __future__ import annotations
from .backup_integration import run_backup
from contextlib import redirect_stdout
from pathlib import Path
from typing import TypedDict, Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel
import io
import json
from .backup_integration import get_backup_info
from ..config import load_config
from .code_search import run_search
from .paste_chunks import run_paste
from .format_code import run_format
from .clean_temp import run_clean
from .gh_raw import run_gh_raw

# Viktig: pek til /tools/configs (ikke r_tools/configs)
ROOT_DIR = Path(__file__).resolve().parents[2]  # .../tools
CONFIG_DIR = ROOT_DIR / "configs"

class ProjectEntry(TypedDict):
    name: str
    path: str  # som i JSON (kan være relativ)
    abs_path: str  # oppløst absolutt path
    exists: bool  # finnes på disk?

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
        base = ROOT_DIR  # relativ path tolkes relativt til tools/
        abs_path = (
            Path(raw_path).expanduser()
            if Path(raw_path).is_absolute()
            else (base / raw_path)
        ).resolve()

        out.append(
            ProjectEntry(
                name=str(p["name"]),
                path=raw_path,
                abs_path=str(abs_path),
                exists=abs_path.exists(),
            )
        )

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

INDEX_HTML = """<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>r_tools UI</title>
<style>
  /* Google Font */
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');

  :root {
    --bg: #0f1116;
    --surface: #181b24;
    --border: #262c3f;
    --text: #e6ebf5;
    --muted: #9ca9c9;
    --primary: #3b82f6;
    --primary-hover: #2563eb;
    --radius: 12px;
    --pad: 16px;
    --gap: 14px;
  }

  body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family: 'Inter', system-ui, sans-serif;
    line-height: 1.5;
  }

  header {
    display: flex;
    gap: var(--gap);
    align-items: center;
    padding: var(--pad);
    background: rgba(24,27,36,0.85);
    backdrop-filter: blur(10px);
    border-bottom: 1px solid var(--border);
    position: sticky;
    top: 0;
    z-index: 10;
  }

  header h1 {
    flex: 1;
    font-size: 20px;
    margin: 0;
    font-weight: 600;
  }

  main {
    padding: var(--pad);
    max-width: 1100px;
    margin: 0 auto;
  }

  .row {
    display: grid;
    gap: var(--gap);
  }

  @media (min-width: 1080px) {
    .row { grid-template-columns: repeat(2, 1fr); }
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: var(--pad);
    box-shadow: 0 4px 12px rgba(0,0,0,.3);
    transition: transform 0.1s ease, box-shadow 0.2s ease;
  }

  .card:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(0,0,0,.35);
  }

  h2 {
    font-size: 18px;
    margin: 6px 0 14px;
    font-weight: 600;
  }

  label { display: block; margin: 8px 0 4px; }

  input[type=text], input[type=number], textarea, select {
    width: 100%;
    padding: 10px;
    background: #0e1220;
    color: var(--text);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-family: inherit;
    transition: border 0.2s, box-shadow 0.2s;
  }

  input:focus, textarea:focus, select:focus {
    border-color: var(--primary);
    box-shadow: 0 0 0 2px rgba(59,130,246,0.4);
    outline: none;
  }

  textarea {
    min-height: 160px;
    font-family: ui-monospace, Menlo, Consolas, monospace;
  }

  .btn {
  display: inline-block;
  padding: 8px 12px;
  border-radius: 999px; /* pill-form */
  border: none;
  background: linear-gradient(135deg, var(--primary), #4f9ef8);
  color: #fff;
  font-weight: 600;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 2px 4px rgba(0,0,0,0.25);
}

.btn:hover {
  background: linear-gradient(135deg, var(--primary-hover), #3d8ef5);
  box-shadow: 0 4px 10px rgba(0,0,0,0.3);
  transform: translateY(-1px);
}

.btn:active {
  transform: translateY(0);
  box-shadow: 0 2px 6px rgba(0,0,0,0.3) inset;
}

.btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

  .inline {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }

  .muted {
    color: var(--muted);
    font-size: 13px;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }

  @media(min-width: 840px) {
    .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  }

  .badge-ok { color: #9ff59f; }
  .badge-warn { color: #ffca3a; }
</style>

</head>
<body>
<header class="inline">
  <h1 style="flex:1">r_tools UI</h1>
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
      <h2>Search</h2>
      <label>Termer (regex, separert med komma)</label>
      <input id="search_terms" type="text" placeholder="f.eks: import\\s+os, class"/>
      <div class="inline">
        <label><input type="checkbox" id="search_all"/> Krev alle termer (--all)</label>
        <label><input type="checkbox" id="search_case"/> Skill store/små (--case-sensitive)</label>
        <label>Max size <input id="search_max" type="number" value="2000000"/></label>
      </div>
      <div class="inline"><button class="btn" id="run_search">Kjør search</button></div>
      <div id="bk_info" class="muted" style="margin-top:6px"></div>

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

  <div class="inline">
    <button class="btn" id="run_clean">Kjør clean</button>
  </div>

  <label>Resultat</label>
  <textarea id="out_clean" readonly></textarea>
</section>

    <section class="card">
      <h2>GH Raw</h2>
      <label>Path prefix</label>
      <input id="gh_prefix" type="text" placeholder="app/routes"/>
      <div class="inline"><button class="btn" id="run_gh">List raw-URLer</button></div>
      <label>Resultat</label><textarea id="out_gh" readonly></textarea>
    </section>

    <section class="card">
  <h2>Backup</h2>

  <label>Config (valgfri)</label>
  <input id="bk_config" type="text" placeholder="~/backup.json eller ~/.config/backup_app/profiles.json"/>

  <label>Profile (valgfri)</label>
<label>Profil (fra backup_profiles.json)</label>
<select id="bk_profile_select"></select>

  <div class="inline">
    <label>Project <input id="bk_project" type="text" placeholder="prosjektnavn"/></label>
    <label>Version <input id="bk_version" type="text" placeholder="1.10"/></label>
    <label>Tag <input id="bk_tag" type="text" placeholder="Frontend_OK"/></label>
  </div>

  <div class="inline">
    <label>Source <input id="bk_source" type="text" placeholder="countdown (→ ~ /countdown)"/></label>
    <label>Dest <input id="bk_dest" type="text" placeholder="backups (→ ~ /backups)"/></label>
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

  <div class="inline"><button class="btn" id="run_backup">Kjør backup</button></div>
  <label>Resultat</label><textarea id="out_backup" readonly></textarea>
  <p class="muted">
  <code>backup.py</code>-sti settes i <code>tools/config/backup_config.json</code>.
  Profiler hentes automatisk fra <code>tools/config/backup_profiles.json</code> (kan overstyres i feltet “Config”).
</p>

</section>

  </div>
</main>

<script>
const PREF_KEY = (proj) => `rtools:prefs:${proj}`;

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
    console.warn('Prosjektfeil:', data.error, 'Config:', data.config);
    alert(`Kunne ikke laste prosjekter.\\n\\n${data.error}\\n\\nForventet fil:\\n${data.config}`);
    return;
  }

  const projs = data.projects || [];
  let firstValid = '';
  projs.forEach(p => {
    const opt = document.createElement('option');
    const badge = p.exists ? "✓" : "⚠";
    opt.value = p.abs_path;                // bruk absolutt sti ved kjøring
    opt.textContent = `${badge} ${p.name} — ${p.path}`;
    opt.title = p.exists ? p.abs_path : `Sti finnes ikke: ${p.abs_path}`;
    sel.appendChild(opt);
    if (p.exists && !firstValid) firstValid = p.abs_path;
  });

  sel.value = firstValid || (projs[0]?.abs_path || '');

  if (projs.length && projs.every(p => !p.exists)) {
    alert("Ingen av prosjektene i projects_config.json finnes på disk.\\n\\nSjekk stiene.");
  }

  await fetchCleanConfig(); // last targets for valgt prosjekt
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
  if (!data.backup || data.backup.error) {
    el.textContent = 'Backup-info utilgjengelig.';
    return;
  }
  const b = data.backup;
  const scriptBadge = b.script_exists ? '✓' : '⚠';
  const profBadge = b.profiles_exists ? '✓' : '⚠';
  el.textContent = `backup.py: ${scriptBadge} ${b.script} · profiler: ${profBadge} ${b.profiles || '(ingen funnet)'} `;
}

// kall ved oppstart/refresh:
document.getElementById('refresh').onclick = async ()=>{ await fetchProjects(); await fetchRecipes(); await fetchBackupInfo(); loadPrefs(); };
fetchBackupInfo();

async function fetchBackupProfiles() {
  const r = await fetch('/api/backup-profiles');
  const data = await r.json();
  const sel = document.getElementById('bk_profile_select');
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

// Når profil-dropdown endres, sett tekstfeltet (om du har det) eller lagre valg
document.addEventListener('change', (e)=>{
  if (e.target && e.target.id === 'bk_profile_select') {
    const val = e.target.value || '';
    const tf = document.getElementById('bk_profile');
    if (tf) tf.value = val;
  }
});

// Kall på oppstart og når du trykker "Oppdater"
document.getElementById('refresh').onclick = async ()=>{
  await fetchProjects();
  await fetchRecipes();
  await fetchBackupInfo?.();
  await fetchBackupProfiles();
  loadPrefs();
};
// første last
fetchBackupProfiles();

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

['project','search_terms','search_all','search_case','search_max',
 'paste_list_only','paste_filename_search','paste_max','paste_out','paste_include','paste_exclude',
 'format_dry','clean_yes','clean_dry','clean_what','clean_skip','gh_prefix'
].forEach(id=>{
  document.addEventListener('change', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
  document.addEventListener('input', (e)=>{ if(e.target && e.target.id===id) savePrefs(); });
});

document.getElementById('project').addEventListener('change', async ()=>{ loadPrefs(); await fetchCleanConfig(); });
document.getElementById('refresh').onclick = async ()=>{ await fetchProjects(); await fetchRecipes(); loadPrefs(); };

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
  const targets = collectCleanTargets(); // ← hent valgene fra UI
  runTool('clean', { args:{
    yes: document.getElementById('clean_yes').checked,
    dry_run: document.getElementById('clean_dry').checked,
    what: what ? what.split(',').map(s=>s.trim()).filter(Boolean) : [],
    skip: skip ? skip.split(',').map(s=>s.trim()).filter(Boolean) : [],
    targets: targets
  } }, 'out_clean');
};

document.getElementById('run_gh').onclick = () => {
  runTool('gh-raw', { args:{ path_prefix: document.getElementById('gh_prefix').value.trim() } }, 'out_gh');
};

fetchProjects(); fetchRecipes(); loadPrefs();

// Legg til disse i <script>-delen:
function currentCleanMode(){
  const dry = document.getElementById('clean_mode_dry').checked;
  return dry ? 'dry' : 'apply';
}
function updateCleanWarning(){
  const warn = document.getElementById('clean_warning');
  warn.style.display = currentCleanMode() === 'apply' ? 'block' : 'none';
}
// Kall ved oppstart og når radios endres
document.addEventListener('change', (e)=>{
  if (e.target && (e.target.id === 'clean_mode_dry' || e.target.id === 'clean_mode_apply')) {
    updateCleanWarning();
  }
});

// Oppdater eksisterende run_clean-handler:
document.getElementById('run_clean').onclick = () => {
  const what = document.getElementById('clean_what').value.trim();
  const skip = document.getElementById('clean_skip').value.trim();
  const targets = collectCleanTargets();
  const mode = currentCleanMode();

  if (mode === 'apply') {
    const ok = confirm("Dette vil SLETTE filer. Er du sikker på at du vil fortsette?");
    if (!ok) return;
  }

  runTool('clean', { args:{
    mode,                       // <- ny
    what: what ? what.split(',').map(s=>s.trim()).filter(Boolean) : [],
    skip: skip ? skip.split(',').map(s=>s.trim()).filter(Boolean) : [],
    targets: targets
  } }, 'out_clean');
};

// Kall ved init (etter fetchProjects()); gjør også etter project-change:
updateCleanWarning();

document.getElementById('run_backup').onclick = () => {
  // hent profil fra dropdown om den finnes, ellers fra tekstfelt (valgfritt)
  const sel = document.getElementById('bk_profile_select');
  const profile = sel && sel.value ? sel.value.trim() : (document.getElementById('bk_profile')?.value.trim() || "");

  const payload = {
    config: document.getElementById('bk_config')?.value.trim(), // valgfri; tom → auto
    profile: profile || undefined,                               // tom → backend bruker default
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
  runTool('backup', { args: payload }, 'out_backup');
};

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
    """Returner effektiv clean-config for valgt prosjekt (targets vises i UI)."""
    project_path = Path(project).resolve() if project else None
    cfg = load_config("clean_config.json", project_path, None)
    return {"clean": cfg.get("clean", {})}

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
            out = _capture(
                run_search,
                cfg=cfg,
                terms=args.get("terms") or None,
                use_color=False,
                show_count=True,
                max_size=int(args.get("max_size", 2_000_000)),
                require_all=bool(args.get("all", False)),
            )
            return {"output": out}

        if tool == "paste":
            pov: Dict[str, Any] = {"paste": {}}
            for key in [
                "out_dir",
                "max_lines",
                "include",
                "exclude",
                "filename_search",
            ]:
                if key in args and args[key] not in (None, ""):
                    pov["paste"][key] = args[key]
            cfg = load_config(tool_cfg, project_path, pov)
            out = _capture(
                run_paste, cfg=cfg, list_only=bool(args.get("list_only", False))
            )
            return {"output": out}

        if tool == "format":
            cfg = load_config(tool_cfg, project_path, ov or None)
            out = _capture(
                run_format, cfg=cfg, dry_run=bool(args.get("dry_run", False))
            )
            return {"output": out}

        if tool == "clean":
            cov: Dict[str, Any] = {"clean": {}}
            if "targets" in args and isinstance(args["targets"], dict):
                cov["clean"]["targets"] = args["targets"]
            if "extra_globs" in args:
                cov["clean"]["extra_globs"] = args["extra_globs"]
            if "skip_globs" in args:
                cov["clean"]["skip_globs"] = args["skip_globs"]

            cfg = load_config(
                "clean_config.json", project_path, cov if cov["clean"] else None
            )

            mode = (args.get("mode") or "dry").lower()
            perform = mode == "apply"  # kun når eksplisitt valgt
            dry_run = not perform  # sikker default

            out = _capture(
                run_clean,
                cfg=cfg,
                only=args.get("what") or None,
                skip=args.get("skip") or [],
                dry_run=dry_run,
            )
            return {"output": out}

        if tool == "backup":
            # args kommer direkte fra UI – send videre som overrides
            rc, out = run_backup(args)
            # vis alltid alt i UI
            if out:
                print(out, end="")
            return {"output": out or f"(exit {rc})"}

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

# Favicon – unngå 404-støy
@app.get("/favicon.ico")
def favicon():
    png_1x1 = (
        b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\rIHDR\\x00\\x00\\x00\\x01\\x00\\x00\\x00\\x01"
        b"\\x08\\x06\\x00\\x00\\x00\\x1f\\x15\\xc4\\x89\\x00\\x00\\x00\\x0bIDATx\\x9cc``\\x00"
        b"\\x00\\x00\\x02\\x00\\x01\\xe2!\\xbc3\\x00\\x00\\x00\\x00IEND\\xaeB`\\x82"
    )
    return Response(content=png_1x1, media_type="image/png")

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
        return {
            "error": f"{type(e).__name__}: {e}",
            "path": None,
            "exists": False,
            "default": None,
            "names": [],
        }
