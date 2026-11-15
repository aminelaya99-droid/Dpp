"""الجداول والحصص: الحفظ، الاعتماد، النسخ، التعديل اليدوي، فحص التعارضات، التخطيط الكامل."""
from __future__ import annotations

from typing import TYPE_CHECKING

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..db.database import Database
if TYPE_CHECKING:                       # الاستيراد كسول: محرك OR-Tools ثقيل وغير متوفر
    from ..scheduler.engine import ScheduleResult, Scheduler   # noqa: F401
from ..utils import STATUS_LABELS, hm, iso, to_date, week_days, week_start, weeks_between
from .calendar import blocked_dates, teaching_days


class ConflictError(Exception):
    def __init__(self, conflicts: list[str]):
        super().__init__("\n".join(conflicts))
        self.conflicts = conflicts


# ------------------------------------------------------------------ أساسيات
def get_or_create_timetable(db: Database, formation_id: int, ws) -> int:
    ws = iso(week_start(ws))
    r = db.one("SELECT id FROM timetables WHERE formation_id=? AND week_start=? ORDER BY version DESC LIMIT 1",
               (formation_id, ws))
    if r:
        return r["id"]
    return db.insert("timetables", formation_id=formation_id, week_start=ws, status="draft")


def timetable_status(db: Database, tt_id: int) -> str:
    return db.scalar("SELECT status FROM timetables WHERE id=?", (tt_id,), "draft")


def session_groups(db: Database, session_id: int) -> list[int]:
    return [r[0] for r in db.q("SELECT group_id FROM session_groups WHERE session_id=?", (session_id,))]


def _group_units(db: Database) -> dict[int, set[int]]:
    """لكل فوج: مجموعة الأفواج الذرية التي يغطيها (الفوج الكامل = كل مجموعاته)."""
    rows = db.q("SELECT id, section_id, is_whole FROM groups_")
    subs = defaultdict(set)
    for r in rows:
        if not r["is_whole"]:
            subs[r["section_id"]].add(r["id"])
    out = {}
    for r in rows:
        out[r["id"]] = set(subs[r["section_id"]]) if (r["is_whole"] and subs[r["section_id"]]) else {r["id"]}
    return out


def check_conflicts(db: Database, day, start_min: int, end_min: int, teacher_id: int | None,
                    room_id: int | None, group_ids: list[int], subject_id: int | None = None,
                    ignore_session: int | None = None) -> list[str]:
    """يعيد قائمة التعارضات (فارغة = لا تعارض)."""
    out = []
    day = to_date(day)
    if end_min <= start_min:
        out.append("وقت النهاية يجب أن يكون بعد وقت البداية.")
    ds, de = db.get_int("day_start"), db.get_int("day_end")
    if start_min < ds or end_min > de:
        out.append(f"الحصة خارج ساعات الدراسة ({hm(ds)} – {hm(de)}).")
    if teacher_id and subject_id:
        ok = db.scalar("SELECT COUNT(*) FROM teacher_subjects WHERE teacher_id=? AND subject_id=?",
                       (teacher_id, subject_id), 0)
        if not ok:
            out.append("الأستاذ غير مؤهل لتدريس هذه المادة.")
    if teacher_id:
        ab = db.one("SELECT reason FROM absences WHERE teacher_id=? AND start_date<=? AND end_date>=?",
                    (teacher_id, iso(day), iso(day)))
        if ab:
            out.append(f"الأستاذ غائب في هذا اليوم ({ab['reason']}).")
    rows = db.q("""SELECT s.*, sub.name AS sname, sub.shareable FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                   WHERE s.date=? AND s.status IN ('planned','done') AND s.start_min<? AND s.end_min>?
                   AND (? IS NULL OR s.id<>?)""",
                (iso(day), end_min, start_min, ignore_session, ignore_session))
    units = _group_units(db)
    mine = set().union(*(units.get(g, {g}) for g in group_ids)) if group_ids else set()
    for r in rows:
        when = f"{hm(r['start_min'])}–{hm(r['end_min'])}"
        other_t = r["substitute_id"] or r["teacher_id"]
        if teacher_id and other_t == teacher_id:
            out.append(f"الأستاذ لديه حصة «{r['sname']}» في {when}.")
        if room_id and r["room_id"] == room_id:
            out.append(f"القاعة مشغولة بحصة «{r['sname']}» في {when}.")
        others = set().union(*(units.get(g, {g}) for g in session_groups(db, r["id"])) or [set()])
        if mine & others:
            out.append(f"الفوج لديه حصة «{r['sname']}» في {when}.")
    if db.scalar("SELECT COUNT(*) FROM calendar_events WHERE blocks_scheduling=1 AND start_date<=? AND end_date>=?",
                 (iso(day), iso(day)), 0):
        out.append("هذا اليوم محجوب في الرزنامة (عطلة/امتحان/توقف).")
    return out


