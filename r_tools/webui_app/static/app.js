// tools/r_tools/webui_app/static/app.js
const PREF_KEY = (proj) => `rtools:prefs:${proj}`
const ACTIVE_TOOL_KEY = 'rtools:active_tool'
const TOOLS = ['search', 'replace', 'paste', 'format', 'clean', 'gh-raw', 'backup', 'git', 'settings']
const STATUS_IDS = {
  search: 'status_search',
  replace: 'status_replace',
  paste: 'status_paste',
  format: 'status_format',
  clean: 'status_clean',
  'gh-raw': 'status_gh',
  backup: 'status_backup',
  git: 'status_git',
}

function setLamp(id, state) {
  const el = document.getElementById(id)
  if (!el) return
  el.classList.remove('busy', 'ok', 'err')
  if (state === 'busy') el.classList.add('busy')
  if (state === 'ok') el.classList.add('ok')
  if (state === 'err') el.classList.add('err')
}
function setStatus(key, state) {
  const id = STATUS_IDS[key]
  if (!id) return
  setLamp(id, state)
}
function setGlobalStatus(state, label) {
  setLamp('status_global', state)
  const lab = document.getElementById('status_label')
  if (lab) lab.textContent = label || '(ingen)'
}

/* Tabs */
function setActiveTool(name) {
  TOOLS.forEach((t) => {
    const sec = document.querySelector(`.tool[data-tool="${t}"]`)
    const tab = document.querySelector(`.tab[data-tool="${t}"]`)
    if (sec) sec.classList.toggle('active', t === name)
    if (tab) tab.classList.toggle('active', t === name)
  })
  localStorage.setItem(ACTIVE_TOOL_KEY, name)
}
document.getElementById('tabs').addEventListener('click', (e) => {
  const btn = e.target.closest('.tab')
  if (!btn) return
  const tool = btn.getAttribute('data-tool')
  setActiveTool(tool)
})

/* Status-wrapper */
async function withStatus(key, outId, fn) {
  if (key) setStatus(key, 'busy')
  setGlobalStatus('busy', key ? `Kjører: ${key}` : 'Kjører')
  const out = document.getElementById(outId)
  if (out) out.value = ''
  try {
    const result = await fn()
    if (key) setStatus(key, 'ok')
    setGlobalStatus('ok', key ? `Sist: ${key}` : 'OK')
    return result
  } catch (e) {
    if (key) setStatus(key, 'err')
    setGlobalStatus('err', key ? `Feil: ${key}` : 'Feil')
    if (out) out.value = String(e?.message || e)
    throw e
  }
}

/* Git: remotes/branches */
async function fetchGitRemotes() {
  const proj = currentProject()
  const r = await fetch('/api/git/remotes?project=' + encodeURIComponent(proj))
  const d = await r.json()
  const sel = document.getElementById('git_remote')
  sel.innerHTML = ''
  ;(d.remotes || []).forEach((name) => {
    const o = document.createElement('option')
    o.value = name
    o.textContent = name
    sel.appendChild(o)
  })
  if (!sel.value && sel.options.length) sel.value = sel.options[0].value
}
async function fetchGitBranches(selectValueIfPresent) {
  const proj = currentProject()
  const r = await fetch('/api/git/branches?project=' + encodeURIComponent(proj))
  const d = await r.json()
  const sel = document.getElementById('git_branch')
  if (!sel) return
  sel.innerHTML = ''
  ;(d.branches || []).forEach((name) => {
    const o = document.createElement('option')
    o.value = name
    o.textContent = name === d.current ? `${name} (current)` : name
    sel.appendChild(o)
  })
  const want = selectValueIfPresent || d.current
  if (want && [...sel.options].some((o) => o.value === want)) sel.value = want
  else if (sel.options.length) sel.value = sel.options[0].value
}

/* Oppskrifter dropdown */
async function fetchRecipes() {
  const r = await fetch('/api/recipes')
  const data = await r.json()
  const pop = document.getElementById('recipes_pop')
  pop.innerHTML = ''
  ;(data.recipes || []).forEach((rec, idx) => {
    const row = document.createElement('div')
    row.className = 'row'
    const label = document.createElement('div')
    label.className = 'muted'
    label.textContent = rec.name || `Oppskrift ${idx + 1}`
    const btn = document.createElement('button')
    btn.className = 'btn'
    btn.textContent = 'Kjør'
    btn.onclick = async (e) => {
      e.stopPropagation()
      await withStatus(rec.tool, guessOutputTarget(rec.tool), async () => {
        return runTool(rec.tool, { args: rec.args || {} }, guessOutputTarget(rec.tool))
      })
    }
    row.appendChild(label)
    row.appendChild(btn)
    pop.appendChild(row)
  })
  if ((data.recipes || []).length === 0) {
    const p = document.createElement('div')
    p.className = 'muted'
    p.textContent = 'Ingen oppskrifter funnet.'
    pop.appendChild(p)
  }
}

/* Git actions */
const elGitStatus = document.getElementById('git_status')
if (elGitStatus)
  elGitStatus.onclick = () => withStatus('git', 'out_git', async () => runTool('git', { args: { action: 'status' } }, 'out_git'))

const elGitSync = document.getElementById('git_sync')
if (elGitSync)
  elGitSync.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const branch = document.getElementById('git_branch')?.value
      const remote = document.getElementById('git_remote')?.value || 'origin'
      return runTool('git', { args: { action: 'sync', branch, remote } }, 'out_git')
    })

const elGitSwitch = document.getElementById('git_switch')
if (elGitSwitch)
  elGitSwitch.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const branch = document.getElementById('git_branch')?.value
      const res = await runTool('git', { args: { action: 'switch', branch } }, 'out_git')
      await fetchGitBranches()
      return res
    })

const elGitStashSwitch = document.getElementById('git_stash_switch')
if (elGitStashSwitch)
  elGitStashSwitch.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const branch = document.getElementById('git_branch')?.value
      const res = await runTool('git', { args: { action: 'stash_switch', branch } }, 'out_git')
      await fetchGitBranches()
      return res
    })

const elGitCreate = document.getElementById('git_create')
if (elGitCreate)
  elGitCreate.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const branch = document.getElementById('git_newbranch')?.value.trim()
      const base = document.getElementById('git_base')?.value.trim()
      const res = await runTool('git', { args: { action: 'create', branch, base } }, 'out_git')
      await fetchGitBranches(branch)
      return res
    })

