# /home/reidar/tools/r_tools/tools/backup_integration.py
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional

# Rot til tools/
ROOT_DIR = Path(__file__).resolve().parents[2]

# PRIMÆR: tools/configs  (← riktig)
CONFIG_DIR = ROOT_DIR / "configs"

# LEGACY fallback: tools/config  (kun om noen filer fortsatt ligger her)
LEGACY_CONFIG_DIR = ROOT_DIR / "config"

def _load_backup_cfg() -> Dict[str, Any]:
    """
    Leser optional backup_config.json (peker primært på backup.py-sti).
    Sjekker først tools/configs, deretter legacy tools/config.
    """
    for path in (
        CONFIG_DIR / "backup_config.json",
        LEGACY_CONFIG_DIR / "backup_config.json",
    ):
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                break
    # Default: anta backup.py under tools/backup_app/
    return {
        "backup": {"script": str((ROOT_DIR / "backup_app" / "backup.py").resolve())}
    }

def _auto_profiles_config() -> Optional[Path]:
    """
    Finn profiler automatisk.
    Prioritet (riktig først):
      1) tools/configs/backup_profiles.json
      2) tools/configs/profiles.json          (tillatt alias)
      3) tools/config/backup_profiles.json    (legacy-mappe)
      4) tools/config/profiles.json           (legacy-navn+mappe)
    """
    for p in (
        CONFIG_DIR / "backup_profiles.json",
        CONFIG_DIR / "profiles.json",
        LEGACY_CONFIG_DIR / "backup_profiles.json",
        LEGACY_CONFIG_DIR / "profiles.json",
    ):
        if p.is_file():
            return p
    return None

def _read_profiles() -> Tuple[Optional[Path], Dict[str, Any]]:
    """
    Les backup-profiler (om tilgjengelig). Returner (path, data).
    data-format forventes å være { "profiles": {...}, "default": "navn" } eller flat.
    """
    p = _auto_profiles_config()
    if not p:
        return None, {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return p, {}
        return p, data
    except Exception:
        return p, {}

def _build_argv(script: Path, args: Dict[str, Any]) -> List[str]:
    """
    Map fra UI/CLI felter → backup.py CLI-flagg. Sender kun felter som er gitt.
    """
    argv: List[str] = [str(script)]

    def add(*xs: Any) -> None:
        argv.extend([str(x) for x in xs])

    # 1) config/profil
    cfg_from_args = args.get("config")
    if cfg_from_args:
        add("--config", cfg_from_args)
    else:
        auto_cfg = _auto_profiles_config()
        if auto_cfg:
            add("--config", str(auto_cfg))

    if args.get("profile"):
        add("--profile", args["profile"])

    # 2) hovedvalg
    if args.get("project"):
        add("--project", args["project"])
    if args.get("source"):
        add("--source", args["source"])
    if args.get("dest"):
        add("--dest", args["dest"])
    if args.get("version"):
        add("--version", args["version"])
    if args.get("no_version"):
        add("--no-version")
    if args.get("tag"):
        add("--tag", args["tag"])
    if args.get("format"):
        add("--format", args["format"])
    if args.get("include_hidden"):
        add("--include-hidden")
    if args.get("keep") not in (None, ""):
        add("--keep", int(args["keep"]))
    if args.get("list"):
        add("--list")
    if args.get("dry_run"):
        add("--dry-run")
    if args.get("no_verify"):
        add("--no-verify")
    if args.get("verbose"):
        add("--verbose")

    # 3) exclude: støtt både streng og liste
    excludes = args.get("exclude")
    if isinstance(excludes, str):
        parts: List[str] = []
        for line in excludes.replace(",", "\n").splitlines():
            s = line.strip()
            if s:
                parts.append(s)
        excludes = parts
    if isinstance(excludes, list):
        for pat in excludes:
            add("--exclude", pat)

    # 4) dropbox
    if args.get("dropbox_path"):
        add("--dropbox-path", args["dropbox_path"])
    if args.get("dropbox_mode"):
        add("--dropbox-mode", args["dropbox_mode"])

    return argv

def run_backup(overrides: Dict[str, Any] | None = None) -> Tuple[int, str]:
    """
    Kjør backup.py som subprosess. Returner (returncode, samlet_output).
    - Hvis profil ikke er gitt, forsøk å lese default-profil fra configs/backup_profiles.json
    """
    overrides = overrides or {}
    # Auto-utfyll profil fra default hvis ikke spesifisert
    if not overrides.get("profile"):
        _, prof_data = _read_profiles()
        if (
            prof_data
            and "profiles" in prof_data
            and isinstance(prof_data["profiles"], dict)
        ):
            default_name = prof_data.get("default")
            if default_name and default_name in prof_data["profiles"]:
                overrides["profile"] = default_name  # ← bruker default-profil

    cfg = _load_backup_cfg()
    script_str = cfg.get("backup", {}).get("script") or str(
        (ROOT_DIR / "backup_app" / "backup.py").resolve()
    )
    script = Path(script_str).expanduser().resolve()

    if not script.is_file():
        return (
            127,
            f"backup: Fant ikke backup.py på {script}\n"
            f"Tips: sett korrekt sti i {CONFIG_DIR}/backup_config.json",
        )

    argv = [sys.executable, *_build_argv(script, overrides)]
    print("▶", " ".join(shlex.quote(a) for a in argv))
    try:
        proc = subprocess.run(
            argv,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return (proc.returncode, proc.stdout)
    except Exception as e:
        return (1, f"backup: klarte ikke starte prosess: {e}")

def get_backup_info() -> Dict[str, Any]:
    """
    Meta-info for 'rt list --tool backup' og UI:
      - script path (backup.py), finnes?
      - profiles path, finnes?
      - default-profilnavn, liste med profilnavn
    """
    cfg = _load_backup_cfg()
    script_str = cfg.get("backup", {}).get("script") or str(
        (ROOT_DIR / "backup_app" / "backup.py").resolve()
    )
    script = Path(script_str).expanduser().resolve()

    profiles_path, profiles_data = _read_profiles()
    names: List[str] = []
    default_name: Optional[str] = None
    if profiles_data:
        if "profiles" in profiles_data and isinstance(profiles_data["profiles"], dict):
            names = sorted(profiles_data["profiles"].keys())
            default_name = profiles_data.get("default")

    return {
        "script": str(script),
        "script_exists": script.is_file(),
        "profiles": str(profiles_path) if profiles_path else None,
        "profiles_exists": (
            (profiles_path and profiles_path.is_file()) if profiles_path else False
        ),
        "profiles_default": default_name,
        "profiles_names": names,
        "config_dir": str(CONFIG_DIR.resolve()),
    }
