"""الغياب والاستخلاف."""
from __future__ import annotations

from ..db.database import Database
from ..utils import iso, to_date, week_start
from .timetables import check_conflicts, session_groups

REASONS = ["إجازة", "عطلة", "مهمة", "نقاهة", "تكوين", "سبب آخر"]


def add_absence(db: Database, teacher_id: int, reason: str, start, end, notes: str = "") -> int:
    s, e = to_date(start), to_date(end)
    if e < s:
        raise ValueError("تاريخ النهاية يسبق تاريخ البداية.")
    with db.tx():
        aid = db.insert("absences", teacher_id=teacher_id, reason=reason, start_date=iso(s), end_date=iso(e), notes=notes)
        db.log("تسجيل غياب", "absences", aid, {"teacher": teacher_id, "reason": reason, "from": iso(s), "to": iso(e)})
    return aid


def delete_absence(db: Database, absence_id: int):
    with db.tx():
        db.execute("DELETE FROM absences WHERE id=?", (absence_id,))
        db.log("حذف غياب", "absences", absence_id)


def affected_sessions(db: Database, absence_id: int) -> list[dict]:
    a = db.one("SELECT * FROM absences WHERE id=?", (absence_id,))
    rows = db.q("""SELECT s.*, sub.name sname FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                   WHERE s.teacher_id=? AND s.date>=? AND s.date<=? AND s.status='planned'
                   AND COALESCE(sub.kind,'teach')<>'nonteach'
                   ORDER BY s.date, s.start_min""", (a["teacher_id"], a["start_date"], a["end_date"]))
    return [dict(r) for r in rows]


SUB_REASONS = {0: "درّس هذه المادة لنفس القسم", 1: "يدرّس هذه المادة", 2: "نفس اختصاص الأستاذ الغائب",
               3: "أستاذ متفرغ"}


def _busy_teachers(db: Database, day: str, start: int, end: int, ignore_session: int | None) -> set[int]:
    rows = db.q("""SELECT COALESCE(substitute_id, teacher_id) t FROM sessions
                   WHERE date=? AND start_min<? AND end_min>? AND status IN ('planned','done') AND id<>?
                   AND COALESCE(substitute_id, teacher_id) IS NOT NULL""", (day, end, start, ignore_session or -1))
    busy = {r["t"] for r in rows}
    wd = (to_date(day).weekday() + 1) % 7
    for r in db.q("""SELECT ref_id FROM unavailability WHERE kind='teacher' AND hard=1 AND start_min<? AND end_min>?
                     AND (date=? OR (date IS NULL AND weekday=?))""", (end, start, day, wd)):
        busy.add(r["ref_id"])
    return busy


def absent_teachers(db: Database, day: str) -> set[int]:
    return {r[0] for r in db.q("SELECT teacher_id FROM absences WHERE start_date<=? AND end_date>=?", (day, day))}