const elGitMergeMain = document.getElementById('git_merge_main')
if (elGitMergeMain)
  elGitMergeMain.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const source = document.getElementById('git_branch')?.value
      const target = 'main'
      const confirmProtected = document.getElementById('git_confirm')?.checked || false
      const res = await runTool('git', { args: { action: 'merge', source, target, confirm: confirmProtected } }, 'out_git')
      await fetchGitBranches(target)
      return res
    })

const elGitPush = document.getElementById('git_push')
if (elGitPush)
  elGitPush.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const branch = document.getElementById('git_branch')?.value
      const remote = document.getElementById('git_remote')?.value || 'origin'
      const confirmProtected = document.getElementById('git_confirm')?.checked || false
      const precheck = document.getElementById('git_precheck')?.checked || false
      const precheck_tests = document.getElementById('git_precheck_tests')?.checked || false
      return runTool('git', { args: { action: 'push', branch, remote, confirm: confirmProtected, precheck, precheck_tests } }, 'out_git')
    })

const elGitAcp = document.getElementById('git_acp')
if (elGitAcp)
  elGitAcp.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const branch = document.getElementById('git_branch')?.value
      const remote = document.getElementById('git_remote')?.value || 'origin'
      const msg = document.getElementById('git_message')?.value || ''
      const confirmProtected = document.getElementById('git_confirm')?.checked || false
      const precheck = document.getElementById('git_precheck')?.checked || false
      const precheck_tests = document.getElementById('git_precheck_tests')?.checked || false
      return runTool(
        'git',
        { args: { action: 'acp', branch, remote, message: msg, confirm: confirmProtected, precheck, precheck_tests } },
        'out_git'
      )
    })

const elGitDiff = document.getElementById('git_diff')
if (elGitDiff)
  elGitDiff.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const staged = document.getElementById('git_staged')?.checked || false
      return runTool('git', { args: { action: 'diff', staged } }, 'out_git')
    })

const elGitLog = document.getElementById('git_log')
if (elGitLog)
  elGitLog.onclick = () =>
    withStatus('git', 'out_git', async () => {
      const n = parseInt(document.getElementById('git_log_n')?.value || '10', 10)
      return runTool('git', { args: { action: 'log', n } }, 'out_git')
    })

const elGitResolve = document.getElementById('git_resolve')
if (elGitResolve)
  elGitResolve.onclick = () => withStatus('git', 'out_git', async () => runTool('git', { args: { action: 'resolve' } }, 'out_git'))

/* Oppskrifter UI */
document.getElementById('recipes_toggle').onclick = (e) => {
  e.stopPropagation()
  document.getElementById('recipes_pop').classList.toggle('show')
}
document.addEventListener('click', () => document.getElementById('recipes_pop').classList.remove('show'))

/* Hjelpere */
function currentProject() {
  return document.getElementById('project').value
}
function guessOutputTarget(tool) {
  return tool === 'search'
    ? 'out_search'
    : tool === 'replace'
      ? 'out_replace'
      : tool === 'paste'
        ? 'out_paste'
        : tool === 'format'
          ? 'out_format'
          : tool === 'clean'
            ? 'out_clean'
            : tool === 'backup'
              ? 'out_backup'
              : tool === 'git'
                ? 'out_git'
                : tool === 'settings'
                  ? 'out_settings'
                  : 'out_gh'
}

