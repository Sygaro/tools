# /home/reidar/tools/r_tools/tools/backup_integration.py
from __future__ import annotations
import json
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, Tuple
TOOLS_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = TOOLS_ROOT / "configs"
def _load_json(p: Path) -> Dict[str, Any]:
    return json.loads(p.read_text(encoding="utf-8"))
def _backup_config() -> Dict[str, Any]:
    cfg = CONFIG_DIR / "backup_config.json"
    if not cfg.is_file():
        # tillat kjøring uten egen config – bruk default sti
        return {"backup": {"script": "backup_app/backup.py"}}
    return _load_json(cfg)
def _resolve_script_abspath(script_path: str) -> Path:
    p = Path(script_path)
    if p.is_absolute():
        return p
    # VIKTIG: RESOLV RELATIVT TIL TOOLS_ROOT, IKKE prosjekt!
    return (TOOLS_ROOT / p).resolve()
def get_backup_info() -> Dict[str, Any]:
    c = _backup_config()
    script_rel = c.get("backup", {}).get("script", "backup_app/backup.py")
    script_abs = _resolve_script_abspath(script_rel)
    profiles = CONFIG_DIR / "backup_profiles.json"
    return {
        "config_dir": str(CONFIG_DIR),
        "script": str(script_abs),
        "script_exists": script_abs.is_file(),
        "profiles": str(profiles),
        "profiles_exists": profiles.is_file(),
        "profiles_default": (
            _load_json(profiles).get("default") if profiles.is_file() else None
        ),
        "profiles_names": (
            sorted((_load_json(profiles).get("profiles") or {}).keys())
            if profiles.is_file()
            else []
        ),
    }
def _build_backup_cmd(overrides: Dict[str, Any]) -> Tuple[list[str], Path]:
    info = get_backup_info()
    script = Path(info["script"])
    if not info["script_exists"]:
        raise FileNotFoundError(
            f"backup: Fant ikke backup.py på {script}\n"
            f"Tips: sett korrekt sti i {CONFIG_DIR / 'backup_config.json'}"
        )
    # Finn profiler
    prof = CONFIG_DIR / "backup_profiles.json"
    if not prof.is_file():
        raise FileNotFoundError(
            f"backup: Fant ikke {prof}\n" f"Tips: opprett profiler i {prof}"
        )
    python = sys.executable  # kjør i samme venv
    cmd = [python, str(script), "--config", str(prof)]
    # profile (default hvis ikke angitt)
    profile = overrides.get("profile")
    if profile:
        cmd += ["--profile", profile]
    # Enkle overrides – sendes direkte videre til backup.py
    passthrough = [
        "project",
        "source",
        "dest",
        "version",
        "tag",
        "format",
        "dropbox_path",
        "dropbox_mode",
    ]
    for k in passthrough:
        v = overrides.get(k)
        if v not in (None, ""):
            cmd += [f"--{k.replace('_','-')}", str(v)]
    # Bool / flagg
    if overrides.get("no_version"):
        cmd.append("--no-version")
    if overrides.get("include_hidden"):
        cmd.append("--include-hidden")
    if overrides.get("list"):
        cmd.append("--list")
    if overrides.get("dry_run"):
        cmd.append("--dry-run")
    if overrides.get("no_verify"):
        cmd.append("--no-verify")
    if overrides.get("verbose"):
        cmd.append("--verbose")
    # Repeterbare
    for ex in overrides.get("exclude", []) or []:
        cmd += ["--exclude", ex]
    if overrides.get("keep") is not None:
        cmd += ["--keep", str(int(overrides["keep"]))]
    return cmd, script
def run_backup(overrides: Dict[str, Any]) -> Tuple[int, str]:
    import subprocess
    # Bygg kommando (uavhengig av CWD/prosjekt)
    cmd, script = _build_backup_cmd(overrides)
    # Vis tydelig kommando
    line = "▶ " + " ".join(shlex.quote(x) for x in cmd) + "\n"
    # Kjør og fang stdout/stderr
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    out, _ = proc.communicate()
    return proc.returncode, line + (out or "")
