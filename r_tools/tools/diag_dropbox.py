# /home/reidar/tools/r_tools/tools/diag_dropbox.py
from __future__ import annotations
import os
from pathlib import Path
from typing import Dict, Tuple
def _robust_env() -> Dict[str, bool]:
    try:
        from dotenv import load_dotenv, dotenv_values  # type: ignore
    except Exception:
        load_dotenv = None
        dotenv_values = None
    if load_dotenv:
        try:
            load_dotenv()  # CWD
        except Exception:
            pass
        tools_env = Path(__file__).resolve().parents[2] / ".env"
        backup_env = Path(__file__).resolve().parents[1] / "backup_app" / ".env"
        home_env = Path.home() / ".env"
        for p in (tools_env, backup_env, home_env):
            if p.is_file() and dotenv_values:
                for k, v in dotenv_values(p).items():
                    if v is not None:
                        os.environ.setdefault(k, v)
    keys = ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN")
    return {k: bool(os.getenv(k)) for k in keys}
def diag_dropbox() -> Tuple[int, str]:
    have = _robust_env()
    out = []
    out.append("== Dropbox diag ==")
    out.append(
        f"APP_KEY: {have['DROPBOX_APP_KEY']}, APP_SECRET: {have['DROPBOX_APP_SECRET']}, REFRESH_TOKEN: {have['DROPBOX_REFRESH_TOKEN']}"
    )
    # ⚠️ marker hvis backup_app/.env finnes
    backup_env = Path(__file__).resolve().parents[1] / "backup_app" / ".env"
    if backup_env.is_file():
        out.append(
            f"⚠️ Fant {backup_env} – anbefales å slette/ignorere (bruk tools/.env)"
        )
    missing = [k for k, v in have.items() if not v]
    if missing:
        out.append("Mangler nøkler: " + ", ".join(missing))
        return 2, "\n".join(out) + "\n"
    try:
        from dropbox import Dropbox  # type: ignore
        dbx = Dropbox(
            oauth2_refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
            app_key=os.environ["DROPBOX_APP_KEY"],
            app_secret=os.environ["DROPBOX_APP_SECRET"],
        )
        acct = dbx.users_get_current_account()
        out.append(f"Account OK: {acct.name.display_name} ({acct.account_id})")
        return 0, "\n".join(out) + "\n"
    except Exception as e:
        out.append(f"API-sjekk feilet: {e}")
        return 3, "\n".join(out) + "\n"