/* Prefs save/load */
function savePrefs() {
  const proj = currentProject()
  if (!proj) return
  const prefs = {
    search_terms: document.getElementById('search_terms').value,
    search_all: document.getElementById('search_all').checked,
    search_case: document.getElementById('search_case').checked,
    search_max: document.getElementById('search_max').value,
    search_files_only: document.getElementById('search_files_only').checked,
    search_path_mode: document.getElementById('search_path_mode').value,
    search_limit_dirs: document.getElementById('search_limit_dirs').value,
    search_limit_exts: document.getElementById('search_limit_exts').value,
    search_include: document.getElementById('search_include')?.value,
    search_exclude: document.getElementById('search_exclude')?.value,
    search_filename_search: document.getElementById('search_filename_search')?.checked,
    rep_filename_search: document.getElementById('rep_filename_search')?.checked,
    paste_list_only: document.getElementById('paste_list_only').checked,
    paste_filename_search: document.getElementById('paste_filename_search').checked,
    paste_max: document.getElementById('paste_max').value,
    paste_out: document.getElementById('paste_out').value,
    paste_include: document.getElementById('paste_include').value,
    paste_exclude: document.getElementById('paste_exclude').value,
    format_dry: document.getElementById('format_dry').checked,
    fmt_prettier_enable: document.getElementById('fmt_prettier_enable')?.checked,
    fmt_prettier_globs: document.getElementById('fmt_prettier_globs')?.value,
    fmt_prettier_printWidth: document.getElementById('fmt_prettier_printWidth')?.value,
    fmt_prettier_tabWidth: document.getElementById('fmt_prettier_tabWidth')?.value,
    fmt_prettier_singleQuote: document.getElementById('fmt_prettier_singleQuote')?.checked,
    fmt_prettier_semi: document.getElementById('fmt_prettier_semi')?.checked,
    fmt_prettier_trailingComma: document.getElementById('fmt_prettier_trailingComma')?.value,
    fmt_black_enable: document.getElementById('fmt_black_enable')?.checked,
    fmt_black_paths: document.getElementById('fmt_black_paths')?.value,
    fmt_black_line_length: document.getElementById('fmt_black_line_length')?.value,
    fmt_black_target: document.getElementById('fmt_black_target')?.value,
    fmt_ruff_enable: document.getElementById('fmt_ruff_enable')?.checked,
    fmt_ruff_fix: document.getElementById('fmt_ruff_fix')?.checked,
    fmt_ruff_unsafe: document.getElementById('fmt_ruff_unsafe')?.checked,
    fmt_ruff_preview: document.getElementById('fmt_ruff_preview')?.checked,
    fmt_ruff_select: document.getElementById('fmt_ruff_select')?.value,
    fmt_ruff_ignore: document.getElementById('fmt_ruff_ignore')?.value,
    fmt_cleanup_enable: document.getElementById('fmt_cleanup_enable')?.checked,
    fmt_cleanup_compact: document.getElementById('fmt_cleanup_compact')?.checked,
    fmt_cleanup_maxblank: document.getElementById('fmt_cleanup_maxblank')?.value,
    fmt_cleanup_exts: document.getElementById('fmt_cleanup_exts')?.value,
    fmt_cleanup_excl_exts: document.getElementById('fmt_cleanup_excl_exts')?.value,
    clean_what: document.getElementById('clean_what').value,
    clean_skip: document.getElementById('clean_skip').value,
    gh_prefix: document.getElementById('gh_prefix').value,
    gh_wrap_read: document.getElementById('gh_wrap_read')?.checked,
    rep_find: document.getElementById('rep_find')?.value,
    rep_repl: document.getElementById('rep_repl')?.value,
    rep_regex: document.getElementById('rep_regex')?.checked,
    rep_case: document.getElementById('rep_case')?.checked,
    rep_backup: document.getElementById('rep_backup')?.checked,
    rep_dry: document.getElementById('rep_dry')?.checked,
    rep_showdiff: document.getElementById('rep_showdiff')?.checked,
    rep_max: document.getElementById('rep_max')?.value,
    rep_include: document.getElementById('rep_include')?.value,
    rep_exclude: document.getElementById('rep_exclude')?.value,
  }
  localStorage.setItem(PREF_KEY(proj), JSON.stringify(prefs))
}
function loadPrefs() {
  const proj = currentProject()
  if (!proj) return
  const raw = localStorage.getItem(PREF_KEY(proj))
  if (!raw) return
  try {
    const p = JSON.parse(raw)
    const set = (id, val, chk = false) => {
      const el = document.getElementById(id)
      if (!el) return
      if (chk) el.checked = !!val
      else el.value = val ?? el.value
    }
    set('search_terms', p.search_terms)
    set('search_all', p.search_all, true)
    set('search_case', p.search_case, true)
    set('search_max', p.search_max)
    set('search_files_only', p.search_files_only, true)
    set('search_path_mode', p.search_path_mode)
    set('search_limit_dirs', p.search_limit_dirs)
    set('search_limit_exts', p.search_limit_exts)
    set('search_include', p.search_include)
    set('search_exclude', p.search_exclude)
    set('search_filename_search', p.search_filename_search, true)
    set('rep_filename_search', p.rep_filename_search, true)
    set('paste_list_only', p.paste_list_only, true)
    set('paste_filename_search', p.paste_filename_search, true)
    set('paste_max', p.paste_max)
    set('paste_out', p.paste_out)
    set('paste_include', p.paste_include)
    set('paste_exclude', p.paste_exclude)
    set('format_dry', p.format_dry, true)
    set('fmt_prettier_enable', p.fmt_prettier_enable, true)
    set('fmt_prettier_globs', p.fmt_prettier_globs)
    set('fmt_prettier_printWidth', p.fmt_prettier_printWidth)
    set('fmt_prettier_tabWidth', p.fmt_prettier_tabWidth)
    set('fmt_prettier_singleQuote', p.fmt_prettier_singleQuote, true)
    set('fmt_prettier_semi', p.fmt_prettier_semi, true)
    set('fmt_prettier_trailingComma', p.fmt_prettier_trailingComma)
    set('fmt_black_enable', p.fmt_black_enable, true)
    set('fmt_black_paths', p.fmt_black_paths)
    set('fmt_black_line_length', p.fmt_black_line_length)
    set('fmt_black_target', p.fmt_black_target)
    set('fmt_ruff_enable', p.fmt_ruff_enable, true)
    set('fmt_ruff_fix', p.fmt_ruff_fix, true)
    set('fmt_ruff_unsafe', p.fmt_ruff_unsafe, true)
    set('fmt_ruff_preview', p.fmt_ruff_preview, true)
    set('fmt_ruff_select', p.fmt_ruff_select)
    set('fmt_ruff_ignore', p.fmt_ruff_ignore)
    set('fmt_cleanup_enable', p.fmt_cleanup_enable, true)
    set('fmt_cleanup_compact', p.fmt_cleanup_compact, true)
    set('fmt_cleanup_maxblank', p.fmt_cleanup_maxblank)
    set('fmt_cleanup_exts', p.fmt_cleanup_exts)
    set('fmt_cleanup_excl_exts', p.fmt_cleanup_excl_exts)
    set('clean_what', p.clean_what)
    set('clean_skip', p.clean_skip)
    set('gh_prefix', p.gh_prefix)
    set('gh_wrap_read', p.gh_wrap_read, true)
    set('rep_find', p.rep_find)
    set('rep_repl', p.rep_repl)
    set('rep_regex', p.rep_regex, true)
    set('rep_case', p.rep_case, true)
    set('rep_backup', p.rep_backup, true)
    set('rep_dry', p.rep_dry, true)
    set('rep_showdiff', p.rep_showdiff, true)
    set('rep_max', p.rep_max)
    set('rep_include', p.rep_include)
    set('rep_exclude', p.rep_exclude)
  } catch {}
}

