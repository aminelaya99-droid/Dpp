"""الرزنامة: الأحداث، الأيام المحظورة، التنبيهات والعد التنازلي."""
from __future__ import annotations

from datetime import date, timedelta

from ..db.database import Database
from ..utils import iso, parse_rest_days, to_date, weekday_sun0

EVENT_KINDS = {
    "holiday": "عطلة رسمية", "inst_holiday": "عطلة مؤسساتية", "break": "فترة راحة/توقف",
    "exam": "امتحان دوري", "final_exam": "امتحان نهائي", "evaluation": "تقييم",
    "graduation": "حفل تخرج", "meeting": "اجتماع", "report": "تسليم تقرير",
    "admin": "موعد إداري", "phase": "مرحلة تكوين", "custom": "حدث مخصص",
    "duty": "خفارة", "service": "خدمة", "field": "تمرين ميداني", "full_day": "يوم كامل (عام)",
}
BLOCKING_KINDS = {"holiday", "inst_holiday", "break", "exam", "final_exam", "graduation", "duty", "service", "field",
                  "full_day"}


def add_event(db: Database, title: str, kind: str, start, end=None, formation_id=None, section_id=None,
              description="", importance=1, blocks=None, remind_days="7,3,1") -> int:
    if kind not in EVENT_KINDS:
        raise ValueError("نوع الحدث غير معروف.")
    s, e = to_date(start), to_date(end or start)
    if e < s:
        raise ValueError("تاريخ النهاية يسبق تاريخ البداية.")
    if blocks is None:
        blocks = kind in BLOCKING_KINDS
    with db.tx():
        eid = db.insert("calendar_events", title=title, kind=kind, start_date=iso(s), end_date=iso(e),
                        formation_id=formation_id, section_id=section_id, description=description,
                        importance=importance, blocks_scheduling=int(bool(blocks)), remind_days=remind_days)
        db.log("إضافة حدث", "calendar_events", eid, {"title": title, "kind": kind, "from": iso(s), "to": iso(e)})
    return eid


def set_event_sections(db: Database, event_id: int, section_ids: list[int]) -> None:
    """الأقسام المعنية بالحدث (فارغة = كل أقسام التكوين المحدد، أو كل التكوينات)."""
    with db.tx():
        db.execute("DELETE FROM calendar_event_sections WHERE event_id=?", (event_id,))
        for sid in section_ids:
            db.execute("INSERT OR IGNORE INTO calendar_event_sections VALUES (?,?)", (event_id, sid))


def event_sections(db: Database, event_id: int) -> list[int]:
    return [r[0] for r in db.q("SELECT section_id FROM calendar_event_sections WHERE event_id=?", (event_id,))]


def attendees_label(db: Database, event_id: int, formation_name: str | None = None) -> str:
    rows = db.q("""SELECT s.short FROM calendar_event_sections x JOIN sections s ON s.id=x.section_id
                   LEFT JOIN levels l ON l.id=s.level_id WHERE x.event_id=? ORDER BY COALESCE(l.sort,99), s.sort, s.id""",
                (event_id,))
    if not rows:
        return formation_name or "كل التكوينات"
    names = [r[0] for r in rows]
    return f"{len(names)} قسم: " + "، ".join(names[:6]) + ("…" if len(names) > 6 else "")


def update_event(db: Database, event_id: int, **fields):
    with db.tx():
        db.update("calendar_events", event_id, **fields)
        db.log("تعديل حدث", "calendar_events", event_id, fields)


def delete_event(db: Database, event_id: int):
    with db.tx():
        db.execute("DELETE FROM calendar_events WHERE id=?", (event_id,))
        db.log("حذف حدث", "calendar_events", event_id)