def create_session(db: Database, timetable_id: int | None, day, start_min: int, end_min: int,
                   subject_id: int, teacher_id: int | None, room_id: int | None, group_ids: list[int],
                   requirement_id: int | None = None, manual=True, force=False, is_makeup=False,
                   makeup_of: int | None = None, note: str = "") -> int:
    conflicts = check_conflicts(db, day, start_min, end_min, teacher_id, room_id, group_ids, subject_id)
    if conflicts and not force:
        raise ConflictError(conflicts)
    if timetable_id and timetable_status(db, timetable_id) == "approved" and not force:
        raise ConflictError(["الجدول معتمد؛ أعد فتحه كمسودة قبل التعديل."])
    with db.tx():
        sid = db.insert("sessions", timetable_id=timetable_id, requirement_id=requirement_id, date=iso(to_date(day)),
                        start_min=start_min, end_min=end_min, subject_id=subject_id, teacher_id=teacher_id,
                        room_id=room_id, manual=int(manual), is_makeup=int(is_makeup), makeup_of=makeup_of, note=note)
        for g in group_ids:
            db.execute("INSERT INTO session_groups VALUES (?,?)", (sid, g))
        db.log("إنشاء حصة", "sessions", sid, {"date": iso(to_date(day)), "from": hm(start_min), "to": hm(end_min),
                                               "makeup": is_makeup})
    return sid


def update_session(db: Database, session_id: int, force=False, **fields):
    s = db.one("SELECT * FROM sessions WHERE id=?", (session_id,))
    if not s:
        raise ValueError("الحصة غير موجودة.")
    if s["timetable_id"] and timetable_status(db, s["timetable_id"]) == "approved" and not force \
            and set(fields) - {"status", "substitute_id", "note"}:
        raise ConflictError(["الجدول معتمد؛ أعد فتحه كمسودة قبل نقل الحصص أو تعديلها."])
    new = dict(s) | fields
    if {"date", "start_min", "end_min", "teacher_id", "room_id"} & set(fields):
        c = check_conflicts(db, new["date"], new["start_min"], new["end_min"], new["teacher_id"], new["room_id"],
                            session_groups(db, session_id), new["subject_id"], ignore_session=session_id)
        if c and not force:
            raise ConflictError(c)
    with db.tx():
        db.update("sessions", session_id, manual=1, **fields)
        db.log("تعديل حصة", "sessions", session_id, {k: (s[k], v) for k, v in fields.items()})


def set_status(db: Database, session_id: int, status: str, note: str = ""):
    if status not in STATUS_LABELS:
        raise ValueError("حالة غير معروفة.")
    with db.tx():
        db.execute("UPDATE sessions SET status=?, note=COALESCE(NULLIF(?,''), note) WHERE id=?", (status, note, session_id))
        db.log(f"تسجيل الحصة: {STATUS_LABELS[status]}", "sessions", session_id)


def delete_session(db: Database, session_id: int):
    s = db.one("SELECT timetable_id FROM sessions WHERE id=?", (session_id,))
    if s and s["timetable_id"] and timetable_status(db, s["timetable_id"]) == "approved":
        raise ConflictError(["لا يمكن حذف حصة من جدول معتمد."])
    with db.tx():
        db.execute("DELETE FROM sessions WHERE id=?", (session_id,))
        db.log("حذف حصة", "sessions", session_id)