/* Serverkall */
async function runTool(tool, payload, outId) {
  payload = payload || {}
  const projectPath = currentProject()
  payload.project = projectPath
  payload.tool = tool
  const r = await fetch('/api/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await r.json()
  const target = document.getElementById(outId)
  if (target) target.value = (data.output || data.error || '').trim()
  return data
}

/* Prosjekter og config */
async function fetchProjects() {
  const r = await fetch('/api/projects')
  const data = await r.json()
  const sel = document.getElementById('project')
  sel.innerHTML = ''
  if (data.error) {
    const opt = document.createElement('option')
    opt.value = ''
    opt.textContent = 'Ingen prosjekter (se konsollen)'
    sel.appendChild(opt)
    console.warn(['Prosjektfeil:', data.error, 'Config:', data.config].join('\n'))
    alert(['Kunne ikke laste prosjekter.', '', data.error, '', 'Forventet fil:', data.config].join('\n'))
    return
  }
  const projs = data.projects || []
  let firstValid = ''
  projs.forEach((p) => {
    const opt = document.createElement('option')
    const badge = p.exists ? '✓' : '⚠'
    opt.value = p.abs_path
    opt.textContent = `${badge} ${p.name} — ${p.path}`
    opt.title = p.exists ? p.abs_path : `Sti finnes ikke: ${p.abs_path}`
    sel.appendChild(opt)
    if (p.exists && !firstValid) firstValid = p.abs_path
  })
  const s = await fetch('/api/settings')
    .then((r) => r.json())
    .catch(() => ({ global: {} }))
  const defaultProj = s?.global?.default_project || ''
  if (defaultProj && projs.some((p) => p.abs_path === defaultProj)) sel.value = defaultProj
  else sel.value = firstValid || projs[0]?.abs_path || ''
  if (projs.length && projs.every((p) => !p.exists)) {
    alert(['Ingen av prosjektene i projects_config.json finnes på disk.', '', 'Sjekk stiene.'].join('\n'))
  }
}
async function fetchCleanConfig() {
  const proj = currentProject()
  const r = await fetch('/api/clean-config?project=' + encodeURIComponent(proj))
  const data = await r.json()
  const targets = data.clean && data.clean.targets ? data.clean.targets : {}
  const box = document.getElementById('clean_targets')
  box.innerHTML = ''
  const keys = Object.keys(targets)
  if (!keys.length) {
    box.innerHTML = '<span class="muted">Ingen targets definert i clean_config.json</span>'
    return
  }
  keys.sort().forEach((k) => {
    const id = 'ct_' + k
    const wrap = document.createElement('label')
    wrap.innerHTML = `<input type="checkbox" id="${id}" ${targets[k] ? 'checked' : ''}/> ${k}`
    box.appendChild(wrap)
  })
}
async function fetchBackupInfo() {
  const r = await fetch('/api/backup-info')
  const data = await r.json()
  const el = document.getElementById('bk_info')
  if (!el) return
  if (!data.backup || data.backup.error) {
    el.textContent = 'Backup-info utilgjengelig.'
    return
  }
  const b = data.backup
  const scriptBadge = b.script_exists ? '✓' : '⚠'
  const profBadge = b.profiles_exists ? '✓' : '⚠'
  el.textContent = `backup.py: ${scriptBadge} ${b.script} · profiler: ${profBadge} ${b.profiles || '(ingen funnet)'}`
}
async function fetchBackupProfiles() {
  const r = await fetch('/api/backup-profiles')
  const data = await r.json()
  const sel = document.getElementById('bk_profile_select')
  if (!sel) return
  sel.innerHTML = ''
  if (!data.names || !data.names.length) {
    const o = document.createElement('option')
    o.value = ''
    o.textContent = '(ingen profiler funnet)'
    sel.appendChild(o)
    return
  }
  const def = data.default || ''
  const nil = document.createElement('option')
  nil.value = ''
  nil.textContent = '(ingen valgt)'
  sel.appendChild(nil)
  data.names.forEach((name) => {
    const o = document.createElement('option')
    o.value = name
    o.textContent = name + (name === def ? ' (default)' : '')
    sel.appendChild(o)
  })
  sel.value = ''
}

/* Clean-hjelpere */
function currentCleanMode() {
  const dry = document.getElementById('clean_mode_dry').checked
  return dry ? 'dry' : 'apply'
}
function updateCleanWarning() {
  const warn = document.getElementById('clean_warning')
  if (warn) warn.style.display = currentCleanMode() === 'apply' ? 'block' : 'none'
}
function collectCleanTargets() {
  const box = document.getElementById('clean_targets')
  const inputs = box.querySelectorAll('input[type=checkbox]')
  const t = {}
  inputs.forEach((inp) => {
    const k = inp.id.replace(/^ct_/, '')
    t[k] = !!inp.checked
  })
  return t
}

/* Settings (globals + JSON editor) */
async function loadSettings() {
  const data = await fetch('/api/settings').then((r) => r.json())
  const selProj = document.getElementById('set_default_project')
  selProj.innerHTML = ''
  const projSel = document.getElementById('project')
  Array.from(projSel.options).forEach((opt) => {
    const o = document.createElement('option')
    o.value = opt.value
    o.textContent = opt.textContent
    selProj.appendChild(o)
  })
  selProj.value = data.global?.default_project || ''
  document.getElementById('set_default_tool').value = data.global?.default_tool || ''
  document.getElementById('set_backup_script').value = (data.backup && data.backup.script) || ''
  document.getElementById('settings_cfgdir').textContent = data.config_dir || ''
  await cfgList()
}
async function cfgList() {
  const r = await fetch('/api/config-files')
  const d = await r.json()
  const sel = document.getElementById('cfg_file')
  const path = document.getElementById('cfg_path')
  sel.innerHTML = ''
  ;(d.files || []).forEach((f) => {
    const o = document.createElement('option')
    o.value = f.name
    o.textContent = `${f.exists ? '✓' : '⚠'} ${f.name}`
    o.title = f.path
    sel.appendChild(o)
  })
  if ((d.files || []).length) {
    sel.value = d.files[0].name
    path.textContent = d.files[0].path
  }
  await cfgLoad()
}
async function cfgLoad() {
  const name = document.getElementById('cfg_file').value
  setLamp('status_settings', 'busy')
  const r = await fetch('/api/config?name=' + encodeURIComponent(name))
  const d = await r.json()
  document.getElementById('cfg_path').textContent = d.path || ''
  const ta = document.getElementById('cfg_editor')
  ta.value = (d.content || d.error || '').trim()
  setLamp('status_settings', d.error ? 'err' : 'ok')
}
function cfgFormat() {
  const ta = document.getElementById('cfg_editor')
  try {
    const parsed = JSON.parse(ta.value)
    ta.value = JSON.stringify(parsed, null, 2)
  } catch (e) {
    alert('Ugyldig JSON: ' + e.message)
  }
}
async function cfgSave() {
  const name = document.getElementById('cfg_file').value
  const content = document.getElementById('cfg_editor').value
  setLamp('status_settings', 'busy')
  let parsed
  try {
    parsed = JSON.parse(content)
  } catch (e) {
    setLamp('status_settings', 'err')
    return alert('Ugyldig JSON: ' + e.message)
  }
  const r = await fetch('/api/config?name=' + encodeURIComponent(name), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: JSON.stringify(parsed) }),
  })
  const d = await r.json()
  if (d.ok) setLamp('status_settings', 'ok')
  else setLamp('status_settings', 'err')
}

/* ---------- FORMAT UI <-> JSON ---------- */
function _linesToList(id) {
  const el = document.getElementById(id)
  if (!el) return []
  return el.value
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean)
}
function _listToLines(arr) {
  return (arr || []).join('\n')
}
function _csvToList(s) {
  return (s || '')
    .split(/[,\s]+/)
    .map((x) => x.trim())
    .filter(Boolean)
}
function _listToCsv(arr) {
  return (arr || []).join(',')
}

