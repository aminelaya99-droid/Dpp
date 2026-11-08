"""متابعة الساعات: المبرمج، المنجز، المؤجل، الملغى، المتبقي، ونسبة الإنجاز.

القواعد:
  * الحصة "منجزة" فقط إذا سُجلت حالتها done. وجودها في الجدول لا يكفي.
  * ساعات الحصة المنفذة بالاستخلاف تُنسب للمستخلف وحده.
  * المؤجلة والملغاة لا تُحتسب منجزة ولا مبرمجة؛ والتعويضية تُحتسب مرة واحدة كأي حصة.
  * الحصة المشتركة تُحتسب مرة واحدة للأستاذ، وتُحتسب لكل فوج في تقدم مادته.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..db.database import Database
from ..utils import iso, to_date
from .calendar import teaching_days


def _h(m) -> float:
    return round((m or 0) / 60.0, 2)


def requirement_progress(db: Database, formation_id: int, today=None) -> list[dict]:
    today = to_date(today or date.today())
    out = []
    reqs = db.q("""SELECT r.*, s.name sname, s.short sshort, s.color, g.name gname, sec.name secname, sec.short secshort,
                          t.full_name tname
                   FROM requirements r JOIN subjects s ON s.id=r.subject_id JOIN groups_ g ON g.id=r.group_id
                   JOIN sections sec ON sec.id=g.section_id LEFT JOIN teachers t ON t.id=r.teacher_id
                   WHERE r.formation_id=? ORDER BY sec.name, g.name, s.name""", (formation_id,))
    f = db.one("SELECT * FROM formations WHERE id=?", (formation_id,))
    elapsed_ratio = None
    if f and f["start_date"] and f["end_date"]:
        all_days = teaching_days(db, formation_id, f["start_date"], f["end_date"])
        past = [d for d in all_days if d <= today]
        elapsed_ratio = len(past) / len(all_days) if all_days else None
    for r in reqs:
        stats = defaultdict(int)
        for s in db.q("""SELECT s.status, SUM(s.end_min-s.start_min) m FROM sessions s
                         JOIN session_groups sg ON sg.session_id=s.id
                         WHERE sg.group_id=? AND s.subject_id=? GROUP BY s.status""", (r["group_id"], r["subject_id"])):
            stats[s["status"]] = s["m"] or 0
        total = r["total_hours"] or 0
        planned = _h(stats["planned"] + stats["done"])
        done = _h(stats["done"])
        pct = (done / total * 100) if total else 0.0
        late = bool(elapsed_ratio is not None and total and done < total * elapsed_ratio - 1e-6
                    and (total * elapsed_ratio - done) >= 2)
        out.append({
            "requirement_id": r["id"], "section": r["secname"], "section_short": r["secshort"], "group": r["gname"],
            "subject": r["sname"], "subject_short": r["sshort"], "color": r["color"], "teacher": r["tname"],
            "total": total, "planned": planned, "done": done,
            "postponed": _h(stats["postponed"]), "cancelled": _h(stats["cancelled"]),
            "remaining": round(max(0.0, total - done), 2), "unplanned": round(max(0.0, total - planned), 2),
            "percent": round(pct, 1), "late": late,
            "expected": round(total * elapsed_ratio, 2) if elapsed_ratio is not None else None,
        })
    return out


def late_subjects(db: Database, formation_id: int, today=None) -> list[dict]:
    return [r for r in requirement_progress(db, formation_id, today) if r["late"]]


def teacher_hours(db: Database, teacher_id: int, start=None, end=None) -> dict:
    """ساعات الأستاذ: المنجزة تُحتسب للمنفّذ الفعلي (المستخلف إن وُجد)."""
    cond, params = "", []
    if start:
        cond += " AND s.date>=?"
        params.append(iso(to_date(start)))
    if end:
        cond += " AND s.date<=?"
        params.append(iso(to_date(end)))
    executed = _h(db.scalar(f"""SELECT SUM(end_min-start_min) FROM sessions s
                                WHERE s.status='done' AND COALESCE(s.substitute_id, s.teacher_id)=? {cond}""",
                            (teacher_id, *params), 0))
    planned = _h(db.scalar(f"""SELECT SUM(end_min-start_min) FROM sessions s
                               WHERE s.status IN ('planned','done') AND COALESCE(s.substitute_id, s.teacher_id)=? {cond}""",
                           (teacher_id, *params), 0))
    as_sub = _h(db.scalar(f"""SELECT SUM(end_min-start_min) FROM sessions s
                              WHERE s.status='done' AND s.substitute_id=? {cond}""", (teacher_id, *params), 0))
    replaced = _h(db.scalar(f"""SELECT SUM(end_min-start_min) FROM sessions s
                                WHERE s.substitute_id IS NOT NULL AND s.teacher_id=? {cond}""",
                            (teacher_id, *params), 0))
    return {"planned": planned, "done": executed, "remaining": round(max(0.0, planned - executed), 2),
            "as_substitute": as_sub, "replaced_by_others": replaced}


def teacher_hours_by_period(db: Database, teacher_id: int, start, end, by: str = "week") -> list[tuple[str, float, float]]:
    fmt = "%Y-%W" if by == "week" else "%Y-%m"
    rows = db.q(f"""SELECT strftime('{fmt}', date) k,
                    SUM(CASE WHEN status IN ('planned','done') THEN end_min-start_min ELSE 0 END) p,
                    SUM(CASE WHEN status='done' THEN end_min-start_min ELSE 0 END) d
                    FROM sessions WHERE COALESCE(substitute_id, teacher_id)=? AND date>=? AND date<=?
                    GROUP BY k ORDER BY k""", (teacher_id, iso(to_date(start)), iso(to_date(end))))
    return [(r["k"], _h(r["p"]), _h(r["d"])) for r in rows]


def formation_progress(db: Database, formation_id: int, today=None) -> dict:
    rows = requirement_progress(db, formation_id, today)
    total = sum(r["total"] for r in rows)
    done = sum(r["done"] for r in rows)
    planned = sum(r["planned"] for r in rows)
    return {"total": total, "done": done, "planned": planned,
            "percent": round(done / total * 100, 1) if total else 0.0,
            "late": sum(1 for r in rows if r["late"])}
