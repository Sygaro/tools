#!/usr/bin/env python3
"""
Fleksibel backup-CLI med JSON-profiler.
- SOURCE/DEST tolkes relativt til HOME hvis de ikke er absolutte.
- Standard DEST: ~/Backups, og arkiver legges i ~/Backups/<project>/<YYYY>/<MM>/.
- --config PATH.json: last inn innstillinger (én profil eller profiles:{...}).
- --profile NAME: plukk profil fra config eller standard-oppslag.
- Prioritet: CLI > JSON > defaults.
- --list: skriv hvilke filer som blir med (ingen skriving).
"""
import argparse
import fnmatch
import json
import logging
import os
import sys
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from uploader_dropbox import upload_to_dropbox  # type: ignore

try:
    from dotenv import load_dotenv  # type: ignore
except Exception:
    load_dotenv = None

def _lazy_import_dropbox():
    import uploader_dropbox  # noqa: F401

    return uploader_dropbox

LOG = logging.getLogger("backup")
DEFAULT_DEST = str(Path.home() / "Backups")  # <-- stor B
IGNORE_FILE = ".backupignore"
EXCLUDE_DIRNAMES: set[str] = {
    "venv",
    ".venv",
    ".git",
    "node_modules",
    "__pycache__",
    "dist",
    "build",
    "backups",
    "Backups",
}
EXCLUDE_FILEPATTERNS: list[str] = ["*.pyc", "*.pyo", "*.log", "*.tmp"]

# ---------- Utils
def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

def expand_vars_home(s: str) -> str:
    return os.path.expanduser(os.path.expandvars(s))

def resolve_from_home(path_arg: str) -> Path:
    p = Path(expand_vars_home(path_arg))
    if p.is_absolute():
        return p.resolve()
    return (Path.home() / p).resolve()

def read_ignore_file(src: Path) -> list[str]:
    patterns: list[str] = []
    f = src / IGNORE_FILE
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns

def matched_any(path_rel: str, patterns: Iterable[str]) -> bool:
    for p in patterns:
        if fnmatch.fnmatch(path_rel, p):
            return True
    return False

def iter_files(src: Path, exclude_patterns: Iterable[str], include_hidden: bool) -> Iterable[Path]:
    for p in src.rglob("*"):
        if p.is_dir():
            continue
        rel_path = p.relative_to(src)
        rel_posix = rel_path.as_posix()
        if not include_hidden and any(part.startswith(".") for part in rel_path.parts):
            continue
        if any(part in EXCLUDE_DIRNAMES for part in rel_path.parts):
            continue
        if matched_any(rel_posix, EXCLUDE_FILEPATTERNS):
            continue
        if matched_any(rel_posix, exclude_patterns):
            continue
        yield p

# ---------- JSON config
def find_default_config() -> Path | None:
    """
    Finn standard konfig-fil når --config ikke er oppgitt.
    Prioritet:
      1) Miljøvariabel BACKUP_CONFIG (fil)
      2) CWD: backup.json / backup_profiles.json / config/backup_profiles.json
      3) Ved kjørende skript: <repo_root>/config/backup_profiles.json
         (dvs. hvis backup.py ligger i tools/backup_app/, repo_root=tools/)
      4) $HOME: ~/.config/backup_app/backup_profiles.json
      5) Bakoverkompatible plasseringer: ~/.config/backup_app/profiles.json, ~/backup.json
    """
    # 1) Miljøvariabel
    env_cfg = os.getenv("BACKUP_CONFIG")
    if env_cfg:
        p = Path(os.path.expanduser(os.path.expandvars(env_cfg)))
        if p.is_file():
            return p.resolve()
    # 2) CWD-varianter
    cwd = Path.cwd()
    candidates = [
        cwd / "backup.json",
        cwd / "backup_profiles.json",
        cwd / "config" / "backup_profiles.json",
    ]
    # 3) tools/config/backup_profiles.json hvis backup.py ligger i tools/backup_app/
    here = Path(__file__).resolve().parent
    repo_root = here.parent  # antatt .../tools
    candidates.append(repo_root / "config" / "backup_profiles.json")
    # 4) $HOME/.config/backup_app/backup_profiles.json
    home_cfg_dir = Path.home() / ".config" / "backup_app"
    candidates.append(home_cfg_dir / "backup_profiles.json")
    # 5) Bakoverkompatible plasseringer
    candidates.append(home_cfg_dir / "profiles.json")  # gammel
    candidates.append(Path.home() / "backup.json")  # gammel
    for c in candidates:
        if c.is_file():
            return c.resolve()
    return None