/* Les format-config fra server og sett felter i UI */
async function loadFormatUIFromConfig() {
  try {
    const r = await fetch('/api/config?name=' + encodeURIComponent('format_config.json'))
    const d = await r.json()
    if (!d.content) return
    const cfg = JSON.parse(d.content)
    const fmt = cfg.format || {}
    // Prettier
    const pr = fmt.prettier || {}
    document.getElementById('fmt_prettier_enable').checked = !!pr.enable
    document.getElementById('fmt_prettier_globs').value = _listToLines(pr.globs || [])
    const extra = pr.extra_args || []
    const getArg = (key) => {
      const i = extra.indexOf(key)
      return i >= 0 ? extra[i + 1] : null
    }
    const has = (key) => extra.includes(key)
    document.getElementById('fmt_prettier_printWidth').value = getArg('--print-width') || ''
    document.getElementById('fmt_prettier_tabWidth').value = getArg('--tab-width') || ''
    document.getElementById('fmt_prettier_singleQuote').checked = has('--single-quote')
    document.getElementById('fmt_prettier_semi').checked = !has('--no-semi')
    document.getElementById('fmt_prettier_trailingComma').value = getArg('--trailing-comma') || ''
    // Black
    const bl = fmt.black || {}
    document.getElementById('fmt_black_enable').checked = !!bl.enable
    document.getElementById('fmt_black_paths').value = (bl.paths || []).join(', ')
    const blArgs = bl.args || []
    const blGet = (key) => {
      const i = blArgs.indexOf(key)
      return i >= 0 ? blArgs[i + 1] : null
    }
    document.getElementById('fmt_black_line_length').value = blGet('--line-length') || ''
    document.getElementById('fmt_black_target').value = blGet('--target-version') || ''
    // Ruff
    const rf = fmt.ruff || {}
    document.getElementById('fmt_ruff_enable').checked = !!rf.enable
    const rfArgs = rf.args || []
    const rfHas = (key) => rfArgs.includes(key)
    const rfGet = (key) => {
      const i = rfArgs.indexOf(key)
      return i >= 0 ? rfArgs[i + 1] : null
    }
    document.getElementById('fmt_ruff_fix').checked = rfHas('--fix')
    document.getElementById('fmt_ruff_unsafe').checked = rfHas('--unsafe-fixes')
    document.getElementById('fmt_ruff_preview').checked = rfHas('--preview')
    const sel = rfGet('--select')
    const ign = rfGet('--ignore')
    document.getElementById('fmt_ruff_select').value = sel ? sel.split(',').join('\n') : ''
    document.getElementById('fmt_ruff_ignore').value = ign ? ign.split(',').join('\n') : ''
    // Cleanup
    const cl = fmt.cleanup || {}
    document.getElementById('fmt_cleanup_enable').checked = !!cl.enable
    document.getElementById('fmt_cleanup_compact').checked = !!cl.compact_blocks
    document.getElementById('fmt_cleanup_maxblank').value = String(cl.max_consecutive_blanks ?? '')
    document.getElementById('fmt_cleanup_exts').value = _listToLines(cl.exts || [])
    document.getElementById('fmt_cleanup_excl_exts').value = _listToLines(cl.exclude_exts || [])
  } catch (e) {
    console.warn('[format] Kunne ikke laste format_config.json:', e)
  }
}

/* Samle UI → format-config (felles struktur) */
function gatherFormatUIToConfig() {
  const extra = []
  const pw = document.getElementById('fmt_prettier_printWidth').value.trim()
  if (pw) extra.push('--print-width', pw)
  const tw = document.getElementById('fmt_prettier_tabWidth').value.trim()
  if (tw) extra.push('--tab-width', tw)
  if (document.getElementById('fmt_prettier_singleQuote').checked) extra.push('--single-quote')
  if (!document.getElementById('fmt_prettier_semi').checked) extra.push('--no-semi')
  const tc = document.getElementById('fmt_prettier_trailingComma').value
  if (tc) extra.push('--trailing-comma', tc)
  const prettier = {
    enable: document.getElementById('fmt_prettier_enable').checked,
    globs: _linesToList('fmt_prettier_globs'),
    extra_args: extra,
  }

  const blArgs = []
  const blLL = document.getElementById('fmt_black_line_length').value.trim()
  if (blLL) blArgs.push('--line-length', blLL)
  const blTarget = document.getElementById('fmt_black_target').value.trim()
  if (blTarget) blArgs.push('--target-version', blTarget)
  const black = {
    enable: document.getElementById('fmt_black_enable').checked,
    paths: (document.getElementById('fmt_black_paths').value || './')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean),
    args: blArgs,
  }

  const args = ['check', './']
  if (document.getElementById('fmt_ruff_fix').checked) args.push('--fix')
  if (document.getElementById('fmt_ruff_unsafe').checked) args.push('--unsafe-fixes')
  if (document.getElementById('fmt_ruff_preview').checked) args.push('--preview')
  const sel = _linesToList('fmt_ruff_select')
  const ign = _linesToList('fmt_ruff_ignore')
  if (sel.length) args.push('--select', sel.join(','))
  if (ign.length) args.push('--ignore', ign.join(','))
  const ruff = { enable: document.getElementById('fmt_ruff_enable').checked, args }

  const cleanup = {
    enable: document.getElementById('fmt_cleanup_enable').checked,
    compact_blocks: document.getElementById('fmt_cleanup_compact').checked,
    max_consecutive_blanks: parseInt(document.getElementById('fmt_cleanup_maxblank').value || '0', 10),
    exts: _linesToList('fmt_cleanup_exts'),
    exclude_exts: _linesToList('fmt_cleanup_excl_exts'),
    paths: [],
  }

  return { format: { prettier, black, ruff, cleanup } }
}