def blocked_dates(db: Database, formation_id: int, start, end, section_id=None) -> set[date]:
    """الأيام التي لا تجوز فيها البرمجة: أحداث حاجبة + أيام راحة التكوين."""
    s, e = to_date(start), to_date(end)
    out: set[date] = set()
    rows = db.q("""SELECT start_date, end_date FROM calendar_events e
                   WHERE blocks_scheduling=1 AND end_date>=? AND start_date<=?
                   AND (formation_id IS NULL OR formation_id=?)
                   AND (section_id IS NULL OR section_id=? OR ? IS NULL)
                   AND (NOT EXISTS (SELECT 1 FROM calendar_event_sections x WHERE x.event_id=e.id)
                        OR EXISTS (SELECT 1 FROM calendar_event_sections x JOIN sections sc ON sc.id=x.section_id
                                   WHERE x.event_id=e.id AND sc.formation_id=? AND (? IS NULL OR sc.id=?)))""",
                (iso(s), iso(e), formation_id, section_id, section_id, formation_id, section_id, section_id))
    for r in rows:
        d = max(to_date(r["start_date"]), s)
        last = min(to_date(r["end_date"]), e)
        while d <= last:
            out.add(d)
            d += timedelta(days=1)
    f = db.one("SELECT rest_days, start_date, end_date FROM formations WHERE id=?", (formation_id,))
    rest = parse_rest_days(f["rest_days"]) if f else set()
    d = s
    while d <= e:
        if weekday_sun0(d) in rest:
            out.add(d)
        if f and f["start_date"] and d < to_date(f["start_date"]):
            out.add(d)
        if f and f["end_date"] and d > to_date(f["end_date"]):
            out.add(d)
        d += timedelta(days=1)
    return out


def section_day_events(db: Database, start, end, section_ids: list[int]) -> dict:
    """الأحداث التي تأخذ اليوم كاملاً لكل قسم: {(قسم، تاريخ): [(العنوان، النوع)]}.
    الحدث بلا أقسام محددة يخص كل أقسام تكوينه (أو كل الأقسام). العطل الرسمية لا تُعرض هنا (لها أيام الراحة)."""
    s, e = to_date(start), to_date(end)
    out: dict = {}
    if not section_ids:
        return out
    secs = {r["id"]: r["formation_id"] for r in db.q(
        f"SELECT id, formation_id FROM sections WHERE id IN ({','.join('?' * len(section_ids))})", tuple(section_ids))}
    for ev in db.q("""SELECT * FROM calendar_events WHERE blocks_scheduling=1 AND end_date>=? AND start_date<=?""",
                   (iso(s), iso(e))):
        targets = event_sections(db, ev["id"])
        if not targets:
            targets = [sid for sid, f in secs.items() if (ev["section_id"] in (None, sid))
                       and (ev["formation_id"] in (None, f))]
        d = max(to_date(ev["start_date"]), s)
        last = min(to_date(ev["end_date"]), e)
        while d <= last:
            for sid in targets:
                if sid in secs:
                    out.setdefault((sid, d), []).append((ev["title"], ev["kind"]))
            d += timedelta(days=1)
    return out


def teaching_days(db: Database, formation_id: int, start, end) -> list[date]:
    s, e = to_date(start), to_date(end)
    blocked = blocked_dates(db, formation_id, s, e)
    out, d = [], s
    while d <= e:
        if d not in blocked:
            out.append(d)
        d += timedelta(days=1)
    return out


def upcoming(db: Database, today=None, horizon_days=60) -> list[dict]:
    today = to_date(today or date.today())
    rows = db.q("""SELECT e.*, f.name AS formation FROM calendar_events e
                   LEFT JOIN formations f ON f.id=e.formation_id
                   WHERE e.end_date>=? AND e.start_date<=? ORDER BY e.start_date""",
                (iso(today), iso(today + timedelta(days=horizon_days))))
    out = []
    for r in rows:
        d = dict(r)
        d["days_left"] = (to_date(r["start_date"]) - today).days
        d["kind_label"] = EVENT_KINDS.get(r["kind"], r["kind"])
        out.append(d)
    return out


def due_reminders(db: Database, today=None) -> list[dict]:
    """الأحداث التي يحل اليوم موعد تنبيهها (قبل الحدث بعدد الأيام المحدد)."""
    today = to_date(today or date.today())
    out = []
    for ev in upcoming(db, today, 400):
        left = ev["days_left"]
        days = {int(x) for x in (ev["remind_days"] or "").split(",") if x.strip().isdigit()}
        if left in days or left == 0:
            out.append(ev)
    return out