def suggest_substitutes(db: Database, session_id: int, limit: int = 15) -> list[dict]:
    """كل أستاذ متفرغ في وقت الحصة وغير غائب، مرتب:
    0) درّس المادة لنفس القسم  1) يدرّس المادة  2) نفس اختصاص الغائب  3) الباقون — ثم الأقل ساعات في الأسبوع."""
    s = db.one("SELECT * FROM sessions WHERE id=?", (session_id,))
    if not s:
        return []
    orig = s["teacher_id"]
    busy = _busy_teachers(db, s["date"], s["start_min"], s["end_min"], session_id)
    absent = absent_teachers(db, s["date"])
    secs = [r[0] for r in db.q("""SELECT DISTINCT g.section_id FROM session_groups sg JOIN groups_ g ON g.id=sg.group_id
                                  WHERE sg.session_id=?""", (session_id,))]
    taught_sub = {r[0] for r in db.q("""SELECT DISTINCT COALESCE(substitute_id, teacher_id) FROM sessions
                                        WHERE subject_id=? AND COALESCE(substitute_id, teacher_id) IS NOT NULL""",
                                     (s["subject_id"],))}
    taught_sub |= {r[0] for r in db.q("SELECT teacher_id FROM teacher_subjects WHERE subject_id=?", (s["subject_id"],))}
    taught_sec = set()
    if secs:
        taught_sec = {r[0] for r in db.q(f"""SELECT DISTINCT COALESCE(s.substitute_id, s.teacher_id) FROM sessions s
                                            JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
                                            WHERE s.subject_id=? AND g.section_id IN ({','.join('?' * len(secs))})""",
                                         (s["subject_id"], *secs))}
    o = db.one("SELECT specialty, category_id FROM teachers WHERE id=?", (orig or -1,))
    spec = (o["specialty"] or "").strip() if o else ""
    wk0 = iso(week_start(to_date(s["date"])))
    load = {r[0]: r[1] or 0 for r in db.q("""SELECT COALESCE(substitute_id, teacher_id), SUM(end_min-start_min)
                                             FROM sessions WHERE date>=? AND date<=date(?, '+6 days')
                                             AND status IN ('planned','done') GROUP BY 1""", (wk0, wk0))}
    out = []
    for t in db.q("SELECT id, full_name, rank, specialty FROM teachers WHERE active=1"):
        tid = t["id"]
        if tid == orig or tid in busy or tid in absent:
            continue
        if tid in taught_sec:
            tier = 0
        elif tid in taught_sub:
            tier = 1
        elif spec and (t["specialty"] or "").strip() == spec:
            tier = 2
        else:
            tier = 3
        out.append({"id": tid, "name": t["full_name"], "rank": t["rank"] or "", "tier": tier,
                    "reason": SUB_REASONS[tier], "week_load": round(load.get(tid, 0) / 60, 1)})
    out.sort(key=lambda d: (d["tier"], d["week_load"], d["name"]))
    return out[:limit] if limit else out


def auto_assign(db: Database, absence_id: int) -> dict:
    """يعيّن أول معوّض مقترح لكل حصة متأثرة؛ الحصة التي لا معوّض لها تبقى في مكانها «بدون أستاذ»."""
    done, none = [], []
    for ses in affected_sessions(db, absence_id):
        if ses.get("substitute_id"):
            continue
        cands = suggest_substitutes(db, ses["id"], 1)
        if cands:
            assign_substitute(db, ses["id"], cands[0]["id"], force=True)
            done.append((ses["id"], cands[0]["id"]))
        else:
            none.append(ses["id"])
    return {"assigned": done, "unassigned": none}


def teacher_absent_on(db: Database, teacher_id: int, day) -> dict | None:
    r = db.one("SELECT * FROM absences WHERE teacher_id=? AND start_date<=? AND end_date>=?",
               (teacher_id, iso(to_date(day)), iso(to_date(day))))
    return dict(r) if r else None


def assign_substitute(db: Database, session_id: int, substitute_id: int | None, force=False):
    s = db.one("SELECT * FROM sessions WHERE id=?", (session_id,))
    if substitute_id is not None:
        if substitute_id == s["teacher_id"]:
            raise ValueError("المستخلف هو نفسه الأستاذ الأصلي.")
        conf = check_conflicts(db, s["date"], s["start_min"], s["end_min"], substitute_id, None, [],
                               s["subject_id"], ignore_session=session_id)
        conf = [x for x in conf if "الفوج" not in x and "محجوب" not in x]
        if conf and not force:
            from .timetables import ConflictError
            raise ConflictError(conf)
    with db.tx():
        db.execute("UPDATE sessions SET substitute_id=? WHERE id=?", (substitute_id, session_id))
        db.log("تعيين مستخلف" if substitute_id else "إلغاء الاستخلاف", "sessions", session_id,
               {"original": s["teacher_id"], "substitute": substitute_id})


def current_absences(db: Database, today) -> list[dict]:
    d = iso(to_date(today))
    return [dict(r) for r in db.q("""SELECT a.*, t.full_name FROM absences a JOIN teachers t ON t.id=a.teacher_id
                                     WHERE a.start_date<=? AND a.end_date>=? ORDER BY a.end_date""", (d, d))]