/* Lagre format_config.json via API */
async function saveFormatConfig() {
  const payload = gatherFormatUIToConfig()
  const body = { content: JSON.stringify(payload) }
  const r = await fetch('/api/config?name=' + encodeURIComponent('format_config.json'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const d = await r.json()
  if (!d.ok) alert('Klarte ikke å lagre format_config.json')
  else alert('Lagret format_config.json')
}

/* Settings-knapper */
document.getElementById('cfg_file').addEventListener('change', cfgLoad)
document.getElementById('cfg_reload').onclick = cfgLoad
document.getElementById('cfg_format').onclick = cfgFormat
document.getElementById('cfg_save').onclick = cfgSave
document.getElementById('settings_diag').onclick = async (e) => {
  e.preventDefault()
  const dbg = await fetch('/api/debug-config').then((r) => r.json())
  document.getElementById('out_settings').value = JSON.stringify(dbg, null, 2)
}

/* FORMAT summary renderer */
function renderFormatSummary(result) {
  let box = document.getElementById('fmt_summary')
  if (!box) {
    const out = document.getElementById('out_format')
    if (out && out.parentElement) {
      box = document.createElement('pre')
      box.id = 'fmt_summary'
      box.className = 'summary'
      box.style.marginTop = '8px'
      box.style.whiteSpace = 'pre-wrap'
      out.parentElement.appendChild(box)
    }
  }
  if (!box) return
  const s = (result && result.format_summary) || {}
  const pr = s.prettier || {}
  const rf = s.ruff || {}
  const cl = s.cleanup || {}
  const bk = s.black || {}
  const lines = []
  lines.push(`Prettier: ${pr.formatted ?? 0} filer formatert${pr.errors ? `, ${pr.errors} feil` : ''}`)
  if (pr.cmds && pr.cmds.length) lines.push(`Cmd: ${pr.cmds[0]}`)
  lines.push(`Black: ${bk.ran ? 'kjørt' : 'ikke kjørt'}`)
  lines.push(`Ruff: ${rf.violations ?? 0} funn${rf.fixed != null ? `, ${rf.fixed} auto-fikset` : ''}`)
  if (rf.codes) {
    const top = Object.entries(rf.codes)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([k, v]) => `${k}:${v}`)
      .join('  ')
    if (top) lines.push(`  ${top}`)
  }
  if (cl.changed != null && cl.total != null) lines.push(`Cleanup: ${cl.changed}/${cl.total} endret`)
  box.textContent = lines.join('\n')
}

/* Pref-lagring (feltliste) */
// prettier-ignore
const PREF_FIELDS = `
project search_terms search_all search_case search_max search_files_only search_path_mode
search_limit_dirs search_limit_exts search_include search_exclude search_filename_search
rep_filename_search paste_list_only paste_filename_search paste_max paste_out paste_include paste_exclude
format_dry clean_what clean_skip gh_prefix gh_wrap_read
rep_find rep_repl rep_regex rep_case rep_backup rep_dry rep_showdiff rep_max rep_include rep_exclude
fmt_prettier_enable fmt_prettier_globs fmt_prettier_printWidth fmt_prettier_tabWidth fmt_prettier_singleQuote fmt_prettier_semi fmt_prettier_trailingComma
fmt_black_enable fmt_black_paths fmt_black_line_length fmt_black_target
fmt_ruff_enable fmt_ruff_fix fmt_ruff_unsafe fmt_ruff_preview fmt_ruff_select fmt_ruff_ignore
fmt_cleanup_enable fmt_cleanup_compact fmt_cleanup_maxblank fmt_cleanup_exts fmt_cleanup_excl_exts
`.trim().split(/\s+/);

PREF_FIELDS.forEach((id) => {
  document.addEventListener('change', (e) => {
    if (e.target && e.target.id === id) savePrefs()
  })
  document.addEventListener('input', (e) => {
    if (e.target && e.target.id === id) savePrefs()
  })
})

/* Project change */
document.getElementById('project').addEventListener('change', async () => {
  loadPrefs()
  await fetchGitRemotes()
  await fetchGitBranches()
  await fetchCleanConfig()
})

/* Clean modus-warning */
document.addEventListener('change', (e) => {
  if (e.target && (e.target.id === 'clean_mode_dry' || e.target.id === 'clean_mode_apply')) {
    updateCleanWarning()
  }
})

/* Refresh-knapp */
document.getElementById('refresh').onclick = async () => {
  await fetchProjects()
  await fetchGitRemotes()
  await fetchGitBranches()
  await fetchRecipes()
  await fetchBackupInfo()
  await fetchBackupProfiles()
  await fetchCleanConfig()
  await loadSettings()
  await loadFormatUIFromConfig()
  loadPrefs()
}

/* Verktøykjøring */
document.getElementById('run_search').onclick = () =>
  withStatus('search', 'out_search', async () => {
    const terms = document.getElementById('search_terms').value.trim()
    const dirsText = document.getElementById('search_limit_dirs').value
    const limitDirs = dirsText
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    const extsText = document.getElementById('search_limit_exts').value.trim()
    const limitExts = extsText
      ? extsText
          .split(/[,\s]+/)
          .map((s) => s.trim())
          .filter(Boolean)
      : []
    const inc =
      document
        .getElementById('search_include')
        ?.value.split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean) || []
    const exc =
      document
        .getElementById('search_exclude')
        ?.value.split(/\r?\n/)
        .map((s) => s.trim())
        .filter(Boolean) || []
    const fn = !!document.getElementById('search_filename_search')?.checked
    const args = {
      terms: terms
        ? terms
            .split(',')
            .map((s) => s.trim())
            .filter(Boolean)
        : [],
      case_sensitive: document.getElementById('search_case').checked,
      all: document.getElementById('search_all').checked,
      max_size: parseInt(document.getElementById('search_max').value || '2000000', 10),
      files_only: document.getElementById('search_files_only').checked,
      path_mode: document.getElementById('search_path_mode').value,
      limit_dirs: limitDirs,
      limit_exts: limitExts,
      filename_search: fn,
    }
    if (inc.length) args.include = inc
    if (exc.length) args.exclude = exc
    return runTool('search', { args }, 'out_search')
  })
document.getElementById('search_terms').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') document.getElementById('run_search').click()
})

document.getElementById('run_replace').onclick = () =>
  withStatus('replace', 'out_replace', async () => {
    const inc = document
      .getElementById('rep_include')
      .value.split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    const exc = document
      .getElementById('rep_exclude')
      .value.split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    return runTool(
      'replace',
      {
        args: {
          find: document.getElementById('rep_find').value,
          replace: document.getElementById('rep_repl').value,
          regex: document.getElementById('rep_regex').checked,
          case_sensitive: document.getElementById('rep_case').checked,
          backup: document.getElementById('rep_backup').checked,
          dry_run: document.getElementById('rep_dry').checked,
          show_diff: document.getElementById('rep_showdiff').checked,
          include: inc,
          exclude: exc,
          max_size: parseInt(document.getElementById('rep_max').value || '2000000', 10),
          filename_search: !!document.getElementById('rep_filename_search').checked,
        },
      },
      'out_replace'
    )
  })

