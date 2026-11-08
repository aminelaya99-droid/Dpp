"""النسخ الاحتياطي والاستعادة الآمنة لقاعدة SQLite."""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

from ..db.database import Database, default_data_dir

MANIFEST = "dpp_backup.json"


def backup_dir(db: Database) -> Path:
    d = db.get_setting("backup_dir")
    p = Path(d) if d else default_data_dir() / "backups"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _integrity_ok(path: Path) -> tuple[bool, str]:
    try:
        c = sqlite3.connect(str(path))
        r = c.execute("PRAGMA integrity_check").fetchone()[0]
        ok = r == "ok" and c.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='sessions'").fetchone()[0] == 1
        c.close()
        return ok, r
    except sqlite3.DatabaseError as e:
        return False, str(e)


def create_backup(db: Database, label: str = "يدوي", target_dir: Path | None = None) -> Path:
    target_dir = Path(target_dir) if target_dir else backup_dir(db)
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    tmp = target_dir / f".tmp_{stamp}.sqlite"
    dst = sqlite3.connect(str(tmp))
    db.conn.backup(dst)           # SQLite Online Backup API: آمن أثناء العمل
    dst.close()
    ok, msg = _integrity_ok(tmp)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"فشل فحص سلامة النسخة: {msg}")
    out = target_dir / f"DPP_{stamp}.dppbak"
    counts = {t: db.scalar(f"SELECT COUNT(*) FROM {t}", default=0)
              for t in ("formations", "teachers", "subjects", "sessions", "calendar_events")}
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp, "dpp.sqlite")
        z.writestr(MANIFEST, json.dumps({"created": datetime.now().isoformat(timespec="seconds"), "label": label,
                                         "app": "DPP", "counts": counts}, ensure_ascii=False))
        logo = db.get_setting("institution_logo")
        if logo and os.path.isfile(logo):
            z.write(logo, "files/" + Path(logo).name)
    tmp.unlink(missing_ok=True)
    db.log("نسخة احتياطية", "backup", None, {"file": out.name, "label": label})
    prune(db, target_dir)
    return out


def prune(db: Database, target_dir: Path):
    keep = max(1, db.get_int("backup_keep"))
    files = sorted(target_dir.glob("DPP_*.dppbak"))
    for f in files[:-keep]:
        f.unlink(missing_ok=True)


def list_backups(db: Database) -> list[dict]:
    out = []
    for f in sorted(backup_dir(db).glob("DPP_*.dppbak"), reverse=True):
        info = inspect_backup(f)
        out.append(info)
    return out


def inspect_backup(path) -> dict:
    path = Path(path)
    info = {"path": str(path), "name": path.name, "size": path.stat().st_size, "valid": False}
    try:
        with zipfile.ZipFile(path) as z:
            meta = json.loads(z.read(MANIFEST).decode("utf-8"))
            info.update(meta)
            tmpdir = path.parent / f".check_{path.stem}"
            tmpdir.mkdir(exist_ok=True)
            z.extract("dpp.sqlite", tmpdir)
            ok, msg = _integrity_ok(tmpdir / "dpp.sqlite")
            shutil.rmtree(tmpdir, ignore_errors=True)
            info["valid"], info["check"] = ok, msg
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError, OSError) as e:
        info["check"] = f"ملف غير صالح: {e}"
    return info


def restore_backup(db: Database, path) -> Database:
    """يستعيد نسخة بأمان ويعيد كائن قاعدة بيانات جديداً مفتوحاً على البيانات المستعادة."""
    info = inspect_backup(path)
    if not info["valid"]:
        raise RuntimeError("النسخة الاحتياطية تالفة أو غير صالحة؛ لم يتم تغيير أي بيانات. " + info.get("check", ""))
    db_path = db.path
    safety = create_backup(db, label="تلقائي قبل الاستعادة")
    db.close()
    tmp = db_path.with_suffix(".restore_tmp")
    with zipfile.ZipFile(path) as z:
        with z.open("dpp.sqlite") as src, open(tmp, "wb") as dst:
            shutil.copyfileobj(src, dst)
    ok, msg = _integrity_ok(tmp)
    if not ok:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"فشل الفحص بعد الاستخراج: {msg}")
    for ext in ("-wal", "-shm"):
        Path(str(db_path) + ext).unlink(missing_ok=True)
    os.replace(tmp, db_path)
    new = Database(db_path)
    ok, msg = _integrity_ok(db_path)
    if not ok:   # تراجع إلى نسخة الأمان
        new.close()
        with zipfile.ZipFile(safety) as z:
            with z.open("dpp.sqlite") as src, open(db_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
        raise RuntimeError("فشل فحص قاعدة البيانات بعد الاستعادة؛ أعيدت البيانات السابقة.")
    new.log("استعادة نسخة احتياطية", "backup", None, {"file": Path(path).name, "safety": safety.name})
    return new


def auto_backup_if_due(db: Database, hours: int = 24) -> Path | None:
    if db.get_setting("backup_auto") != "1":
        return None
    files = sorted(backup_dir(db).glob("DPP_*.dppbak"))
    if files:
        age = datetime.now().timestamp() - files[-1].stat().st_mtime
        if age < hours * 3600:
            return None
    return create_backup(db, label="تلقائي")


def wipe_all(db: Database, password: str, delete_backups: bool = False) -> list[Path]:
    """مسح كل البيانات والعودة إلى الصفر (كأن البرنامج جديد). يتطلب كلمة مرور المدير.

    يغلق قاعدة البيانات ويحذف ملفها (وملفات WAL)، وكذلك النسخ الاحتياطية إن طُلب ذلك. لا رجوع فيه.
    يعيد قائمة الملفات المحذوفة.
    """
    if not db.check_login(db.current_user, password):
        raise ValueError("كلمة المرور غير صحيحة.")
    bdir = backup_dir(db)
    path = Path(db.path)
    db.close()
    removed = []
    for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm")):
        if p.exists():
            p.unlink()
            removed.append(p)
    if delete_backups and bdir.exists():
        for p in bdir.glob("*.sqlite"):
            p.unlink()
            removed.append(p)
    return removed
