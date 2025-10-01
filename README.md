# r_tools — små, fleksible dev‑verktøy for prosjekter (RPi m.m.)

**r_tools** samler flere CLI- og UI‑verktøy i én struktur: søk i kode, bygg "paste chunks", formattering/rydding, sletting av cache, GitHub raw‑lister og integrert **backup**. Alt kan kjøres fra terminal (`rt …`) eller via et lite web‑UI.

> Støttet plattform: Linux/macOS (testet på Raspberry Pi 4/5).

---

## Innhold
- `rt search` – raske søk i prosjektfiler (regex, flere termer, AND/OR)
- `rt paste` – generer innlimingsklare tekstfiler ("paste_001.txt" …)
- `rt format` – kjør Prettier/Black/Ruff + valgfri whitespace‑opprydding
- `rt clean` – trygg sletting av cache/temp (dry‑run som standard)
- `rt gh-raw` – list rå‑URLer (GitHub API)
- `rt backup` – integrasjon mot din eksisterende `backup_app/backup.py`
- `rt serve` – enkel web‑UI for alle verktøy (prosjektvelger + oppskrifter)

---

## Installasjon
```bash
# klon repo
git clone https://github.com/Sygaro/tools
cd tools

# opprett venv og installer avhengigheter
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# legg rt på PATH (enkelt alias)
# legg denne i ~/.bashrc eller ~/.zshrc
alias rt="python -m r_tools.cli"
```

> Alternativt kan du lage en liten wrapper i `/usr/local/bin/rt` som kjører `python -m r_tools.cli` i riktig venv.

---

## Katalogstruktur (utdrag)
```
tools/
├─ r_tools/
│  ├─ cli.py
│  ├─ config.py
│  └─ tools/
│     ├─ code_search.py   # search
│     ├─ paste_chunks.py  # paste
│     ├─ format_code.py   # format
│     ├─ clean_temp.py    # clean
│     ├─ gh_raw.py        # gh-raw
│     └─ webui.py         # rt serve
├─ backup_app/            # din eksisterende backup-app
│  ├─ backup.py
│  └─ ...
└─ configs/
   ├─ global_config.json
   ├─ search_config.json
   ├─ paste_config.json
   ├─ format_config.json
   ├─ clean_config.json
   ├─ gh_raw_config.json
   ├─ backup_config.json        # peker til backup_app/backup.py (valgfri)
   └─ backup_profiles.json      # profiler + default for backup
```

---

## Konfigurasjon
Alle verktøy leser først `configs/global_config.json` og deretter verktøyspesifikke filer. Prosjekt‑override kan gis i CLI/UI (project‑root).

**Viktig:** JSON kan **ikke** ha kommentarer. Bruk relative stier der det er naturlig.

### Global eksempel (`configs/global_config.json`)
```json
{
  "project_root": ".",
  "include_extensions": [".py", ".sh", ".c", ".cpp", ".h", ".js", ".ts"],
  "exclude_dirs": ["__pycache__", "build", ".git", "node_modules", "venv"],
  "exclude_files": [],
  "case_insensitive": true
}
```

### Paste (`configs/paste_config.json`)
```json
{
  "paste": {
    "root": ".",
    "out_dir": "paste_out",
    "max_lines": 4000,
    "allow_binary": false,
    "include": ["**/*.py", "**/*.js", "**/*.ts", "**/*.css", "**/*.html", "**/*.json", "**/*.md", "**/*.sh"],
    "exclude": ["**/.git/**", "**/venv/**", "**/node_modules/**", "**/__pycache__/**", "**/.pytest_cache/**", "**/.mypy_cache/**", "**/.DS_Store"],
    "only_globs": [],
    "skip_globs": [],
    "filename_search": true
  }
}
```

### Format (`configs/format_config.json`)
```json
{
  "format": {
    "prettier": { "enable": true, "globs": ["static/**/*.{html,css,js}"] },
    "black":    { "enable": true, "paths": ["app"] },
    "ruff":     { "enable": true, "args": ["check", "app", "--fix"] },
    "cleanup":  {
      "enable": true,
      "paths": ["app", "static"],
      "exts": [".py", ".js", ".ts", ".css", ".html", ".json", ".sh"],
      "trim_blanklines": true   
    }
  }
}
```

### Clean (`configs/clean_config.json`)
```json
{
  "clean": {
    "targets": {
      "pycache": true, "pytest_cache": true, "mypy_cache": true, "ruff_cache": true,
      "coverage": true, "build": true, "dist": true, "editor": true,
      "ds_store": true, "thumbs_db": true, "node_modules": false
    },
    "extra_globs": [],
    "skip_globs": []
  }
}
```

### Backup (`configs/backup_config.json` og `configs/backup_profiles.json`)
```json
// configs/backup_config.json
{ "backup": { "script": "backup_app/backup.py" } }
```
```json
// configs/backup_profiles.json
{
  "profiles": {
    "countdown_zip": {"project": "countdown", "source": "countdown", "dest": "backups", "format": "zip", "keep": 10},
    "countdown_tgz": {"project": "countdown", "source": "countdown", "dest": "backups", "format": "tar.gz", "keep": 10}
  },
  "default": "countdown_zip"
}
```

---

## Bruk (CLI)

### Search
```bash
rt search class --all --max-size 2000000
rt search "import\\s+os, class" --all  # flere termer (AND)
```

### Paste
```bash
rt paste --list-only
rt paste --out paste_out --max-lines 4000
```

### Format
```bash
rt format                # faktisk kjøring
rt format --dry-run      # simuler
```

### Clean (trygg som standard)
```bash
rt clean                 # dry-run
rt clean --yes           # slett faktisk
rt clean --what pycache ruff_cache --skip node_modules
```

### GitHub raw
```bash
rt gh-raw --json
```

### Backup
```bash
# bruker default-profil fra configs/backup_profiles.json
rt backup --dry-run --list

# eksplisitt profil
rt backup --profile countdown_zip --dry-run

# overstyr felter
rt backup --profile countdown_zip --tag nightly --keep 20
```

### List effektiv config/meta
```bash
rt list                  # alt
rt list --tool paste
rt list --tool backup    # viser backup.py + profiler/default
```

---

## Web‑UI
Start:
```bash
rt serve --host 0.0.0.0 --port 8765
```
Funksjoner:
- Prosjektvelger (fra `configs/projects_config.json`)
- Oppskrifter (knapper) fra `configs/recipes_config.json`
- Kort for hver funksjon (Search/Paste/Format/Clean/GH Raw/Backup)
- **Clean** har trygg modus-bryter (Dry‑run ↔ Apply) med advarsel
- **Backup** støtter profil‑dropdown (leses fra `configs/backup_profiles.json`)

> Favicon leveres av serveren (ingen 404). UI lagrer felt lokalt (per prosjekt).

---

## Feilsøking
- **Prettier/Black/Ruff ikke funnet**: installer i samme venv eller globalt.
- **JSON med kommentarer**: fjern `//`/`#` – JSON støtter ikke kommentarer.
- **GH‑raw 404**: sjekk `gh_raw_config.json` (user/repo/branch) og nett.
- **Backup**: verifiser `configs/backup_config.json` peker til riktig `backup.py`, og at `configs/backup_profiles.json` finnes.

---

## Lisens
MIT

---

## Endringslogg (kort)
- UI/CLI samkjørt for trygge standarder (clean = dry-run, backup = default‑profil)
- Filnavn‑søk i paste, AND‑søk i search, UI‑oppskrifter
- Backup‑integrasjon via wrapper (ingen endring i din `backup.py` nødvendig)