document.getElementById('save_clean_targets').onclick = async () => {
  const targets = collectCleanTargets()
  const proj = currentProject()
  await withStatus('clean', 'out_clean', async () => {
    const r = await fetch('/api/clean-targets?project=' + encodeURIComponent(proj), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ targets }),
    })
    const data = await r.json()
    document.getElementById('out_clean').value = data.message || data.error || JSON.stringify(data, null, 2)
    return data
  })
}

document.getElementById('run_paste').onclick = () =>
  withStatus('paste', 'out_paste', async () => {
    const payload = { args: {} }
    payload.args.list_only = document.getElementById('paste_list_only').checked
    const out = document.getElementById('paste_out').value.trim()
    if (out) payload.args.out_dir = out
    const mx = parseInt(document.getElementById('paste_max').value || '4000', 10)
    if (!Number.isNaN(mx)) payload.args.max_lines = mx
    payload.args.filename_search = !!document.getElementById('paste_filename_search').checked
    const inc = document
      .getElementById('paste_include')
      .value.split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (inc.length) payload.args.include = inc
    const exc = document
      .getElementById('paste_exclude')
      .value.split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    if (exc.length) payload.args.exclude = exc
    return runTool('paste', payload, 'out_paste')
  })

document.getElementById('run_format').onclick = () =>
  withStatus('format', 'out_format', async () => {
    const globs = (document.getElementById('fmt_prettier_globs').value || '')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    const black_paths = (document.getElementById('fmt_black_paths').value || '')
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean)
    const fmtOverride = { format: {} }
    fmtOverride.format.prettier = {
      enable: !!document.getElementById('fmt_prettier_enable').checked,
      globs: globs.length ? globs : undefined,
      printWidth: parseInt(document.getElementById('fmt_prettier_printWidth').value || '0', 10) || undefined,
      tabWidth: parseInt(document.getElementById('fmt_prettier_tabWidth').value || '0', 10) || undefined,
      singleQuote: !!document.getElementById('fmt_prettier_singleQuote').checked,
      semi: !!document.getElementById('fmt_prettier_semi').checked,
      trailingComma: document.getElementById('fmt_prettier_trailingComma').value,
    }
    fmtOverride.format.black = {
      enable: !!document.getElementById('fmt_black_enable').checked,
      paths: black_paths.length ? black_paths : undefined,
      line_length: parseInt(document.getElementById('fmt_black_line_length').value || '0', 10) || undefined,
      target_version:
        (document.getElementById('fmt_black_target').value || '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean) || undefined,
    }
    fmtOverride.format.ruff = {
      enable: !!document.getElementById('fmt_ruff_enable').checked,
      fix: !!document.getElementById('fmt_ruff_fix').checked,
      unsafe_fixes: !!document.getElementById('fmt_ruff_unsafe').checked,
      preview: !!document.getElementById('fmt_ruff_preview').checked,
      select:
        (document.getElementById('fmt_ruff_select').value || '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean) || undefined,
      ignore:
        (document.getElementById('fmt_ruff_ignore').value || '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean) || undefined,
    }
    fmtOverride.format.cleanup = {
      enable: !!document.getElementById('fmt_cleanup_enable').checked,
      compact_blocks: !!document.getElementById('fmt_cleanup_compact').checked,
      max_consecutive_blanks: parseInt(document.getElementById('fmt_cleanup_maxblank').value || '0', 10),
      exts:
        (document.getElementById('fmt_cleanup_exts').value || '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean) || undefined,
      exclude_exts:
        (document.getElementById('fmt_cleanup_excl_exts').value || '')
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean) || undefined,
    }
    const res = await runTool(
      'format',
      { args: { dry_run: document.getElementById('format_dry').checked, override: fmtOverride } },
      'out_format'
    )
    renderFormatSummary(res)
    return res
  })

document.getElementById('fmt_load_cfg').onclick = async () => {
  await withStatus('format', 'out_format', async () => {
    await loadFormatFromConfig(false)
    savePrefs()
  })
}
document.getElementById('fmt_save_cfg').onclick = async () => {
  const payload = gatherFormatUIToConfig()
  await withStatus('format', 'out_format', async () => {
    const r = await fetch('/api/config?name=' + encodeURIComponent('format_config.json'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: JSON.stringify(payload) }),
    })
    const d = await r.json()
    const out = document.getElementById('out_format')
    out.value = d.ok ? 'Lagret format_config.json' : d.error || JSON.stringify(d)
  })
}
document.getElementById('fmt_preview_btn').onclick = async () => {
  const rel = document.getElementById('fmt_preview_path').value.trim()
  const proj = currentProject()
  const out = document.getElementById('fmt_preview_out')
  out.value = ''
  if (!rel) {
    out.value = 'Oppgi en relativ filsti (f.eks. app/main.py).'
    return
  }
  await withStatus('format', 'out_format', async () => {
    const r = await fetch('/api/format-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ project: proj, path: rel }),
    })
    const d = await r.json()
    out.value = (d.output || d.error || '').trim()
    return d
  })
}

document.getElementById('run_clean').onclick = () =>
  withStatus('clean', 'out_clean', async () => {
    const what = document.getElementById('clean_what').value.trim()
    const skip = document.getElementById('clean_skip').value.trim()
    const targets = collectCleanTargets()
    const mode = currentCleanMode()
    if (mode === 'apply') {
      const ok = confirm(['Dette vil SLETTE filer.', 'Er du sikker på at du vil fortsette?'].join('\n'))
      if (!ok) return
    }
    return runTool(
      'clean',
      {
        args: {
          mode,
          what: what
            ? what
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean)
            : [],
          skip: skip
            ? skip
                .split(',')
                .map((s) => s.trim())
                .filter(Boolean)
            : [],
          targets,
        },
      },
      'out_clean'
    )
  })

document.getElementById('run_gh').onclick = () =>
  withStatus('gh-raw', 'out_gh', async () => {
    return runTool(
      'gh-raw',
      {
        args: {
          path_prefix: document.getElementById('gh_prefix').value.trim(),
          wrap_read: !!document.getElementById('gh_wrap_read')?.checked,
        },
      },
      'out_gh'
    );
  });


if (document.getElementById('run_backup')) {
  document.getElementById('run_backup').onclick = () =>
    withStatus('backup', 'out_backup', async () => {
      const sel = document.getElementById('bk_profile_select')
      const profile = sel && sel.value ? sel.value.trim() : ''
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
        dropbox_mode: document.getElementById('bk_dbx_mode')?.value || undefined,
      }
      return runTool('backup', { args: payload }, 'out_backup')
    })
}
if (document.getElementById('run_backup_env')) {
  document.getElementById('run_backup_env').onclick = async () => {
    await withStatus('backup', 'out_backup', async () => {
      const r = await fetch('/api/diag/dropbox')
      const data = await r.json()
      document.getElementById('out_backup').value = (data.output || data.error || '').trim()
      return data
    })
  }
}
if (document.getElementById('fmt_save')) {
  document.getElementById('fmt_save').onclick = async () => {
    await saveFormatConfig()
  }
}