def create_makeup(db: Database, session_id: int, day, start_min: int, end_min: int | None = None,
                  room_id: int | None = None, force=False) -> int:
    """حصة تعويضية لحصة مؤجلة/ملغاة. الأصلية لا تُحتسب، والتعويضية تُحتسب مرة واحدة."""
    s = db.one("SELECT * FROM sessions WHERE id=?", (session_id,))
    if s["status"] not in ("postponed", "cancelled"):
        raise ValueError("يجب تسجيل الحصة الأصلية كمؤجلة أو ملغاة قبل إنشاء حصة تعويضية.")
    if db.scalar("SELECT COUNT(*) FROM sessions WHERE makeup_of=? AND status<>'cancelled'", (session_id,), 0):
        raise ValueError("توجد حصة تعويضية لهذه الحصة بالفعل.")
    end_min = end_min or start_min + (s["end_min"] - s["start_min"])
    tt = get_or_create_timetable(db, db.scalar("SELECT formation_id FROM timetables WHERE id=?", (s["timetable_id"],))
                                 or db.scalar("SELECT id FROM formations LIMIT 1"), day)
    return create_session(db, tt, day, start_min, end_min, s["subject_id"], s["teacher_id"], room_id or s["room_id"],
                          session_groups(db, session_id), s["requirement_id"], manual=True, force=force,
                          is_makeup=True, makeup_of=session_id)


# ------------------------------------------------------------------ حفظ نتيجة المحرك
def save_result(db: Database, formation_id: int, result: ScheduleResult, replace_generated=True, from_date=None) -> int:
    tt = get_or_create_timetable(db, formation_id, result.week_start)
    if timetable_status(db, tt) == "approved":
        raise ConflictError(["الجدول معتمد؛ لا يمكن استبداله تلقائياً. أنشئ نسخة جديدة أو أعد فتحه كمسودة."])
    with db.tx():
        if replace_generated:
            db.execute("DELETE FROM sessions WHERE timetable_id=? AND manual=0 AND status='planned' AND date>=?",
                       (tt, iso(to_date(from_date)) if from_date else "0000-00-00"))
        for p in result.placements:
            sid = db.insert("sessions", timetable_id=tt, requirement_id=p.meeting.requirement_ids[0],
                            date=iso(p.day), start_min=p.start_min, end_min=p.end_min,
                            subject_id=p.meeting.subject_id, teacher_id=p.meeting.teacher_id, room_id=p.room_id,
                            manual=0)
            for g in p.meeting.group_ids:
                db.execute("INSERT INTO session_groups VALUES (?,?)", (sid, g))
            # حصة مشتركة: نربط كل متطلب بالحصة عبر جدول الأفواج؛ requirement_id يحمل الأول فقط
        db.update("timetables", tt, note=result.summary())
        db.log("حفظ جدول مولد", "timetables", tt, {"placed": len(result.placements), "unplaced": len(result.unplaced)})
    return tt


def snapshot(db: Database, tt_id: int, label: str) -> int:
    rows = []
    for s in db.q("SELECT * FROM sessions WHERE timetable_id=?", (tt_id,)):
        d = dict(s)
        d["groups"] = session_groups(db, s["id"])
        rows.append(d)
    return db.insert("timetable_snapshots", timetable_id=tt_id, label=label,
                     data=json.dumps(rows, ensure_ascii=False))


def restore_snapshot(db: Database, snap_id: int):
    snap = db.one("SELECT * FROM timetable_snapshots WHERE id=?", (snap_id,))
    tt = snap["timetable_id"]
    if timetable_status(db, tt) == "approved":
        raise ConflictError(["أعد فتح الجدول كمسودة قبل الرجوع إلى نسخة سابقة."])
    rows = json.loads(snap["data"])
    with db.tx():
        snapshot(db, tt, "قبل الاستعادة")
        db.execute("DELETE FROM sessions WHERE timetable_id=?", (tt,))
        for r in rows:
            groups = r.pop("groups")
            r.pop("id")
            r["makeup_of"] = None
            sid = db.insert("sessions", **r)
            for g in groups:
                db.execute("INSERT INTO session_groups VALUES (?,?)", (sid, g))
        db.log("استعادة نسخة جدول", "timetables", tt, {"snapshot": snap_id})


def approve(db: Database, tt_id: int):
    with db.tx():
        snapshot(db, tt_id, "عند الاعتماد")
        db.execute("UPDATE timetables SET status='approved' WHERE id=?", (tt_id,))
        db.log("اعتماد جدول", "timetables", tt_id)


def reopen(db: Database, tt_id: int):
    with db.tx():
        db.execute("UPDATE timetables SET status='draft', version=version+1 WHERE id=?", (tt_id,))
        db.log("إعادة فتح جدول كمسودة", "timetables", tt_id)


