# ./tools/r_tools/tools/backup_wizard.py
from __future__ import annotations

import os
import stat
from pathlib import Path

def _tools_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _env_path() -> Path:
    # Lagre på repo-roten (tools/.env)
    return _tools_root() / ".env"

def _load_existing_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip()
    return out

def _write_env(path: Path, kv: dict[str, str]) -> None:
    # Slå sammen med eksisterende, oppdater kun aktuelle
    existing = _load_existing_env(path)
    existing.update(kv)
    lines = [f"{k}={existing[k]}\n" for k in sorted(existing.keys())]
    path.write_text("".join(lines), encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except Exception:
        pass

def _prompt(label: str, default: str | None = None, secret: bool = False) -> str:
    try:
        import getpass
    except Exception:
        getpass = None
    if secret and getpass:
        val = getpass.getpass(f"{label}{' ['+default+']' if default else ''}: ").strip()
    else:
        val = input(f"{label}{' ['+default+']' if default else ''}: ").strip()
    return val or (default or "")

def run_backup_wizard(env_out: Path | None = None) -> int:
    """
    Interaktiv Dropbox-oppsett for refresh token.
    Skriver .env med: DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN.
    Returnerer 0 ved suksess, ellers != 0.
    """
    try:
        from dropbox import DropboxOAuth2FlowNoRedirect  # type: ignore
    except Exception as e:
        print("Mangler 'dropbox' pakken i venv.")
        print("Tips: /home/reidar/tools/venv/bin/pip install dropbox")
        print(f"Feil: {e}")
        return 2
    app_key = os.environ.get("DROPBOX_APP_KEY") or ""
    app_secret = os.environ.get("DROPBOX_APP_SECRET") or ""
    print("\n=== Dropbox wizard (refresh token) ===")
    print("Du trenger APP_KEY og APP_SECRET fra Dropbox App Console (Scoped App).")
    print("De lagres i tools/.env sammen med refresh token.\n")
    app_key = _prompt("APP_KEY", default=app_key)
    app_secret = _prompt("APP_SECRET", default=app_secret, secret=True)
    if not app_key or not app_secret:
        print("APP_KEY og APP_SECRET er påkrevd.")
        return 2
    flow = DropboxOAuth2FlowNoRedirect(
        app_key,
        app_secret,
        token_access_type="offline",  # gir refresh token
        use_pkce=True,
    )
    authorize_url = flow.start()
    print("\n1) Åpne denne URLen i en nettleser og logg inn, godkjenn app-tilgang:")
    print(authorize_url)
    print("\n2) Kopiér 'authorization code' fra nettsiden, lim inn under.\n")
    auth_code = _prompt("CODE").strip()
    if not auth_code:
        print("CODE mangler.")
        return 2
    try:
        result = flow.finish(auth_code)
    except Exception as e:
        print(f"Kunne ikke fullføre OAuth: {e}")
        return 3
    refresh_token = getattr(result, "refresh_token", None)
    if not refresh_token:
        print("Mottok ikke refresh token. Sjekk at appen er Scoped og token_access_type=offline.")
        return 3
    out_path = env_out or _env_path()
    _write_env(
        out_path,
        {
            "DROPBOX_APP_KEY": app_key,
            "DROPBOX_APP_SECRET": app_secret,
            "DROPBOX_REFRESH_TOKEN": refresh_token,
        },
    )
    print("\n✅ Ferdig! Lagret verdier i:", out_path)
    print("Disse brukes automatisk av backup-opplasteren.\n")
    print("Test nå f.eks.: rt backup --dry-run --profile <din_profil> --tag test")
    return 0
