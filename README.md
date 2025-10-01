# r\_tools

Et lettvint verktøysett for daglig utvikling på Linux/Raspberry Pi. **r\_tools** samler flere småverktøy i én konsistent CLI: søk i kode, generer innlimingsklare «paste chunks», list rå GitHub‑lenker og kjør formatteringsverktøy – alt konfigurerbart og kjørbart fra hvilken som helst sti.

> Repo: `Sygaro/tools`

---

## ✨ Hovedidé

- **Én CLI (`rt`)** for alle verktøy.
- **Felles venv** og **felles config-struktur**.
- **Per‑prosjekt overrides** via `.r-tools.json` i arbeidskatalogen.
- Kjør uten å aktivere venv og uten å cd’e inn i repoet.

---

## 📦 Innhold

- `rt search` – raskt regex‑søk i prosjektfiler med farge/highlight.
- `rt paste` – pakk filer i innlimingsklare tekstblokker («chunks») med rammeinfo.
- `rt gh-raw` – list rå GitHub‑lenker for et repo/branch (ingen `jq`/`curl` nødvendig).
- `rt format` – kjør `prettier`, `black`, `ruff` etter config.
- `rt clean` – slett midlertidige/katalog‑cache via trygge filtre.
- `rt list` – vis effektive config‑verdier og opprinnelse (hvilken fil som «vant»).

---

## 🔧 Forutsetninger

- Linux/Unix shell eller macOS.
- Python 3.10+ installert.
- (Valgfritt) Verktøy i PATH når brukt:
  - `npx` (for `prettier`), `black`, `ruff` dersom du bruker `rt format`.

---

## 🚀 Installasjon

```bash
# klon
git clone https://github.com/Sygaro/tools.git
cd tools

# gi kjørerett på launcher og legg på PATH
chmod +x bin/rt
sudo ln -sf "$(pwd)/bin/rt" /usr/local/bin/rt

# første kjøring oppretter venv og installerer requirements automatisk
rt list
```

> **Merk:** `rt` aktiverer/bruker repoets venv automatisk. Du trenger ikke `source venv/bin/activate`.

---

## 🗂️ Mappestruktur (kort)

```
tools/
├─ bin/rt                 # launcher (aktiverer venv, starter CLI)
├─ configs/               # globale og verktøyspesifikke JSON-konfiger
│  ├─ global_config.json
│  ├─ search_config.json
│  ├─ paste_config.json
│  ├─ gh_raw_config.json
│  └─ format_config.json
├─ r_tools/               # Python-pakke (selve verktøyene)
│  ├─ cli.py              # entrypoint for underkommandoer
│  ├─ config.py           # lasting/merging av config + provenance
│  └─ tools/
│     ├─ code_search.py   # rt search
│     ├─ paste_chunks.py  # rt paste
│     ├─ gh_raw.py        # rt gh-raw
│     ├─ format_code.py   # rt format
│     └─ clean_temp.py    # rt clean
└─ requirements.txt       # lette Python-avhengigheter
```

---

## ⚙️ Konfigurasjon

Konfig lastes i følgende prioritet (sist vinner):

1. `configs/global_config.json`
2. *Valgfritt:* verktøyspesifikk (`configs/<tool>_config.json`)
3. *Valgfritt:* prosjekt‑override i **arbeidskatalogen**: `./.r-tools.json`
4. *Valgfritt:* CLI‑flagg

> **Viktig:** JSON‑filer må være gyldig JSON – **ingen kommentarer** (`//`, `/* */`)!

### Eksempel: `configs/global_config.json`

