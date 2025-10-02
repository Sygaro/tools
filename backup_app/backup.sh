#!/usr/bin/env bash
set -euo pipefail

# Finn virkelig skriptplassering selv om dette scriptet er en symlink.
resolve_script_dir() {
  local SOURCE="${BASH_SOURCE[0]}"
  while [ -L "$SOURCE" ]; do
    local TARGET
    TARGET="$(readlink "$SOURCE")"
    if [[ "$TARGET" == /* ]]; then
      SOURCE="$TARGET"
    else
      local DIR
      DIR="$(cd -P "$(dirname "$SOURCE")" && pwd)"
      SOURCE="$DIR/$TARGET"
    fi
  done
  cd -P "$(dirname "$SOURCE")" && pwd
}

SCRIPT_DIR="$(resolve_script_dir)"
PY="$SCRIPT_DIR/venv/bin/python"

if [[ ! -x "$PY" ]]; then
  echo "Fant ikke venv på $PY"
  echo "Tips: cd $SCRIPT_DIR && python -m venv venv && source venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

exec "$PY" "$SCRIPT_DIR/backup.py" "$@"
