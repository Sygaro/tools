# backup\_app

Fleksibel backup av valgfri katalog, med valgfritt prosjektnavn, valgfri versjon, **.backupignore/--exclude**, **retention** og valgfri **Dropbox-opplasting**.

## Endringer (v2)

- **Home-baserte stier**:
  - `--source countdown` betyr nå `~/countdown` (ikke relativt til repoet).
  - `--dest backups` betyr nå `~/backups` (med mindre du oppgir en absolutt sti som starter med `/`).
- **Ny standard destinasjon**: `~/backups` i stedet for `./backups` i repoet.
- **Forbedret ignorering**:
  - Standard utelatelser gjelder overalt i treet: `venv`, `.venv`, `.git`, `node_modules`, `__pycache__`, `dist`, `build`, `backups`, samt filer `*.pyc`, `*.pyo`, `*.log`, `*.tmp`.
  - `--exclude` og `.backupignore` kan i tillegg brukes.

## Installasjon

```bash
sudo apt update && sudo apt install -y git python3-venv
git clone https://github.com/Sygaro/backup_app
cd backup_app
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

> **Dropbox (valgfritt):**
>
> 1. Opprett token: [https://www.dropbox.com/developers/apps](https://www.dropbox.com/developers/apps)
> 2. Kopiér miljømal og sett token:
>    ```bash
>    cp env_mal .env
>    nano .env   # sett DROPBOX_TOKEN=...
>    ```

## Bruk

> Merk: Kortflagg – `-v` = verbose (mer logging), `-V` = version (f.eks. `-V 1.10`).

**Standard ZIP-backup uten versjon (dato i navn):**

```bash
./backup.sh --source countdown --project countdown
```

Dette vil pakke `~/countdown` og lagre i `~/backups`.

**Med versjon og tag:**

```bash
./backup.sh --source countdown --project countdown \
  --version 1.10 --tag Frontend_OK
```

**Ekskludering og skjulte filer:**

```bash
./backup.sh --source countdown --project countdown \
  --exclude "*.env" --include-hidden
```

> Standard-utestengte mapper (venv/.venv/.git/node\_modules/**pycache**/dist/build/backups) ekskluderes uansett hvor de ligger i treet.

**Retention (behold kun 10 siste):**

```bash
./backup.sh --source countdown --project countdown --keep 10
```

**Dropbox-opplasting (krever **``**):**

```bash
./backup.sh --source countdown --project countdown \
  --version 1.11 --dropbox-path "/Apps/backup_app/countdown"
```

**Tar.gz i stedet for ZIP:**

```bash
./backup.sh --source countdown --project countdown --format tar.gz
```

**Tørrkjøring:**

```bash
./backup.sh --source countdown --project countdown --dry-run
```

## Filnavn

```
{project}[_v{versjon}]_{YYYYMMDD-HHMM}[_tag].zip
```

Det lages også en symlink `{project}_latest` der det er støttet.

## .backupignore

Legg `.backupignore` i roten av kilden for å ekskludere tilleggsmønstre:

```
# Ekstra eksempel
*.sqlite
.env
coverage/*
```

> Standard-utelukkelser gjelder alltid: `venv`, `.venv`, `.git`, `node_modules`, `__pycache__`, `dist`, `build`, `backups`, `*.pyc`, `*.pyo`, `*.log`, `*.tmp`.

## Miljø

- `DROPBOX_TOKEN` – kreves for Dropbox-opplasting (leses også fra `.env`).
- `BACKUP_DEFAULT_DEST` – valgfritt: overstyr standard destinasjon (default `~/backups`).

