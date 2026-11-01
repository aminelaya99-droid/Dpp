"""إعادة الضبط: «مسح كل البيانات» محمية بكلمة سر → برنامج جديد تماماً (لا يُحفظ شيء)."""
from __future__ import annotations

import shutil
from pathlib import Path

from dpp.config import backups_dir, db_path
from dpp.db.session import current_db_path, init_db, reset_engine
from dpp.services import auth


def wipe_all(s, password: str):
    if not auth.check_admin_password(s, password):
        raise ValueError("كلمة السر غير صحيحة")
    path = current_db_path() or str(db_path())
    reset_engine()
    if path != ":memory:":
        for suffix in ("", "-journal", "-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)
        shutil.rmtree(backups_dir(), ignore_errors=True)  # لا يُحفظ شيء
    return init_db(path)