def load_json_config(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Config må være et JSON-objekt.")
        return data
    except Exception as e:
        raise SystemExit(f"Kunne ikke lese config {path}: {e}")

def select_profile(config: dict[str, Any], profile: str | None) -> dict[str, Any]:
    # To formater støttes:
    # 1) Flat: { "project": "...", "source": "...", ... }
    # 2) profiler: { "profiles": {"navn": {...}, "annet": {...}}, "default": "navn" }
    if "profiles" in config and isinstance(config["profiles"], dict):
        profiles = config["profiles"]
        if profile:
            if profile not in profiles:
                raise SystemExit(f"Fant ikke profil '{profile}' i config.")
            base = profiles[profile]
        else:
            if "default" in config and config["default"] in profiles:
                base = profiles[config["default"]]
            elif len(profiles) == 1:
                base = list(profiles.values())[0]
            else:
                names = ", ".join(sorted(profiles.keys()))
                raise SystemExit(f"Config inneholder flere profiler ({names}). Oppgi --profile.")
        assert isinstance(base, dict), "Profil må være et objekt"
        return base
    # Flat config
    return config

def coerce_types(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    # Normaliser typer
    if "keep" in out:
        try:
            out["keep"] = int(out["keep"])
        except Exception:
            del out["keep"]
    if "include_hidden" in out:
        out["include_hidden"] = bool(out["include_hidden"])
    if "no_verify" in out:
        out["no_verify"] = bool(out["no_verify"])
    if "dry_run" in out:
        out["dry_run"] = bool(out["dry_run"])
    if "verbose" in out:
        out["verbose"] = bool(out["verbose"])
    if "exclude" in out and not isinstance(out["exclude"], list):
        out["exclude"] = [str(out["exclude"])]
    # Expand vars in string paths
    for key in (
        "source",
        "dest",
        "dropbox_path",
        "project",
        "tag",
        "version",
        "format",
        "dropbox_mode",
    ):
        if key in out and isinstance(out[key], str):
            out[key] = expand_vars_home(out[key])
    return out

# ---------- Archiving & layout
def make_archive(
    src: Path,
    dest_root: Path,
    project: str,
    version: str | None,
    tag: str | None,
    fmt: str,
    exclude_patterns: Iterable[str],
    include_hidden: bool,
    dry_run: bool,
) -> Path:
    # ~/Backups/<project>/<YYYY>/<MM>/
    now = datetime.now()
    year = now.strftime("%Y")
    month = now.strftime("%m")
    project_dir = dest_root / project
    dest_dir = project_dir / year / month
    dest_dir.mkdir(parents=True, exist_ok=True)
    dt = now.strftime("%Y%m%d-%H%M")
    parts = [project]
    if version:
        parts.append(f"v{version}")
    parts.append(dt)
    if tag:
        parts.append(tag)
    base = "_".join(parts)
    if fmt == "zip":
        out = dest_dir / f"{base}.zip"
    elif fmt in ("tar.gz", "tgz"):
        out = dest_dir / f"{base}.tar.gz"
    else:
        raise SystemExit(f"Ukjent format: {fmt}")
    LOG.info("Lager arkiv: %s", out)
    if dry_run:
        return out
    if fmt == "zip":
        import zipfile

        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in iter_files(src, exclude_patterns, include_hidden):
                zf.write(f, f.relative_to(src).as_posix())
    else:
        import tarfile

        with tarfile.open(out, "w:gz") as tf:
            for f in iter_files(src, exclude_patterns, include_hidden):
                tf.add(f, f.relative_to(src).as_posix())
    return out

def verify_archive(archive_path: Path) -> None:
    if archive_path.suffix == ".zip":
        import zipfile

        with zipfile.ZipFile(archive_path, "r") as zf:
            _ = zf.namelist()
    elif archive_path.suffixes[-2:] == [".tar", ".gz"] or archive_path.suffix == ".tgz":
        import tarfile

        with tarfile.open(archive_path, "r:gz") as tf:
            _ = tf.getmembers()
    else:
        LOG.warning("Ukjent arkivtype for verifisering: %s", archive_path)

def apply_retention(project_dir: Path, project: str, keep: int) -> None:
    if keep <= 0:
        return
    candidates: list[Path] = []
    for p in project_dir.rglob("*"):
        if p.is_file():
            name = p.name
            if not name.startswith(f"{project}_"):
                continue
            if p.suffix == ".zip" or p.suffix == ".tgz" or p.suffixes[-2:] == [".tar", ".gz"]:
                candidates.append(p)
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    to_delete = candidates[keep:]
    for p in to_delete:
        try:
            LOG.info("Sletter pga retention: %s", p)
            p.unlink(missing_ok=True)
        except Exception as e:
            LOG.warning("Klarte ikke slette %s: %s", p, e)

def create_latest_symlink(project_dir: Path, archive_path: Path, project: str) -> None:
    link = project_dir / f"{project}_latest"
    if link.exists() or link.is_symlink():
        try:
            link.unlink()
        except Exception:
            pass
    try:
        link.symlink_to(archive_path.resolve())
    except Exception as e:
        LOG.debug("Kunne ikke lage symlink (OK på f.eks. Dropbox/FAT): %s", e)

# ---------- Arg parsing (two-stage: pre-parse config/profile, then full)
def build_full_parser(defaults: dict[str, Any]) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Fleksibel prosjekt-backup med JSON-profiler og valgfri Dropbox.")
    p.set_defaults(**defaults)
    p.add_argument("--project", "-p", help="Prosjektnavn (default: navn på kildemappe)")
    p.add_argument("--source", "-s", help="Kildemappe (relativ = fra HOME)")
    p.add_argument("--dest", "-d", help=f"Målmappe (relativ = fra HOME) (default: {DEFAULT_DEST})")
    p.add_argument("--version", "-V", help="Versjonsnummer, f.eks. 1.06 (valgfritt)")
    p.add_argument("--no-version", action="store_true", help="Tving uten versjon i filnavn")
    p.add_argument("--tag", "-t", help="Ekstra tag i filnavn, f.eks. Frontend_OK")
    p.add_argument("--format", choices=["zip", "tar.gz", "tgz"], help="Arkivformat")
    p.add_argument("--include-hidden", action="store_true", help="Ta med skjulte filer/mapper")
    p.add_argument(
        "--exclude",
        action="append",
        default=defaults.get("exclude", []),
        help="Glob-mønster for ekskludering (kan gjentas). Eksempel: --exclude '.env'",
    )
    p.add_argument("--dropbox-path", help="Sti i Dropbox for opplasting")
    p.add_argument("--dropbox-mode", choices=["add", "overwrite"], help="Dropbox skrivemodus")
    p.add_argument(
        "--keep",
        type=int,
        help="Behold kun N siste arkiver for dette prosjektet (0=av)",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List filer som blir inkludert og avslutt (ingen skriving)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Vis hva som ville skjedd, uten å skrive filer",
    )
    p.add_argument("--no-verify", action="store_true", help="Ikke verifiser arkivet etter skriving")
    p.add_argument("--verbose", "-v", action="store_true", help="Mer logging")
    # Pre-parsed options (still accepted to show in --help)
    p.add_argument("--config", help="Sti til JSON-konfig (backup.json).")
    p.add_argument("--profile", help="Profilnavn i config.")
    return p

def main(argv: list[str] | None = None) -> int:
    # --- .env loading (robust) ---
    if load_dotenv:
        from dotenv import dotenv_values

        # 1) Prøv standard (CWD) først – ingen skade om den ikke finnes
        try:
            load_dotenv()
        except Exception:
            pass
        # 2) Last eksplisitt fra tools/.env (repo-rot), så backup_app/.env, så $HOME/.env
        _TOOLS_ENV = Path(__file__).resolve().parents[1] / ".env"  # ./tools/.env
        _BACKUP_ENV = Path(__file__).resolve().parent / ".env"  # ./tools/backup_app/.env
        _HOME_ENV = Path.home() / ".env"
        if _BACKUP_ENV.is_file():
            LOG.warning("Ignorerer backup_app/.env – bruk tools/.env for Dropbox-nøkler.")
        for _p in (_TOOLS_ENV, _BACKUP_ENV, _HOME_ENV):
            if _p.is_file():
                # Sikre at verdiene kommer inn i os.environ uten å overskrive allerede satte
                for k, v in dotenv_values(_p).items():
                    if v is not None:
                        os.environ.setdefault(k, v)
        # (valgfritt) liten diagnose når -v/--verbose er på
        if LOG.isEnabledFor(logging.DEBUG):
            present = {
                k: bool(os.getenv(k))
                for k in (
                    "DROPBOX_APP_KEY",
                    "DROPBOX_APP_SECRET",
                    "DROPBOX_REFRESH_TOKEN",
                )
            }
            LOG.debug("Env loaded (.env): %s", present)
    # --- end .env loading ---
    # Stage 1: bare --config/--profile/--verbose for tidlig logging
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config")
    pre.add_argument("--profile")
    pre.add_argument("--verbose", "-v", action="store_true")
    pre_args, remaining = pre.parse_known_args(argv)
    setup_logging(pre_args.verbose)
    # Last konfig (hvis angitt eller via auto-oppslag)
    defaults: dict[str, Any] = {
        "dest": DEFAULT_DEST,
        "format": "zip",
        "include_hidden": False,
        "exclude": [],
        "dropbox_mode": "add",
        "keep": 0,
        "dry_run": False,
        "no_verify": False,
        "verbose": pre_args.verbose,
    }
    cfg_path: Path | None = None
    if pre_args.config:
        cfg_path = resolve_from_home(pre_args.config)
        LOG.debug("Bruker config: %s", cfg_path)
    else:
        auto = find_default_config()
        if auto:
            cfg_path = auto
            LOG.debug("Fant config: %s", cfg_path)
    if cfg_path:
        cfg_all = load_json_config(cfg_path)
        cfg = select_profile(cfg_all, pre_args.profile)
        cfg = coerce_types(cfg)
        # Sett defaults fra config
        defaults.update({k: v for k, v in cfg.items() if v is not None})
    # Stage 2: full parser med defaults fra config
    parser = build_full_parser(defaults)
    args = parser.parse_args(argv)
    # Resolve SOURCE/DEST
    if not args.source:
        LOG.error("Kildemappe (--source) mangler (kan settes i config).")
        return 2
    src = resolve_from_home(args.source)
    if not src.exists() or not src.is_dir():
        LOG.error("Kildemappe finnes ikke: %s", src)
        return 2
    dest_root = resolve_from_home(args.dest or DEFAULT_DEST)
    project = args.project or src.name
    version = args.version
    if args.no_version:
        version = None
    exclude_patterns: list[str] = read_ignore_file(src)
    # NB: args.exclude kan være None eller liste; legg til
    if args.exclude:
        exclude_patterns.extend(args.exclude)
    LOG.info("Prosjekt: %s", project)
    LOG.info("Kilde:    %s", src)
    LOG.info("Målrot:   %s", dest_root)
    LOG.info("Format:   %s", args.format)
    LOG.info("Versjon:  %s", version if version else "(ingen)")
    if args.tag:
        LOG.info("Tag:      %s", args.tag)
    if exclude_patterns:
        LOG.info("Exclude:  %s", ", ".join(exclude_patterns))
    LOG.info("Hidden:   %s", "med" if args.include_hidden else "uten")
    LOG.info("Dry run:  %s", "ja" if args.dry_run else "nei")
    # --list: bare skriv filene
    if args.list:
        count = 0
        for f in iter_files(src, exclude_patterns, args.include_hidden):
            print(f.relative_to(src).as_posix())
            count += 1
        LOG.info("Totalt %d filer ville blitt inkludert.", count)
        return 0
    # Lag arkiv
    archive_path = make_archive(
        src=src,
        dest_root=dest_root,
        project=project,
        version=version,
        tag=args.tag,
        fmt=args.format,
        exclude_patterns=exclude_patterns,
        include_hidden=args.include_hidden,
        dry_run=args.dry_run,
    )
    project_dir = dest_root / project
    if not args.dry_run:
        if not args.no_verify:
            LOG.info("Verifiserer arkiv...")
            verify_archive(archive_path)
        create_latest_symlink(project_dir, archive_path, project)
    # Retensjon
    if args.keep and not args.dry_run:
        apply_retention(project_dir, project, int(args.keep))
    # Dropbox (fra config/CLI)
    # Dropbox (fra config/CLI) – refresh-token only
    # Dropbox (fra config/CLI) – refresh-token only
    if args.dropbox_path:
        try:
            LOG.info("Laster opp til Dropbox: %s -> %s", archive_path.name, args.dropbox_path)
            if not args.dry_run:
                upload_to_dropbox(
                    local_path=archive_path,
                    dest_path=str(Path(args.dropbox_path) / archive_path.name),
                    mode=args.dropbox_mode or "add",
                )
        except Exception as e:
            LOG.error("Dropbox-opplasting feilet: %s", e)
            return 3
    LOG.info("Ferdig.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
