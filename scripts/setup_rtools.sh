#!/usr/bin/env bash
set -euo pipefail

# ----------------------- Visuelle helpers -----------------------
C_RESET="\033[0m"; C_DIM="\033[2m"; C_BOLD="\033[1m"
C_BLUE="\033[34m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"; C_RED="\033[31m"

log()   { echo -e "${C_DIM}[$(date +%H:%M:%S)]${C_RESET} $*"; }
info()  { echo -e "${C_BLUE}ℹ${C_RESET}  $*"; }
ok()    { echo -e "${C_GREEN}✓${C_RESET}  $*"; }
warn()  { echo -e "${C_YELLOW}⚠${C_RESET}  $*"; }
err()   { echo -e "${C_RED}✗${C_RESET}  $*"; }
ask()   { echo -ne "${C_BOLD}?${C_RESET}  $* "; }

confirm () {
  local prompt="${1:-Vil du fortsette? [y/N]}"; local ans
  read -r -p "$prompt " ans || true
  case "${ans,,}" in y|yes) return 0 ;; *) return 1 ;; esac
}

# ----------------------- Kataloger/variabler -----------------------
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$REPO_DIR"
VENV_DIR="$REPO_DIR/venv"
PY="$VENV_DIR/bin/python"
PIP="$VENV_DIR/bin/pip"
UVICORN="$VENV_DIR/bin/uvicorn"

CONFIG_DIR_DEFAULT="$REPO_DIR/configs"
RTOOLS_CONFIG_DIR="${RTOOLS_CONFIG_DIR:-$CONFIG_DIR_DEFAULT}"  # kan overstyres via env

# ----------------------- Trinn 0: Forhåndssjekker -----------------------
info "Repo: $REPO_DIR"
info "Config-katalog (RTOOLS_CONFIG_DIR): $RTOOLS_CONFIG_DIR"

PY_MIN="3.10"
if command -v python3 >/dev/null 2>&1; then
  PY_SYS_VER="$(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
  info "System Python: $PY_SYS_VER"
else
  err "python3 mangler. Installer først (e.g. sudo apt-get install -y python3)."
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  warn "curl mangler – anbefalt for lokal diagnose."
fi

# ----------------------- Trinn 1: Venv -----------------------
if [[ ! -x "$PY" ]]; then
  info "Oppretter virtualenv i $VENV_DIR"
  python3 -m venv "$VENV_DIR"
  ok "Venv opprettet."
else
  ok "Venv finnes allerede."
fi

info "Oppgraderer pip/wheel og installerer avhengigheter…"
"$PIP" install -U pip wheel >/dev/null
"$PIP" install -r "$REPO_DIR/requirements.txt"
ok "Python-avhengigheter installert."

# ----------------------- Trinn 2: Miljøvariabler (~/.bashrc) -----------------------
BASHRC="$HOME/.bashrc"
ensure_line () {
  local line="$1"
  grep -Fqx "$line" "$BASHRC" 2>/dev/null || echo "$line" >> "$BASHRC"
}

info "Sørger for at venv havner på PATH og at RTOOLS_CONFIG_DIR er satt i $BASHRC"
ensure_line "export PATH=\"$VENV_DIR/bin:\$PATH\""
ensure_line "export RTOOLS_CONFIG_DIR=\"$RTOOLS_CONFIG_DIR\""
ok "Miljøvariabler lagt inn i $BASHRC (ny terminal for å ta effekt)."

# ----------------------- Trinn 3: Grunn-konfig sanity -----------------------
CONFIG_FILES=(
  "projects_config.json"
  "global_config.json"
  "backup_config.json"
  "backup_profiles.json"
  "search_config.json"
  "paste_config.json"
  "format_config.json"
  "clean_config.json"
  "gh_raw_config.json"
  "recipes_config.json"
)
MISSING=()
for f in "${CONFIG_FILES[@]}"; do
  [[ -f "$RTOOLS_CONFIG_DIR/$f" ]] || MISSING+=("$f")
done

