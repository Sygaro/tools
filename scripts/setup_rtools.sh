#!/usr/bin/env bash
set -euo pipefail

# ───────────── colors & helpers ─────────────
if command -v tput >/dev/null 2>&1; then
  T_BLUE="$(tput setaf 4)"; T_GREEN="$(tput setaf 2)"; T_YELLOW="$(tput setaf 3)"; T_RED="$(tput setaf 1)"; T_DIM="$(tput dim)"; T_BOLD="$(tput bold)"; T_RESET="$(tput sgr0)"
else
  T_BLUE=""; T_GREEN=""; T_YELLOW=""; T_RED=""; T_DIM=""; T_BOLD=""; T_RESET=""
fi
info(){ printf "${T_BLUE}ℹ${T_RESET}  %s\n" "$*"; }
ok(){   printf "${T_GREEN}✓${T_RESET}  %s\n" "$*"; }
warn(){ printf "${T_YELLOW}⚠${T_RESET}  %s\n" "$*"; }
err(){  printf "${T_RED}✗${T_RESET}  %s\n" "$*" >&2; }
ask_yn(){ local q="$1" def="${2:-y}" ans; local hint=$([ "$def" = y ] && echo "${T_DIM}[${T_BOLD}Y${T_RESET}${T_DIM}/n]${T_RESET}" || echo "${T_DIM}[y/${T_BOLD}N${T_RESET}${T_DIM}]${T_RESET}"); read -r -p "$(printf "%s %b " "$q" "$hint")" ans || true; ans="${ans:-$def}"; [[ "${ans,,}" == "y" ]]; }
ask_in(){ local q="$1" def="${2:-}"; read -r -p "$(printf "%s %b " "$q" "${T_DIM}(Enter=${def})${T_RESET}")" ans || true; echo "${ans:-$def}"; }

# ───────────── require sudo ─────────────
if [[ "${EUID}" -ne 0 || -z "${SUDO_USER:-}" ]]; then
  err "Kjør med sudo: ${T_BOLD}sudo bash scripts/setup_rtools.sh${T_RESET}"
  exit 1
fi

USER_NAME="${SUDO_USER}"
USER_HOME="$(getent passwd "$USER_NAME" | cut -d: -f6)"
[[ -d "$USER_HOME" ]] || { err "Fant ikke hjemmekatalog for $USER_NAME"; exit 1; }
USER_SHELL="$(getent passwd "$USER_NAME" | cut -d: -f7)"

as_user() { sudo -u "$USER_NAME" -H bash -lc "$*"; }

# ---------- sanity ----------
command -v python3 >/dev/null || { err "python3 mangler (sudo apt-get install -y python3 python3-venv)"; exit 1; }
command -v curl >/dev/null || warn "curl mangler – anbefalt for diagnose."


# ───────────── paths ─────────────
if [[ -f "./requirements.txt" && -d "./r_tools" ]]; then
  TOOLS_DIR="$(pwd)"
else
  TOOLS_DIR="$(ask_in "Sti til 'tools'-repo" "$USER_HOME/tools")"
fi
[[ -d "$TOOLS_DIR" ]] || { err "Katalog finnes ikke: $TOOLS_DIR"; exit 1; }

VENV_DIR="$TOOLS_DIR/venv"
CONFIG_DIR="$TOOLS_DIR/configs"
ENV_DIR="$USER_HOME/.config/rtools"
ENV_FILE="$ENV_DIR/env"
SERVICE_PATH="/etc/systemd/system/rtools.service"
PORT_DEFAULT="8765"

info "Installerer for ${T_BOLD}$USER_NAME${T_RESET} i ${T_BOLD}$TOOLS_DIR${T_RESET}"
install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$ENV_DIR"

# ───────────── optional deps (root) ─────────────
if ! command -v jq >/dev/null 2>&1; then
  if ask_yn "Installere 'jq' (for å skrive JSON)?" y; then
    apt-get update -y && apt-get install -y jq
  else
    warn "jq mangler – bruker enkel fallback for JSON."
  fi
fi
if ! dpkg -s python3-venv >/dev/null 2>&1; then
  if ask_yn "Installere 'python3-venv'?" y; then
    apt-get update -y && apt-get install -y python3-venv
  else
    err "python3-venv mangler – kan ikke lage virtuellenv."; exit 1
  fi