```json
{
  "project_root": ".",
  "include_extensions": [".py", ".sh", ".c", ".cpp", ".h", ".js", ".ts"],
  "exclude_dirs": ["__pycache__", "build", ".git", "node_modules", "venv"],
  "exclude_files": [],
  "case_insensitive": true,
  "paste": {
    "root": ".",
    "out_dir": "paste_out",
    "max_lines": 4000,
    "allow_binary": false,
    "include": ["**/*.py", "**/*.js", "**/*.ts", "**/*.css", "**/*.html", "**/*.json", "**/*.md", "**/*.sh"],
    "exclude": ["**/.git/**", "**/venv/**", "**/node_modules/**", "**/__pycache__/**", "**/.pytest_cache/**", "**/.mypy_cache/**", "**/.DS_Store"],
    "only_globs": [],
    "skip_globs": []
  },
  "gh_raw": { "user": "Sygaro", "repo": "countdown", "branch": "main", "path_prefix": "" },
  "format": {
    "prettier": { "enable": true, "globs": ["static/**/*.{html,css,js}"] },
    "black":    { "enable": true, "paths": ["app"] },
    "ruff":     { "enable": true, "args": ["check", "app", "--fix"] }
  },
  "clean": {
    "enable": true,
    "targets": {
      "pycache": true,
      "pytest_cache": true,
      "mypy_cache": true,
      "ruff_cache": true,
      "coverage": true,
      "build": true,
      "dist": true,
      "editor": true,
      "ds_store": true,
      "thumbs_db": true,
      "node_modules": false
    },
    "extra_globs": [],
    "skip_globs": []
  }
}
```

### Per‑prosjekt override: `./.r-tools.json`

```json
{
  "project_root": ".",
  "search_terms": ["\\bclass\\b"],
  "paste": {
    "only_globs": ["app/**", "tools/**"],
    "skip_globs": ["**/dist/**", "**/*.min.js"]
  }
}
```

---

## 🧰 Bruk

### `rt list` – vis aktiv config og opprinnelse

```bash
rt list                 # alt
rt list --tool paste    # kun paste‑delen
rt list --tool search   # kun search‑delen
```

Viser hvilke filer som ble brukt og «opprinnelse» per nøkkel (hvem overstyrte hva).

### `rt search` – regex‑søk i kode

```bash
# bruk konfigurerte søkeord
rt search

# eksplisitte regex‑termer
rt search class
rt search "import\\s+os" --count
rt search --project /path/til/prosjekt --ext .py .sh --case-sensitive
```

- Filtrer på filendelser, ekskluder kataloger/filer via config eller CLI.
- Farge/highlight i terminal (kan skrus av med `--no-color`).

### `rt paste` – generer «paste chunks»

```bash
# list bare hvilke filer som ville blitt inkludert
rt paste --list-only

# generer filer til standard out_dir
rt paste

# overrides
rt paste --project . --out build/paste --max-lines 3000
```

- Pakker hver kildefil inn i en ramme: `BEGIN/END FILE`, `PATH`, `LINES`, `SHA256`.
- Støtter `allow_binary` (hex‑dump), `only_globs` og `skip_globs` for rask filtrering.

### `rt gh-raw` – list rå GitHub‑lenker

```bash
rt gh-raw
rt gh-raw --path-prefix app/routes --json
```

Returnerer `https://raw.githubusercontent.com/<user>/<repo>/<branch>/<path>` for alle filer i treet (kan filtreres med `path_prefix`).

### `rt format` – kjør formattere

```bash
rt format
rt format --dry-run
```

Kjører `prettier` (via `npx`), `black`, `ruff` dersom de finnes i PATH og er aktivert i config.

### `rt clean` – slett midlertidige filer/kataloger

```bash
# vis hva som ville blitt slettet (standard)
rt clean

# slett faktisk (krever --yes)
rt clean --yes

# begrens til gitte mål (overstyrer config)
rt clean --what pycache ruff_cache coverage --yes

# hopp over node_modules uansett config
rt clean --skip node_modules

# tørkekjøring + mer pratsom
rt clean --dry-run
```

- Trygg som standard: kjører **dry‑run** med oversikt. Du må eksplisitt bruke `--yes` for å slette.
- Mål defineres i `clean.targets` i konfig (`true/false`). CLI `--what` kan snevre inn, `--skip` kan utelate.
- Støtter ekstra mønstre i `clean.extra_globs` og unntak i `clean.skip_globs`.

---

## 🧪 Tips & feilsøking

- **JSON‑feil**: `rt list --tool paste` feiler ofte hvis en JSON‑fil er tom/ugyldig. Valider med `jq . <fil>` (om du har `jq`).
- **PATH**: Sørg for at `/usr/local/bin/rt` peker til repoets `bin/rt`.
- **Ytelse**: bruk `only_globs`/`skip_globs` for å redusere søkeområde.

---

## 🛣️ Veikart

- `rt paste --since <git-ref>` (kun endrede filer)
- `rt search --json` (maskinlesbar output)
- `rt gh-raw` med token fra env for høyere rate‑limit

---

## Lisens

MIT (se `LICENSE` dersom tilgjengelig).

