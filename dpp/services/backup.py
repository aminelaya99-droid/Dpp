"""النسخ الاحتياطي والاستعادة (نسخة متسقة عبر واجهة sqlite3 backup)."""
from __future__ import annotations

import datetime as dt
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from dpp.config import backups_dir, db_path
from dpp.db.session import current_db_path, init_db, reset_engine
from dpp.services import settings as cfg

KEEP_AUTO = 20


def create_backup(target_dir: Path | None = None, tag: str = "manual") -> Path:
    src = current_db_path() or str(db_path())
    if src == ":memory:":
        raise ValueError("لا يمكن نسخ قاعدة بيانات في الذاكرة")
    target_dir = Path(target_dir or backups_dir())
    target_dir.mkdir(parents=True, exist_ok=True)
    out = target_dir / f"dpp_{tag}_{dt.datetime.now():%Y%m%d_%H%M%S_%f}.sqlite3"
    # closing: على Windows يبقى الملف مقفلاً ما دام الاتصال مفتوحاً
    with closing(sqlite3.connect(src)) as a, closing(sqlite3.connect(out)) as b:
        a.backup(b)
    return out


def list_backups(target_dir: Path | None = None) -> list[Path]:
    d = Path(target_dir or backups_dir())
    return sorted(d.glob("dpp_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)


def restore_backup(path: str | Path):
    """يستبدل قاعدة البيانات الحالية بالنسخة (بعد نسخة أمان للحالية) ويعيد فتحها."""
    path = Path(path)
    with closing(sqlite3.connect(path)) as c:
        ok = c.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if ok != "ok" or "trainings" not in tables:
        raise ValueError("الملف ليس نسخة احتياطية صالحة لبرنامج DPP")
    dst = current_db_path() or str(db_path())
    create_backup(tag="before_restore")
    reset_engine()
    shutil.copyfile(path, dst)
    return init_db(dst)


def prune(keep: int = KEEP_AUTO) -> None:
    autos = [p for p in list_backups() if "_auto_" in p.name]
    for p in autos[keep:]:
        p.unlink(missing_ok=True)


def auto_backup_on_exit(s) -> Path | None:
    if current_db_path() in (None, ":memory:") or cfg.get(s, "auto_backup", "1") != "1":
        return None
    out = create_backup(tag="auto")
    prune()
    return out