fi

# ───────────── venv + deps (as user) ─────────────
if [[ ! -d "$VENV_DIR" ]]; then
  info "Lager venv (eies av $USER_NAME)…"
  as_user "python3 -m venv '$VENV_DIR'"
  ok "Venv opprettet: $VENV_DIR"
fi

info "Oppgraderer pip/setuptools/wheel…"
as_user "'$VENV_DIR/bin/python' -m pip install --upgrade pip setuptools wheel >/dev/null"
ok "pip/setuptools/wheel oppdatert"

if [[ -f "$TOOLS_DIR/requirements.txt" ]]; then
  info "Installerer avhengigheter fra requirements.txt…"
  as_user "'$VENV_DIR/bin/python' -m pip install -r '$TOOLS_DIR/requirements.txt'"
  ok "Avhengigheter installert."
else
  warn "Fant ikke requirements.txt – hopper over."
fi

# ───────────── shell-miljø for bruker ─────────────
BASHRC="$USER_HOME/.bashrc"
info "Oppdaterer ${T_BOLD}$BASHRC${T_RESET} (PATH + RTOOLS_CONFIG_DIR)…"
if ! grep -q 'RTOOLS_CONFIG_DIR=' "$BASHRC" 2>/dev/null; then
  {
    echo ""
    echo "# r_tools"
    echo "export RTOOLS_CONFIG_DIR=\"$CONFIG_DIR\""
    echo "export PATH=\"$VENV_DIR/bin:\$PATH\""
  } >> "$BASHRC"
  chown "$USER_NAME":"$USER_NAME" "$BASHRC"
  ok "Miljøvariabler lagt til i .bashrc (åpne ny terminal for effekt)."
else
  ok "RTOOLS_CONFIG_DIR finnes allerede i .bashrc."
fi
# ───────────── rt-kommando ─────────────
# ───────────── Bruk prosjektets bin/rt ─────────────
RT_PROJECT="$TOOLS_DIR/bin/rt"

if [[ ! -x "$RT_PROJECT" ]]; then
  if [[ -f "$RT_PROJECT" ]]; then
    chmod +x "$RT_PROJECT"
  else
    echo "✗ Fant ikke $RT_PROJECT. Sørg for at repoet inneholder bin/rt." >&2
    exit 1
  fi
fi

# Lag bruker-lokal symlink ~/.local/bin/rt -> $TOOLS_DIR/bin/rt
USER_LOCAL_BIN="$USER_HOME/tools/bin"
install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$USER_LOCAL_BIN"

RT_LINK="$USER_LOCAL_BIN/rt"

# Tilby system-wide symlink (valgfritt)
if ask_yn "Opprette system-wide symlink /usr/local/bin/rt også?" y; then
  ln -sf "$RT_SHIM" /usr/local/bin/rt
  ok "Laget /usr/local/bin/rt → $RT_SHIM"
fi

# ───────────── configs: sjekk & evt. generer (as root, deretter chown) ─────────────
NEEDED=( projects_config.json recipes_config.json search_config.json paste_config.json format_config.json clean_config.json gh_raw_config.json global_config.json backup_config.json backup_profiles.json )
MISSING=()
for f in "${NEEDED[@]}"; do
  [[ -f "$CONFIG_DIR/$f" ]] || MISSING+=("$f")
done

