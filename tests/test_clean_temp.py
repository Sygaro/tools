# tests/test_clean_temp.py
from pathlib import Path
import json
import shutil

from r_tools.tools.clean_temp import run_clean

def test_clean_does_not_touch_venv(tmp_path: Path):
    # Prosjektstruktur
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pkg").mkdir()
    # Simuler venv
    venv = project / ".venv"
    (venv / "Lib" / "site-packages").mkdir(parents=True)
    (venv / "pyvenv.cfg").write_text("home = /usr/bin/python3\n")
    # Uønsket mønster inne i venv (ville normalt blitt slettet)
    (venv / "Lib" / "site-packages" / "__pycache__").mkdir()

    # Utenfor venv – skal slettes
    (project / "pkg" / "__pycache__").mkdir()

    cfg = {
        "project_root": str(project),
        "clean": {
            "enable": True,
            "targets": {
                "pycache": True,
                "pytest_cache": True,
                "mypy_cache": True,
                "ruff_cache": True,
                "coverage": True,
                "build": True,
                "dist": True,
                "editor": True,
                "ds_store": True,
                "thumbs_db": True
            },
            "allow_venv_clean": False
        }
    }

    # Dry-run først
    run_clean(cfg, only=None, skip=[], dry_run=True)
    # Kjør faktisk sletting
    run_clean(cfg, only=None, skip=[], dry_run=False)

    # __pycache__ i prosjekt skal bort
    assert not (project / "pkg" / "__pycache__").exists()
    # __pycache__ i venv skal bestå
    assert (venv / "Lib" / "site-packages" / "__pycache__").exists()
