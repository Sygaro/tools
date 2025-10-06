# /home/reidar/tools/r_tools/config.py
from __future__ import annotations
import json, os
from pathlib import Path
from typing import Any, Dict, Tuple, Optional
TOOLS_ROOT = Path(__file__).resolve().parents[1]
GLOBAL_CONFIG = TOOLS_ROOT / "configs" / "global_config.json"
CONFIG_DIR = Path(os.environ.get("RTOOLS_CONFIG_DIR", str(TOOLS_ROOT / "configs"))).resolve()

def _load_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            print(f"[advarsel] Tom JSON-fil ignorert: {path}")
            return {}
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"[advarsel] Ugyldig JSON i {path}: {e}")
        return {}
    except Exception as e:
        print(f"[advarsel] Kunne ikke lese {path}: {e}")
        return {}
def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out
def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            flat.update(_flatten(v, key))
        else:
            flat[key] = v
    return flat
def _merge_with_provenance(
    layers: list[tuple[str, Dict[str, Any]]],
) -> tuple[Dict[str, Any], Dict[str, str]]:
    merged: Dict[str, Any] = {}
    prov: Dict[str, str] = {}
    for name, cfg in layers:
        merged = deep_merge(merged, cfg)
        flat = _flatten(cfg)
        for k in flat.keys():
            prov[k] = name  # siste lag vinner
    return merged, prov
def load_config_info(
    tool_config_name: Optional[str] = None,
    project_override: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    info: Dict[str, Any] = {
        "tools_root": str(TOOLS_ROOT),
        "global_config": str(GLOBAL_CONFIG),
        "tool_config": None,
        "project_file": None,
        "project_override": str(project_override) if project_override else None,
        "cli_overrides": cli_overrides or {},
    }
    layers: list[tuple[str, Dict[str, Any]]] = []
    g = _load_json(GLOBAL_CONFIG)
    layers.append(("global_config", g))
    tool_cfg_path = None
    if tool_config_name:
        tool_cfg_path = TOOLS_ROOT / "configs" / tool_config_name
        info["tool_config"] = str(tool_cfg_path)
        layers.append((tool_config_name, _load_json(tool_cfg_path)))
    project_file = Path.cwd() / ".r-tools.json"
    if project_file.is_file():
        info["project_file"] = str(project_file)
        layers.append((".r-tools.json", _load_json(project_file)))
    if project_override:
        layers.append(("project_override", {"project_root": str(project_override)}))
    if cli_overrides:
        layers.append(("cli_overrides", cli_overrides))
    cfg, prov = _merge_with_provenance(layers)
    cfg.setdefault("include_extensions", [])
    cfg.setdefault("exclude_dirs", [])
    cfg.setdefault("exclude_files", [])
    cfg.setdefault("case_insensitive", True)
    info["provenance"] = prov
    return cfg, info
def load_config(
    tool_config_name: Optional[str] = None,
    project_override: Optional[Path] = None,
    cli_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg, _ = load_config_info(tool_config_name, project_override, cli_overrides)
    return cfg