create_configs(){
  install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$CONFIG_DIR"
  cat > "$CONFIG_DIR/backup_config.json" <<'JSON'
{
  "backup": {
    "script": "backup_app/backup.py",
    "defaults": { "format": "zip", "verbose": true }
  }
}
JSON
  cat > "$CONFIG_DIR/backup_profiles.json" <<'JSON'
{
  "default": "countdown",
  "profiles": {
    "countdown": { "project": "countdown", "source": "countdown", "keep": 200, "format": "zip",
      "dropbox_path": "/Apps/backup_app/countdown", "exclude": ["*.env"], "include_hidden": false,
      "no_verify": false, "dry_run": false, "verbose": true },
    "r_tools": { "project": "r_tools", "source": "tools", "keep": 200, "format": "zip",
      "dropbox_path": "/Apps/backup_app/r_tools", "exclude": ["*.env"], "include_hidden": false,
      "no_verify": false, "dry_run": false, "verbose": true }
  }
}
JSON
  cat > "$CONFIG_DIR/clean_config.json" <<'JSON'
{
  "clean": {
    "enable": true,
    "targets": {
      "build": true, "coverage": true, "dist": true, "ds_store": true,
      "editor": true, "mypy_cache": true, "node_modules": false,
      "pycache": true, "pytest_cache": true, "ruff_cache": false, "thumbs_db": true
    },
    "extra_globs": ["._.DS_Store"],
    "skip_globs": []
  }
}
JSON
  cat > "$CONFIG_DIR/format_config.json" <<'JSON'
{
  "format": {
    "prettier": { "enable": true, "globs": ["**/*.{html,css,js}"] },
    "black":    { "enable": true, "paths": ["./"] },
    "ruff":     { "enable": true, "args": ["check", "./", "--fix"] },
    "cleanup": {
      "enable": true,
      "paths": [],
      "exts": [".py", ".js", ".ts", ".css", ".html", ".json", ".sh"],
      "exclude_exts": [".md","venv/"],
      "compact_blocks": true,
      "max_consecutive_blanks": 0
    }
  }
}
JSON
  cat > "$CONFIG_DIR/gh_raw_config.json" <<'JSON'
{ "gh_raw": { "user": "Sygaro", "repo": "countdown", "branch": "main", "path_prefix": "" } }
JSON
  cat > "$CONFIG_DIR/global_config.json" <<'JSON'
{
  "project_root": ".",
  "include_extensions": [ ".py",".sh",".c",".cpp",".h",".js",".ts",".css",".html" ],
  "exclude_dirs": [ "__pycache__","build",".git","node_modules","venv" ],
  "exclude_files": [ "._.DS_Store" ],
  "case_insensitive": true,
  "default_project": "/home/reidar/countdown",
  "default_tool": "search"
}
JSON
  cat > "$CONFIG_DIR/paste_config.json" <<'JSON'
{
  "paste": {
    "root": ".",
    "out_dir": "paste_out",
    "max_lines": 4000,
    "allow_binary": false,
    "filename_search": true,
    "include": ["r_tools/tools/webui.py"],
    "exclude": ["**/.git/**","**/venv/**","**/node_modules/**","**/__pycache__/**","**/.pytest_cache/**","**/.mypy_cache/**","._.DS_Store",".DS_Store"],
    "only_globs": [],
    "skip_globs": []
  }
}
JSON
  cat > "$CONFIG_DIR/projects_config.json" <<'JSON'
{
  "projects": [
    { "name": "countdown", "path": "/home/reidar/countdown" },
    { "name": "tools",     "path": "/home/reidar/tools" }
  ]
}
JSON
  cat > "$CONFIG_DIR/recipes_config.json" <<'JSON'
{
  "recipes": [
    { "name": "Search: finn import os + class", "tool": "search", "desc": "AND-søk etter import og class på samme linje",
      "args": { "terms": ["import\\s+os", "\\bclass\\b"], "all": true, "max_size": 2000000 } },
    { "name": "Paste: python + md", "tool": "paste", "desc": "Globalt filnavn-søk på README.md og alle .py",
      "args": { "filename_search": true, "include": ["**/*.py", "README.md"], "exclude": ["**/.git/**","**/venv/**"], "max_lines": 4000 } },
    { "name": "Format: dry-run", "tool": "format", "desc": "Kjør formattere og cleanup uten å skrive", "args": { "dry_run": true } },
    { "name": "Clean: pycache+ruff (dry)", "tool": "clean", "desc": "Rydd cache trygt (dry-run)", "args": { "what": ["pycache", "ruff_cache"], "dry_run": true } },
    { "name": "GH Raw: routes", "tool": "gh-raw", "desc": "List raw-URLer under app/routes", "args": { "path_prefix": "app/routes" } }
  ]
}
JSON
  cat > "$CONFIG_DIR/search_config.json" <<'JSON'
{ "search_terms": ["\\bTODO\\b", "\\bFIXME\\b"] }
JSON

  chown -R "$USER_NAME":"$USER_NAME" "$CONFIG_DIR"
}

