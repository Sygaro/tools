# === uploader_dropbox.py (NY) ===
# -*- coding: utf-8 -*-
from pathlib import Path
from typing import Literal

import dropbox
from dropbox.files import WriteMode

def upload_to_dropbox(
    local_path: Path,
    dest_path: str,
    token: str,
    mode: Literal["add", "overwrite"] = "add",
    chunk_size: int = 8 * 1024 * 1024,
) -> None:
    assert local_path.is_file(), f"Finner ikke fil: {local_path}"
    dbx = dropbox.Dropbox(token)
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
