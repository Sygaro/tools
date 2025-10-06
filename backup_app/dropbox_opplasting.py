#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kompatibilitets-wrapper for historisk bruk. Videresender til uploader_dropbox.
"""
from pathlib import Path
import os
import sys
from typing import Literal
try:
    from uploader_dropbox import upload_to_dropbox
except Exception:
    print(
        "Mangler 'uploader_dropbox'. Installer requirements og prøv igjen.",
        file=sys.stderr,
    )
    raise
def main(
    local_path: str, dest_path: str, mode: Literal["add", "overwrite"] = "add"
) -> None:
    token = os.getenv("DROPBOX_TOKEN")
    if not token:
        raise SystemExit("DROPBOX_TOKEN mangler (sett i miljø eller .env).")
    upload_to_dropbox(Path(local_path), dest_path, token=token, mode=mode)
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Bruk: dropbox_opplasting.py /lokal/fil.zip /Dropbox/destinasjon/fil.zip [add|overwrite]",
            file=sys.stderr,
        )
        raise SystemExit(2)
    mode = sys.argv[3] if len(sys.argv) >= 4 else "add"
    main(sys.argv[1], sys.argv[2], mode=mode)  # type: ignore[arg-type]