def copy_week(db: Database, formation_id: int, src_ws, dst_ws, force=False) -> tuple[int, list[str]]:
    """ينسخ حصص أسبوع إلى أسبوع آخر كحصص جديدة مستقلة بحالة "مبرمجة"."""
    src = get_or_create_timetable(db, formation_id, src_ws)
    dst = get_or_create_timetable(db, formation_id, dst_ws)
    if timetable_status(db, dst) == "approved":
        raise ConflictError(["الأسبوع الهدف معتمد."])
    shift = (week_start(dst_ws) - week_start(src_ws)).days
    blocked = blocked_dates(db, formation_id, week_start(dst_ws), week_start(dst_ws) + timedelta(days=6))
    skipped, n = [], 0
    for s in db.q("SELECT * FROM sessions WHERE timetable_id=? AND is_makeup=0 AND status<>'cancelled'", (src,)):
        nd = to_date(s["date"]) + timedelta(days=shift)
        if nd in blocked:
            skipped.append(f"{iso(nd)} {hm(s['start_min'])}: يوم محجوب")
            continue
        try:
            create_session(db, dst, nd, s["start_min"], s["end_min"], s["subject_id"], s["teacher_id"], s["room_id"],
                           session_groups(db, s["id"]), s["requirement_id"], manual=bool(s["manual"]), force=force)
            n += 1
        except ConflictError as e:
            skipped.append(f"{iso(nd)} {hm(s['start_min'])}: {e.conflicts[0]}")
    return n, skipped


def compare_weeks(db: Database, formation_id: int, ws_a, ws_b) -> dict:
    def load(ws):
        tt = get_or_create_timetable(db, formation_id, ws)
        out = defaultdict(float)
        for r in db.q("""SELECT sub.name, SUM(s.end_min-s.start_min) m FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                         WHERE s.timetable_id=? AND s.status<>'cancelled' GROUP BY sub.name""", (tt,)):
            out[r["name"]] = r["m"] / 60
        return out
    a, b = load(ws_a), load(ws_b)
    return {k: (a.get(k, 0), b.get(k, 0)) for k in sorted(set(a) | set(b))}


# ------------------------------------------------------------------ التخطيط لكامل فترة التكوين
@dataclass
class PeriodPlan:
    weeks: list[tuple[date, ScheduleResult, int | None]] = field(default_factory=list)
    carried_over: dict[int, float] = field(default_factory=dict)  # ساعات لم تُبرمج حتى نهاية الفترة
    messages: list[str] = field(default_factory=list)

    @property
    def placed(self) -> int:
        return sum(len(r.placements) for _, r, _ in self.weeks)


def distribute_hours(db: Database, formation_id: int, start=None, end=None) -> dict[date, dict[int, float]]:
    """توزيع الحجم الساعي المتبقي لكل متطلب على الأسابيع بالتناسب مع أيام الدراسة."""
    f = db.one("SELECT * FROM formations WHERE id=?", (formation_id,))
    s, e = to_date(start or f["start_date"]), to_date(end or f["end_date"])
    weeks = weeks_between(s, e)
    days_per_week = {w: len([d for d in teaching_days(db, formation_id, max(w, s), min(w + timedelta(days=6), e))])
                     for w in weeks}
    total_days = sum(days_per_week.values()) or 1
    plan: dict[date, dict[int, float]] = {w: {} for w in weeks}
    for r in db.q("SELECT * FROM requirements WHERE formation_id=?", (formation_id,)):
        kept = (db.scalar("""SELECT SUM(s.end_min-s.start_min) FROM sessions s
                             JOIN session_groups sg ON sg.session_id=s.id
                             LEFT JOIN timetables t ON t.id=s.timetable_id
                             WHERE sg.group_id=? AND s.subject_id=? AND s.status IN ('planned','done')
                             AND (s.date<? OR s.date>? OR s.manual=1 OR s.status='done' OR t.status='approved')""",
                          (r["group_id"], r["subject_id"], iso(s), iso(e)), 0) or 0) / 60
        done = kept
        remaining = max(0.0, (r["total_hours"] or 0) - done)
        if remaining <= 0:
            continue
        unit = (r["session_minutes"] or 120) / 60 if r["session_minutes"] else 6.0
        cum, given = 0.0, 0.0
        for w in weeks:
            cum += remaining * days_per_week[w] / total_days
            target = math.floor(cum / unit + 1e-9) * unit
            h = min(target - given, remaining - given)
            if r["weekly_hours"]:
                h = min(h, max(r["weekly_hours"], unit))
            if h > 0:
                plan[w][r["id"]] = h
                given += h
        if remaining - given > 1e-6:   # البقية: أضفها للأسابيع الأخيرة التي فيها أيام
            for w in reversed(weeks):
                if days_per_week[w] and remaining - given > 1e-6:
                    add = min(unit, remaining - given)
                    plan[w][r["id"]] = plan[w].get(r["id"], 0) + add
                    given += add
    return plan


