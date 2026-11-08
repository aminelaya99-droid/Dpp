"""تنبيهات البيانات الدائمة: مشاكل في المقرر أو البيانات تبقى ظاهرة حتى تُصلح أو تؤكَّد.

كل تنبيه له مفتاح ثابت (key)، فإعادة الاستيراد لا تكرره، والتنبيه الذي أكّدته يبقى مؤكداً.
"""
from __future__ import annotations

from ..db.database import Database

SEVERITY_LABELS = {"high": "عالية", "medium": "متوسطة", "low": "منخفضة"}
KIND_LABELS = {"curriculum_file": "ملف المقرر", "curriculum": "المقرر", "data": "البيانات", "progress": "التقدم"}
_ORDER = {"high": 0, "medium": 1, "low": 2}


def add(db: Database, key: str, kind: str, title: str, details: str = "", severity: str = "medium",
        level_id: int | None = None, specialty_id: int | None = None, subject_id: int | None = None,
        target: str = "") -> None:
    """يضيف التنبيه أو يحدّث نصه؛ لا يعيد فتح تنبيه أكّده المستخدم."""
    db.execute("""INSERT INTO data_alerts(key, kind, severity, title, details, level_id, specialty_id, subject_id, target)
                  VALUES (?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(key) DO UPDATE SET title=excluded.title, details=excluded.details,
                  severity=excluded.severity, target=excluded.target""",
               (key, kind, severity, title, details, level_id, specialty_id, subject_id, target))


def open_alerts(db: Database, kind: str | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM data_alerts WHERE resolved=0" + (" AND kind=?" if kind else ""),
                (kind,) if kind else ())
    out = [dict(r) for r in rows]
    out.sort(key=lambda r: (_ORDER.get(r["severity"], 3), r["kind"], r["id"]))
    return out


def count_open(db: Database) -> int:
    try:
        return int(db.scalar("SELECT COUNT(*) FROM data_alerts WHERE resolved=0", (), 0))
    except Exception:
        return 0


def resolve(db: Database, alert_id: int, note: str = "") -> None:
    with db.tx():
        db.execute("UPDATE data_alerts SET resolved=1 WHERE id=?", (alert_id,))
        db.log("تأكيد تنبيه", "data_alerts", alert_id, {"note": note})


def reopen(db: Database, alert_id: int) -> None:
    db.execute("UPDATE data_alerts SET resolved=0 WHERE id=?", (alert_id,))
    db.commit()


def drop_kind(db: Database, kind: str, keep_resolved: bool = True) -> None:
    """يحذف تنبيهات نوع معيّن قبل إعادة حسابها (المؤكدة تبقى ليتذكر البرنامج أنك أكدتها)."""
    db.execute("DELETE FROM data_alerts WHERE kind=?" + (" AND resolved=0" if keep_resolved else ""), (kind,))
