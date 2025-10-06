# /home/reidar/tools/uploader_dropbox.py
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Literal
import os
import dropbox
from dropbox.files import WriteMode
def _make_dbx() -> dropbox.Dropbox:
    # Kun refresh-token flyt
    refresh = os.getenv("DROPBOX_REFRESH_TOKEN")
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    missing = [
        k
        for k, v in {
            "DROPBOX_APP_KEY": app_key,
            "DROPBOX_APP_SECRET": app_secret,
            "DROPBOX_REFRESH_TOKEN": refresh,
        }.items()
        if not v
    ]
    if missing:
        raise RuntimeError(
            "Mangler miljøvariabler for Dropbox:\n  - " + "\n  - ".join(missing)
        )
    return dropbox.Dropbox(
        oauth2_refresh_token=refresh,
        app_key=app_key,
        app_secret=app_secret,
    )
def upload_to_dropbox(
    local_path: Path,
    dest_path: str,
    mode: Literal["add", "overwrite"] = "add",
    chunk_size: int = 8 * 1024 * 1024,
) -> None:
    assert local_path.is_file(), f"Finner ikke fil: {local_path}"
    dbx = _make_dbx()
    # preflight
    try:
        _ = dbx.users_get_current_account()
    except Exception as e:
        raise RuntimeError(f"Dropbox auth preflight feilet: {e}")
    file_size = local_path.stat().st_size
    write_mode = WriteMode.add if mode == "add" else WriteMode.overwrite
    with local_path.open("rb") as f:
        if file_size <= chunk_size:
            dbx.files_upload(f.read(), dest_path, mode=write_mode, mute=True)
            return
        start = dbx.files_upload_session_start(f.read(chunk_size))
        cursor = dropbox.files.UploadSessionCursor(
            session_id=start.session_id, offset=f.tell()
        )
        commit = dropbox.files.CommitInfo(path=dest_path, mode=write_mode, mute=True)
        while f.tell() < file_size:
            if (file_size - f.tell()) <= chunk_size:
                dbx.files_upload_session_finish(f.read(chunk_size), cursor, commit)
            else:
                dbx.files_upload_session_append_v2(f.read(chunk_size), cursor)
                cursor.offset = f.tell()