def plan_period(db: Database, formation_id: int, start=None, end=None, time_limit=20.0,
                progress=None, save=True) -> PeriodPlan:
    plan = distribute_hours(db, formation_id, start, end)
    f = db.one("SELECT start_date FROM formations WHERE id=?", (formation_id,))
    start_d = to_date(start or f["start_date"])
    out = PeriodPlan()
    carry: dict[int, float] = defaultdict(float)
    from ..scheduler.engine import Scheduler
    sched = Scheduler(db, time_limit=time_limit)
    weeks = sorted(plan)
    for i, w in enumerate(weeks):
        if progress:
            progress(i, len(weeks), w)
        hours = defaultdict(float, plan[w])
        for rid, h in carry.items():
            hours[rid] += h
        carry = defaultdict(float)
        tt = db.one("SELECT id, status FROM timetables WHERE formation_id=? AND week_start=?", (formation_id, iso(w)))
        if tt and tt["status"] == "approved":
            out.messages.append(f"أسبوع {iso(w)} معتمد؛ لم يُعدّل.")
            from ..scheduler.engine import ScheduleResult
            out.weeks.append((w, ScheduleResult(week_start=w, status="APPROVED"), tt["id"]))
            continue
        if not hours:
            continue
        res = sched.schedule_week(formation_id, w, hours_override=dict(hours),
                                  exclude_timetable=tt["id"] if tt else None, subtract_existing=False,
                                  from_date=start_d)
        for u in res.unplaced:
            mins = u.meeting.minutes or (db.get_int("day_end") - db.get_int("day_start"))
            for rid in u.meeting.requirement_ids[:1]:
                carry[rid] += mins / 60
        tt_id = save_result(db, formation_id, res, from_date=start_d) if save and res.placements else (tt["id"] if tt else None)
        out.weeks.append((w, res, tt_id))
    out.carried_over = {k: v for k, v in carry.items() if v > 0}
    if out.carried_over:
        out.messages.append(f"بقيت {sum(out.carried_over.values()):g} ساعة دون برمجة بنهاية الفترة.")
    return out


def reschedule_after_calendar_change(db: Database, formation_id: int, apply=True) -> dict:
    """بعد تعديل الرزنامة: الحصص الواقعة في أيام أصبحت محجوبة.

    - حصص المسودات المولدة آلياً: تُحذف وتُعاد برمجة ساعاتها في الأسابيع اللاحقة.
    - حصص الجداول المعتمدة أو اليدوية: لا تُلمس، وتُعاد كقائمة تحتاج موافقة المستخدم.
    """
    f = db.one("SELECT * FROM formations WHERE id=?", (formation_id,))
    s, e = to_date(f["start_date"]), to_date(f["end_date"])
    blocked = blocked_dates(db, formation_id, s, e)
    rows = db.q("""SELECT s.*, t.status AS tstatus FROM sessions s JOIN timetables t ON t.id=s.timetable_id
                   WHERE t.formation_id=? AND s.status='planned'""", (formation_id,))
    auto, needs_confirm = [], []
    for r in rows:
        if to_date(r["date"]) in blocked:
            (needs_confirm if (r["tstatus"] == "approved" or r["manual"]) else auto).append(r)
    result = {"removed": len(auto), "needs_confirmation": [dict(r) for r in needs_confirm], "plan": None}
    if apply and auto:
        with db.tx():
            for r in auto:
                db.execute("DELETE FROM sessions WHERE id=?", (r["id"],))
            db.log("إعادة برمجة بعد تعديل الرزنامة", "formations", formation_id, {"removed": len(auto)})
        first = min(to_date(r["date"]) for r in auto)
        result["plan"] = plan_period(db, formation_id, start=max(first, s), end=e)
    return result
