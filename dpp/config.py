"""مسارات البيانات والإعدادات العامة."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def data_dir() -> Path:
    """مجلد بيانات البرنامج: DPP_DATA_DIR أو %APPDATA%/DPP أو ~/.dpp."""
    env = os.environ.get("DPP_DATA_DIR")
    if env:
        p = Path(env)
    elif sys.platform.startswith("win") and os.environ.get("APPDATA"):
        p = Path(os.environ["APPDATA"]) / "DPP"
    else:
        p = Path.home() / ".dpp"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "dpp.sqlite3"


def backups_dir() -> Path:
    p = data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p