if (( ${#MISSING[@]} )); then
  warn "Mangler config-filer i $CONFIG_DIR:"
  printf ' - %s\n' "${MISSING[@]}"
  if ask_yn "Opprette manglende filer med standardverdier?" y; then
    create_configs
    ok "Config-filer opprettet og satt eierskap til $USER_NAME."
  fi
else
  ok "Alle forventede config-filer finnes."
  chown -R "$USER_NAME":"$USER_NAME" "$CONFIG_DIR" || true
fi

# ───────────── interaktive innstillinger (as user for jq moves) ─────────────
if ask_yn "Sette default project nå?" n; then
  DEF_PROJ="$(ask_in "Absolutt sti til prosjekt" "$USER_HOME/countdown")"
  if command -v jq >/dev/null 2>&1 && [[ -f "$CONFIG_DIR/global_config.json" ]]; then
    as_user "jq -S --arg dp '$DEF_PROJ' '.default_project=\$dp | .default_tool = (.default_tool // \"search\")' '$CONFIG_DIR/global_config.json' > '$CONFIG_DIR/global_config.json.tmp'"
    mv "$CONFIG_DIR/global_config.json.tmp" "$CONFIG_DIR/global_config.json"
  else
    echo "{\"default_project\":\"$DEF_PROJ\",\"default_tool\":\"search\"}" > "$CONFIG_DIR/global_config.json"
  fi
  chown "$USER_NAME":"$USER_NAME" "$CONFIG_DIR/global_config.json"
  ok "Default project satt: $DEF_PROJ"
fi

if ask_yn "Sette default tool (search/paste/format/clean/gh-raw/backup)?" n; then
  DEF_TOOL="$(ask_in "Tool" "search")"
  if command -v jq >/dev/null 2>&1 && [[ -f "$CONFIG_DIR/global_config.json" ]]; then
    as_user "jq -S --arg dt '$DEF_TOOL' '.default_tool=\$dt | .default_project = (.default_project // \"$USER_HOME/countdown\")' '$CONFIG_DIR/global_config.json' > '$CONFIG_DIR/global_config.json.tmp'"
    mv "$CONFIG_DIR/global_config.json.tmp" "$CONFIG_DIR/global_config.json"
  else
    echo "{\"default_project\":\"$USER_HOME/countdown\",\"default_tool\":\"$DEF_TOOL\"}" > "$CONFIG_DIR/global_config.json"
  fi
  chown "$USER_NAME":"$USER_NAME" "$CONFIG_DIR/global_config.json"
  ok "Default tool satt: $DEF_TOOL"
fi

if ask_yn "Oppdatere sti til backup.py i backup_config.json?" n; then
  BK_SCRIPT="$(ask_in "Sti til backup.py" "$TOOLS_DIR/backup_app/backup.py")"
  if command -v jq >/dev/null 2>&1 && [[ -f "$CONFIG_DIR/backup_config.json" ]]; then
    as_user "jq -S --arg p '$BK_SCRIPT' '.backup.script=\$p' '$CONFIG_DIR/backup_config.json' > '$CONFIG_DIR/backup_config.json.tmp'"
    mv "$CONFIG_DIR/backup_config.json.tmp" "$CONFIG_DIR/backup_config.json"
  else
    echo "{\"backup\":{\"script\":\"$BK_SCRIPT\"}}" > "$CONFIG_DIR/backup_config.json"
  fi
  chown "$USER_NAME":"$USER_NAME" "$CONFIG_DIR/backup_config.json"
  ok "backup_config.json oppdatert."
fi


# ───────────── Dropbox wizard (as user) ─────────────
import_env_lines(){
  local f="$1"
  [[ -f "$f" ]] || return 1
  grep -E '^(DROPBOX_APP_KEY|DROPBOX_APP_SECRET|DROPBOX_REFRESH_TOKEN)=' "$f" || return 2
  install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$ENV_DIR"
  grep -E '^(DROPBOX_APP_KEY|DROPBOX_APP_SECRET|DROPBOX_REFRESH_TOKEN)=' "$f" > "$ENV_FILE"
  chown "$USER_NAME":"$USER_NAME" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  ok "Importerte Dropbox-nøkler fra $f → $ENV_FILE"
}

if ask_yn "Kjøre Dropbox-wizard nå for å sette APP_KEY/SECRET/REFRESH_TOKEN?" n; then
  if [[ -f "$TOOLS_DIR/r_tools/tools/backup_wizard.py" ]]; then
    info "Starter backup_wizard… (følg instruksjonene)"
    as_user "cd '$TOOLS_DIR' && '$VENV_DIR/bin/python' -m r_tools.tools.backup_wizard" || warn "Wizard returnerte ikke-null."
  elif [[ -f "$TOOLS_DIR/extra/dropbox_get_refresh_token.py" ]]; then
    info "Starter extra/dropbox_get_refresh_token.py…"
    as_user "cd '$TOOLS_DIR' && '$VENV_DIR/bin/python' 'extra/dropbox_get_refresh_token.py'" || warn "Wizard returnerte ikke-null."
  else
    warn "Fant ikke wizard i repo."
  fi

  for CAND in "$TOOLS_DIR/.env" "$USER_HOME/.env" "$TOOLS_DIR/backup_app/.env"; do
    if [[ -f "$CAND" ]] && grep -q 'DROPBOX_REFRESH_TOKEN=' "$CAND"; then
      import_env_lines "$CAND" && break
    fi
  done

  if [[ ! -f "$ENV_FILE" ]] && ask_yn "Vil du lime inn nøkler nå og lagre til $ENV_FILE?" y; then
    read -r -p "DROPBOX_APP_KEY: " DBX_APP_KEY || true
    read -r -p "DROPBOX_APP_SECRET: " DBX_APP_SECRET || true
    install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$ENV_DIR"
    {
      echo "DROPBOX_APP_KEY=${DBX_APP_KEY:-}"
      echo "DROPBOX_APP_SECRET=${DBX_APP_SECRET:-}"
      echo "DROPBOX_REFRESH_TOKEN=${DBX_REFRESH:-}"
    } > "$ENV_FILE"
    chown "$USER_NAME":"$USER_NAME" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok "Lagret Dropbox-nøkler i $ENV_FILE"
  fi
fi

# ───────────── Port ─────────────
PORT="$(ask_in "Port for UI" "$PORT_DEFAULT")"

# ───────────── systemd (valg) ─────────────
if ask_yn "Opprette og starte systemd-tjenesten for r_tools UI nå?" y; then
  info "Oppretter systemd-service (rtools) på port $PORT"
  cat > "$SERVICE_PATH" <<UNIT
[Unit]
Description=r_tools UI (uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER_NAME
Group=$USER_NAME
WorkingDirectory=$TOOLS_DIR
Environment=RTOOLS_CONFIG_DIR=$CONFIG_DIR
EnvironmentFile=-$ENV_FILE
ExecStart=$VENV_DIR/bin/python -m uvicorn r_tools.tools.webui:app --host 0.0.0.0 --port $PORT
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable --now rtools || { err "Kunne ikke starte/enable systemd-tjenesten. Se 'journalctl -u rtools -e'."; exit 1; }
  ok "Systemd-tjenesten 'rtools' er aktiv."
else
  info "Du kan starte UI manuelt slik:"
  echo "  ${T_BOLD}cd '$TOOLS_DIR' && '$VENV_DIR/bin/python' -m uvicorn r_tools.tools.webui:app --host 0.0.0.0 --port $PORT${T_RESET}"
fi

# ───────────── sørg for riktig eierskap på alt vi kan ha endret ─────────────
chown -R "$USER_NAME":"$USER_NAME" "$VENV_DIR" "$CONFIG_DIR" "$ENV_DIR" 2>/dev/null || true

# ───────────── summary ─────────────
cat <<EOF

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
${T_GREEN}✅ Ferdig!${T_RESET}

• Repo:            $TOOLS_DIR
• Venv:            $VENV_DIR  ${T_DIM}(eier: $USER_NAME)${T_RESET}
• Config-dir:      $CONFIG_DIR  ${T_DIM}(eier: $USER_NAME)${T_RESET}
• UI-port:         $PORT
• Systemd-unit:    $SERVICE_PATH ${T_DIM}(root)${T_RESET}
• Kjører som:      $USER_NAME

Nyttig:
  - Sjekk status:     ${T_BOLD}systemctl status rtools${T_RESET}
  - Live logger:      ${T_BOLD}journalctl -u rtools -f${T_RESET}
  - URL:              ${T_BOLD}http://<din-ip>:$PORT${T_RESET}
  - Aktiver CLI env:  åpne ny terminal (eller ${T_BOLD}source $USER_HOME/.bashrc${T_RESET})
EOF
