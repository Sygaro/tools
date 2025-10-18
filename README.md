# r_tools

Et lite verktøysett for søk, formatering, opprydding, “paste-out”, GitHub raw-lenker og backup—med både CLI (`rt`) og et lite web-UI (FastAPI + Uvicorn).

- CLI: `bin/rt`
- Web UI: `rt serve` → åpner et UI på en port du velger
- Konfig: `tools/configs/*.json` (kan deles mellom UI og CLI)
- Støtte for Dropbox-opplasting i backup (med enkel env-sjekk/diagnose + wizard)

---

## Innhold

- [Forutsetninger](#forutsetninger)
- [Rask installasjon (setup-script)](#rask-installasjon-setup-script)
- [Manuell installasjon](#manuell-installasjon)
- [Starte UI/CLI](#starte-uicli)
- [Systemd-tjeneste](#systemd-tjeneste)
- [Konfigfiler](#konfigfiler)
- [Dropbox-oppsett](#dropbox-oppsett)
- [Feilsøking](#feilsøking)
- [Avinstallere](#avinstallere)

---

## Forutsetninger

- Linux (testet på Raspberry Pi OS/Debian)
- `python3.11+`, `pip`, `venv`, `git`
- Byggeverktøy anbefales: `build-essential` (på Debian/Ubuntu)

Installer raskt på Debian-baserte systemer:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git build-essential
```

---

## Rask installasjon (setup-script)

Repoet inkluderer et setup-script som setter opp alt for deg, og spør underveis:

- lager virtuelt miljø og installerer avhengigheter
- verifiserer/lagrer konfigfiler i `tools/configs`
- sørger for at du kan kjøre `rt` fra hvor som helst ved å linke **din** `bin/rt` til `~/.local/bin/rt`
- (valg) lager systemd-tjeneste (user/system)
- (valg) kjører Dropbox-wizard for å skaffe refresh token
- legger til miljøvariabler i `~/.bashrc` (bl.a. `RTOOLS_CONFIG_DIR`, `PATH`)

Kjør:

```bash
git clone https://github.com/Sygaro/tools
cd tools
sudo ./scripts/setup_tools.sh
```

> Scriptet må kjøres med `sudo` slik at det trygt kan opprette system-tjenester. Det sørger samtidig for at filer/mapper eies av din bruker etterpå.

Når scriptet er ferdig:

- åpne en ny terminal (for at `PATH` og env skal ta effekt)
- test: `which rt && rt --help`

---

## Manuell installasjon

Hvis du heller vil gjøre det manuelt:

```bash
git clone https://github.com/Sygaro/tools
cd tools

python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel
pip install -r requirements.txt
```

Gjør `rt` tilgjengelig i PATH uten å lage en ny binær—vi **bruker prosjektets `bin/rt`**:

```bash
mkdir -p ~/.local/bin
ln -sf "$PWD/bin/rt" ~/.local/bin/rt
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
echo "export RTOOLS_CONFIG_DIR=\"$PWD/configs\"" >> ~/.bashrc
# åpne en ny terminal etterpå
```

---

## Starte UI/CLI

- CLI:

  ```bash
  rt --help
  rt search "import\\s+os" --all
  ```

- UI (lokalt):
  ```bash
  rt serve --host 0.0.0.0 --port 8765
  ```
  Åpne i nettleser: `http://<pi-ip>:8765`

I UI:

- velg verktøy via tabs (Search, Paste, Format, Clean, GH Raw, Backup, Settings)
- statuslamper viser busy/ok/feil
- “Oppskrifter” (recipes) i toppmenyen gir hurtigkall for vanlige jobber
- “Settings” lagrer globale innstillinger i `configs/global_config.json`
- “Debug config” viser hvilke konfigfiler UI forventer og hvor de ligger

---

## Systemd-tjeneste

Du kan kjøre UI som systemd-tjeneste. Setup-scriptet spør om dette; her er manuelle kommandoer om du trenger dem.

### Bruker-tjeneste (anbefalt)

Støtter instanser via `@PORT`. Den bruker repoets `bin/rt` direkte.

```ini
# ~/.config/systemd/user/rtools@.service
[Unit]
Description=r_tools UI (user) on port %i
After=network.target

[Service]
Type=simple
ExecStart=%h/tools/bin/rt serve --host 0.0.0.0 --port %i
WorkingDirectory=%h/tools
Environment=RTOOLS_CONFIG_DIR=%h/tools/configs
Restart=on-failure

[Install]
WantedBy=default.target
```

Aktiver:

```bash
systemctl --user daemon-reload
systemctl --user enable --now rtools@8765.service
```

### System-tjeneste (hele systemet)

```ini
# /etc/systemd/system/rtools.service
[Unit]
Description=r_tools UI (system)
After=network.target

[Service]
Type=simple
User=<din-bruker>
Group=<din-bruker>
WorkingDirectory=/home/<din-bruker>/tools
Environment=RTOOLS_CONFIG_DIR=/home/<din-bruker>/tools/configs
ExecStart=/home/<din-bruker>/tools/bin/rt serve --host 0.0.0.0 --port 8765
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Aktiver:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now rtools.service
```

---

## Konfigfiler

Alle konfigfiler ligger i `tools/configs/` (kan overstyres med `RTOOLS_CONFIG_DIR`):

- `projects_config.json` – liste over prosjekter i UI-dropdown
- `recipes_config.json` – “Oppskrifter” på toppen (hurtigknapper)
- `search_config.json` – default søketermer for `search`
- `paste_config.json` – standardinnstillinger for “paste out”
- `format_config.json` – hvilke formattere/cleanup som brukes
- `clean_config.json` – hvilke rydde-mål (pycache, ruff_cache, …)
- `gh_raw_config.json` – repo/branch/path-oppsett for GH Raw
- `backup_config.json` – sti til `backup.py` + defaults
- `backup_profiles.json` – navngitte backup-profiler + default
- `global_config.json` – UI/CLI-globale innstillinger (f.eks. `default_project`, `default_tool`)

UI leser og **kan lagre**:

- globale innstillinger via fanen **Settings** (oppdaterer `global_config.json`)
- clean-targets via **Clean → Lagre targets** (oppdaterer `clean_config.json`)
- backup-script sti via **Settings** (oppdaterer `backup_config.json`)

> Endringer i disse filene gjelder også når du kjører CLI-kommandorer via `rt`.

---

## Dropbox-oppsett

For opplasting i backup:

1. **Wizard**  
   Du kan kjøre veiviseren (anbefalt). Fra UI: `Backup → Env-sjekk` gir status, og wizard kan kjøres via CLI (eller via `extra/dropbox_get_refresh_token.py`).

   Typisk:

   ```bash
   rt backup --wizard
   ```

   (eller kjør `python extra/dropbox_get_refresh_token.py` manuelt og følg instruksene)

2. **Miljøvariabler**  
   Verktøyene bruker:

   ```
   DROPBOX_APP_KEY
   DROPBOX_APP_SECRET
   DROPBOX_REFRESH_TOKEN
   ```

   Disse blir gjerne lagt i `~/.bashrc` av setup-scriptet eller wizard. Åpne ny terminal etterpå.

3. **Diagnose**  
   I UI: “Env-sjekk” (kaller `/api/diag/dropbox`) → viser om refresh funker og om token er gyldig.

---

## Feilsøking

- **`rt` ikke funnet**  
  Sørg for at `~/.local/bin` er på PATH, og at symlinken peker til prosjektets `bin/rt`:

  ```bash
  which rt
  ls -l ~/.local/bin/rt
  ```

- **Konfig mangler / feil sti**  
  I UI, åpne **Settings → diagnose** (viser `/api/debug-config`). Sjekk `RTOOLS_CONFIG_DIR`, og at alle forventede filer finnes. Du kan også sette:

  ```bash
  export RTOOLS_CONFIG_DIR="/home/<deg>/tools/configs"
  ```

- **Rart eierskap etter sudo-kjøring**  
  Hvis du manuelt kjørte ting med `sudo`, kan noen filer eies av root. Korriger:

  ```bash
  sudo chown -R $USER:$USER ~/tools ~/.local/bin/rt
  ```

- **Systemd starter ikke**  
  Sjekk logger:

  ```bash
  systemctl --user status rtools@8765.service
  journalctl --user -u rtools@8765.service -f
  ```

- **Pip krasj / “No module named pip.\_internal...”**  
  Oppgrader pip inne i venv med `python -m pip` (ikke `pip` fra PATH):
  ```bash
  source venv/bin/activate
  python -m pip install --upgrade pip wheel setuptools
  python -m pip install -r requirements.txt
  ```

---

## Avinstallere

```bash
# stopp user-tjeneste (hvis aktiv)
systemctl --user disable --now rtools@8765.service 2>/dev/null || true

# stopp system-tjeneste (hvis brukt)
sudo systemctl disable --now rtools.service 2>/dev/null || true

# fjern symlink
rm -f ~/.local/bin/rt

# (valgfritt) fjern repo
rm -rf ~/tools
```

---

## Tips

- Du kan sette **standard prosjekt** og **standard verktøy** i **Settings** (lagres i `global_config.json`), så åpner UI på riktig sted automatisk.
- I **Backup** kan du velge profil fra `backup_profiles.json`.
- **Statuslamper**: grønn = ok, gult pulserende = kjører, rød = feil.
- **Prosjektvelgeren** i headeren styrer hvilket prosjekt alle verktøy opererer på (via `project_root`-override til `load_config`).

---

God hacking! 🚀