if (( ${#MISSING[@]} )); then
  warn "Fant ikke følgende config-filer i $RTOOLS_CONFIG_DIR:"
  for m in "${MISSING[@]}"; do echo "  - $m"; done
  if confirm "Vil du kopiere standardfiler fra repoets configs/? [y/N]"; then
    for m in "${MISSING[@]}"; do
      if [[ -f "$CONFIG_DIR_DEFAULT/$m" ]]; then
        mkdir -p "$RTOOLS_CONFIG_DIR"
        cp -n "$CONFIG_DIR_DEFAULT/$m" "$RTOOLS_CONFIG_DIR/$m"
        ok "Kopierte $m"
      else
        warn "Manglet mal i repo for $m (hopper over)."
      fi
    done
  else
    warn "Fortsetter uten å kopiere – UI kan klage på manglende config."
  fi
else
  ok "Alle forventede config-filer finnes."
fi

# ----------------------- Trinn 4: Valgfrie innstillinger -----------------------
DEFAULT_PROJECT_JSON="$RTOOLS_CONFIG_DIR/global_config.json"
DEFAULT_TOOL="search"

set_json_value () {
  # Bruker embedded Python for robust JSON-oppdatering
  local file="$1" key="$2" value="$3"
  "$PY" - "$file" "$key" "$value" <<'PY'
import json,sys,os
p,key,val=sys.argv[1],sys.argv[2],sys.argv[3]
data={}
if os.path.isfile(p):
    try: data=json.load(open(p,encoding="utf-8"))
    except Exception: data={}
data[key]=None if val in ("", "null", "None") else val
with open(p,"w",encoding="utf-8") as f:
    json.dump(data,f,indent=2,ensure_ascii=False); f.write("\n")
PY
}

# Foreslå default_project fra projects_config.json hvis mulig
SUGGEST_DEFAULT_PROJECT="$("$PY" - <<PY
import json,sys,os
cfg=os.environ.get("RTOOLS_CONFIG_DIR")
pp=os.path.join(cfg,"projects_config.json")
try:
    pr=json.load(open(pp,encoding="utf-8")).get("projects",[])
    for p in pr:
        ap=p.get("path")
        if ap and os.path.exists(ap):
            print(ap); break
except Exception: pass
PY
)"

info "Konfigurer noen grunninnstillinger:"
ask "Sett default project nå? (Enter for forslag: ${SUGGEST_DEFAULT_PROJECT:-ingen}) [y/N]"
read -r A || true
if [[ "${A,,}" =~ ^y(es)?$ ]]; then
  ask "Skriv full sti til default project: "
  read -r DP || true
  DP="${DP:-$SUGGEST_DEFAULT_PROJECT}"
  if [[ -n "$DP" ]]; then
    set_json_value "$DEFAULT_PROJECT_JSON" "default_project" "$DP"
    ok "Default project satt til: $DP"
  else
    warn "Hoppet over default project."
  fi
fi

ask "Sett default tool (search/paste/format/clean/gh-raw/backup)? [y/N]"
read -r A || true
if [[ "${A,,}" =~ ^y(es)?$ ]]; then
  ask "Skriv verktøy (tom = ingen, standard=$DEFAULT_TOOL): "
  read -r DT || true
  DT="${DT:-$DEFAULT_TOOL}"
  set_json_value "$DEFAULT_PROJECT_JSON" "default_tool" "$DT"
  ok "Default tool satt til: $DT"
fi

# backup.py-sti i backup_config.json
if [[ -f "$RTOOLS_CONFIG_DIR/backup_config.json" ]]; then
  CURRENT_SCRIPT="$("$PY" - <<PY
import json,os
p=os.environ["RTOOLS_CONFIG_DIR"]+"/backup_config.json"
try:
  j=json.load(open(p,encoding="utf-8"))
  print((j.get("backup") or {}).get("script") or "")
except Exception: print("")
PY
)"
  SUGGEST_BK="$REPO_DIR/backup_app/backup.py"
  ask "Vil du oppdatere sti til backup.py? (nå: ${CURRENT_SCRIPT:-ikke satt}) [y/N]"
  read -r A || true
  if [[ "${A,,}" =~ ^y(es)?$ ]]; then
    ask "Sti til backup.py (Enter for forslag $SUGGEST_BK): "
    read -r BK || true
    BK="${BK:-$SUGGEST_BK}"
    "$PY" - <<PY
import json,os,sys
cfg=os.environ["RTOOLS_CONFIG_DIR"]+"/backup_config.json"
data=json.load(open(cfg,encoding="utf-8")) if os.path.isfile(cfg) else {}
data.setdefault("backup",{})["script"]=os.path.abspath("$BK")
with open(cfg,"w",encoding="utf-8") as f: json.dump(data,f,indent=2,ensure_ascii=False); f.write("\n")
PY
    ok "backup_config.json oppdatert."
  fi
fi

# Valgfritt: Dropbox env
ask "Vil du sette Dropbox env-variabler (APP_KEY/APP_SECRET/REFRESH_TOKEN) i ~/.bashrc nå? [y/N]"
read -r A || true
if [[ "${A,,}" =~ ^y(es)?$ ]]; then
  read -r -p "DROPBOX_APP_KEY: " DBX_APP || true
  read -r -p "DROPBOX_APP_SECRET: " DBX_SEC || true
  read -r -p "DROPBOX_REFRESH_TOKEN: " DBX_REF || true
  [[ -n "${DBX_APP:-}" ]] && ensure_line "export DROPBOX_APP_KEY=\"$DBX_APP\""
  [[ -n "${DBX_SEC:-}" ]] && ensure_line "export DROPBOX_APP_SECRET=\"$DBX_SEC\""
  [[ -n "${DBX_REF:-}" ]] && ensure_line "export DROPBOX_REFRESH_TOKEN=\"$DBX_REF\""
  ok "Dropbox-variabler lagt til i $BASHRC"
fi

# ----------------------- Trinn 5: Starte UI (systemd? manuelt?) -----------------------
DEFAULT_PORT=8765
ask "Hvilken port skal UI bruke? (Enter=$DEFAULT_PORT):"
read -r PORT || true
PORT="${PORT:-$DEFAULT_PORT}"

if confirm "Vil du kjøre r_tools UI som systemd-tjeneste? [y/N]"; then
  SERVICE_NAME="rtools"
  SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
  RUN_USER="$(id -un)"
  info "Setter opp systemd-tjeneste som bruker '$RUN_USER' på port $PORT"

  SERVICE_CONTENT="[Unit]
Description=r_tools UI
After=network.target

[Service]
User=${RUN_USER}
WorkingDirectory=${REPO_DIR}
Environment=\"RTOOLS_CONFIG_DIR=${RTOOLS_CONFIG_DIR}\"
ExecStart=${UVICORN} r_tools.tools.webui:app --host 0.0.0.0 --port ${PORT}
Restart=always
RestartSec=3
KillSignal=SIGINT
TimeoutStopSec=10

[Install]
WantedBy=multi-user.target
"

  if [[ $EUID -ne 0 ]]; then
    info "Skriver midlertidig service-fil til /tmp og bruker sudo for installasjon…"
    TMPF="$(mktemp)"
    echo "$SERVICE_CONTENT" > "$TMPF"
    sudo mv "$TMPF" "$SERVICE_FILE"
    sudo chown root:root "$SERVICE_FILE"
  else
    echo "$SERVICE_CONTENT" > "$SERVICE_FILE"
  fi

  sudo systemctl daemon-reload
  sudo systemctl enable --now "$SERVICE_NAME"
  sleep 1
  if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "Tjenesten '$SERVICE_NAME' kjører."
  else
    err "Tjenesten startet ikke. Sjekk: sudo journalctl -u $SERVICE_NAME -f"
  fi
else
  warn "Starter ikke som systemd-tjeneste."
  if confirm "Starte UI nå i bakgrunnen (nohup)? [y/N]"; then
    nohup "$UVICORN" r_tools.tools.webui:app --host 0.0.0.0 --port "$PORT" --log-level info >/tmp/rtools-ui.log 2>&1 &
    sleep 1
    ok "UI startet i bakgrunnen (logg: /tmp/rtools-ui.log)."
  else
    info "Du kan starte manuelt senere med:"
    echo "  $UVICORN r_tools.tools.webui:app --host 0.0.0.0 --port $PORT --log-level info"
  fi
fi

# ----------------------- Trinn 6: Diagnose og sluttmelding -----------------------
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
URL="http://${IP:-127.0.0.1}:$PORT"

info "Kjapp diagnose:"
if command -v curl >/dev/null 2>&1; then
  if curl -fsS "$URL/api/debug-config" >/dev/null; then
    ok "UI svarer på $URL"
  else
    warn "Kunne ikke nå $URL akkurat nå. Tjenesten kan bruke noen sekunder på å starte."
  fi
else
  warn "curl mangler; hoppet over HTTP-sjekk."
fi

echo
ok "Oppsett ferdig!"
echo "• Åpne UI:  $URL"
echo "• Ta evt. en ny shell for at endringer i ~/.bashrc skal tre i kraft."
echo "• Diagnose i UI: Settings → diagnose."
echo