/* FORMAT underfaner */
document.getElementById('fmt_tabs').addEventListener('click', (e) => {
  const btn = e.target.closest('.fmt-tab')
  if (!btn) return
  const tab = btn.getAttribute('data-fmt-tab')
  document.querySelectorAll('.fmt-tab').forEach((t) => t.classList.toggle('active', t === tab))
  document.querySelectorAll('.fmt-pane').forEach((p) => p.classList.toggle('active', p.getAttribute('data-fmt-pane') === tab))
})

/* Helper for setVal */
function _setVal(id, val, isChk = false) {
  const el = document.getElementById(id)
  if (!el) return
  if (isChk) el.checked = !!val
  else if (val !== undefined && val !== null) el.value = String(val)
}

/* Les format_config og fyll UI (respekter ev. localStorage) */
async function loadFormatFromConfig(preferPrefs = true) {
  const r = await fetch('/api/config?name=' + encodeURIComponent('format_config.json'))
  const d = await r.json()
  let cfg = {}
  try {
    cfg = JSON.parse(d.content || '{}')
  } catch {}
  const f = cfg.format || {}
  // Prettier
  const pr = f.prettier || {}
  if (!preferPrefs || !localStorage.getItem(PREF_KEY(currentProject()))) {
    _setVal('fmt_prettier_enable', pr.enable, true)
    _setVal('fmt_prettier_globs', Array.isArray(pr.globs) ? pr.globs.join(',') : pr.globs)
    _setVal('fmt_prettier_printWidth', pr.printWidth)
    _setVal('fmt_prettier_tabWidth', pr.tabWidth)
    _setVal('fmt_prettier_singleQuote', pr.singleQuote, true)
    _setVal('fmt_prettier_semi', pr.semi, true)
    _setVal('fmt_prettier_trailingComma', pr.trailingComma)
  }
  // Black
  const bl = f.black || {}
  _setVal('fmt_black_enable', bl.enable, true)
  _setVal('fmt_black_paths', Array.isArray(bl.paths) ? bl.paths.join(',') : bl.paths)
  _setVal('fmt_black_line_length', bl.line_length)
  _setVal('fmt_black_target', bl.target)
  // Ruff
  const rf = f.ruff || {}
  _setVal('fmt_ruff_enable', rf.enable, true)
  _setVal('fmt_ruff_fix', rf.fix !== false, true)
  _setVal('fmt_ruff_unsafe', !!rf.unsafe_fixes, true)
  _setVal('fmt_ruff_preview', !!rf.preview, true)
  _setVal('fmt_ruff_select', rf.select)
  _setVal('fmt_ruff_ignore', rf.ignore)
  // Cleanup
  const cl = f.cleanup || {}
  _setVal('fmt_cleanup_enable', cl.enable, true)
  _setVal('fmt_cleanup_compact', cl.compact_blocks !== false, true)
  _setVal('fmt_cleanup_maxblank', cl.max_consecutive_blanks ?? 1)
  _setVal('fmt_cleanup_exts', Array.isArray(cl.exts) ? cl.exts.join(',') : cl.exts)
  _setVal('fmt_cleanup_excl_exts', Array.isArray(cl.exclude_exts) ? cl.exclude_exts.join(',') : cl.exclude_exts)
}

/* ---------- Help panel control (per-tool) ---------- */
const HELP_STATE_KEY = (tool) => `rtools:help_open:${tool}`
function setHelpOpen(tool, open) {
  const panel = document.querySelector(`.help-panel[data-help-for="${tool}"]`)
  if (!panel) return
  if (open) {
    panel.classList.add('open')
    panel.classList.remove('collapsed')
    localStorage.setItem(HELP_STATE_KEY(tool), '1')
  } else {
    panel.classList.remove('open')
    panel.classList.add('collapsed')
    localStorage.removeItem(HELP_STATE_KEY(tool))
  }
}
function toggleHelp(tool) {
  const panel = document.querySelector(`.help-panel[data-help-for="${tool}"]`)
  if (!panel) return
  const isOpen = panel.classList.contains('open')
  setHelpOpen(tool, !isOpen)
}
document.addEventListener('click', (e) => {
  const btn = e.target.closest('.help-toggle')
  if (!btn) return
  const tool = btn.getAttribute('data-help-for')
  if (!tool) return
  toggleHelp(tool)
})
const _origSetActiveTool = setActiveTool
setActiveTool = function (name) {
  _origSetActiveTool(name)
  document.querySelectorAll('.help-panel').forEach((p) => p.classList.remove('open'))
  const wasOpen = !!localStorage.getItem(HELP_STATE_KEY(name))
  if (wasOpen) setHelpOpen(name, true)
}

/* Init */
Object.keys(STATUS_IDS).forEach((k) => setStatus(k, 'idle'))
setLamp('status_global', 'idle')
setLamp('status_init', 'busy')
;(async function init() {
  try {
    await fetchProjects()
    await fetchGitRemotes()
    await fetchGitBranches()
    document.getElementById('project').addEventListener('change', async () => {
      await fetchGitRemotes()
      await fetchGitBranches()
    })
    await fetchRecipes()
    await fetchBackupInfo()
    await fetchBackupProfiles()
    await fetchCleanConfig()
    const stored = localStorage.getItem(ACTIVE_TOOL_KEY)
    if (stored && TOOLS.includes(stored)) setActiveTool(stored)
    else {
      const s = await fetch('/api/settings')
        .then((r) => r.json())
        .catch(() => ({ global: {} }))
      setActiveTool(s?.global?.default_tool || 'search')
    }
    await loadSettings()
    await loadFormatUIFromConfig()
    loadPrefs()
    await loadFormatFromConfig(true)
    updateCleanWarning()
    setLamp('status_init', 'ok')
    console.log('[webui] init OK')
  } catch (e) {
    setLamp('status_init', 'err')
    console.error('[webui] init failed:', e)
    alert(['UI-init feilet.', 'Sjekk nettleserkonsollen for detaljer.'].join('\n'))
  }
})()
