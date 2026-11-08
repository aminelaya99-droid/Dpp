"""أدوات المخطط الأسبوعي (بلا واجهة):

* needs: ما ينقص القسم هذا الأسبوع (المطلوب حسب الحجم الساعي أو أولويات الأسبوع، الموضوع، الباقي).
* place_first: وضع مادة في أول وقت متاح للقسم والأستاذ.
* day_summary: ساعات الدراسة لكل يوم وهل فيه غداء (قاعدة 7 ساعات + ساعة غداء).
* lock / unlock: الحصة المقفلة لا تحركها البرمجة الآلية (manual=1).
* swap: تبديل وقتي حصتين.
* أسبوع نموذجي لقسم: حفظه ثم تطبيقه على أي أسبوع (تُتجاوز الخانات المتعارضة).
* copy_day: نسخ حصص يوم إلى يوم آخر.
* check_week: فحص قبل الطباعة (تعارضات، حصص بلا أستاذ، أيام أطول من المسموح أو بلا غداء، نقص الساعات).
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

from ..db.database import Database
from ..utils import DAY_NAMES, hm_range, iso, to_date, week_start


def _week_sessions(db: Database, section_id: int, ws) -> list[dict]:
    ws = week_start(to_date(ws))
    return [dict(r) for r in db.q("""SELECT DISTINCT s.*, sub.name sname, COALESCE(sub.kind,'teach') kind
                                     FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                                     JOIN groups_ g ON g.id=sg.group_id JOIN subjects sub ON sub.id=s.subject_id
                                     WHERE g.section_id=? AND s.date BETWEEN ? AND ?
                                     AND s.status IN ('planned','done')""",
                                  (section_id, iso(ws), iso(ws + timedelta(days=6))))]


def needs(db: Database, section_id: int, ws, use_priorities: bool = True) -> list[dict]:
    """[{subject_id, subject, need, placed, left, req, mins, teacher, reason}] مرتبة بالأكثر نقصاً."""
    ws = week_start(to_date(ws))
    fid = db.scalar("SELECT formation_id FROM sections WHERE id=?", (section_id,))
    reqs = [dict(r) for r in db.q("""SELECT r.*, s.name sname FROM requirements r JOIN groups_ g ON g.id=r.group_id
                                     JOIN subjects s ON s.id=r.subject_id WHERE g.section_id=? AND g.is_whole=1""",
                                  (section_id,))]
    plan = {}
    if use_priorities and fid:
        from . import priorities as PRI
        cfg = PRI.load(db)
        if cfg.get("enabled"):
            groups = [r[0] for r in db.q("SELECT id FROM groups_ WHERE section_id=?", (section_id,))]
            _h, rows = PRI.week_plan(db, fid, ws, groups, cfg, create_missing=False)
            plan = {r["req"]: r for r in rows}
    placed = defaultdict(float)
    for s in _week_sessions(db, section_id, ws):
        placed[s["subject_id"]] += (s["end_min"] - s["start_min"]) / 60
    out = []
    for r in reqs:
        p = plan.get(r["id"])
        need = float(p["hours"]) if p else float(r["weekly_hours"] or 0)
        got = round(placed.get(r["subject_id"], 0.0), 2)
        out.append({"subject_id": r["subject_id"], "subject": r["sname"], "need": round(need, 2), "placed": got,
                    "left": round(max(0.0, need - got), 2), "req": r["id"], "mins": r["session_minutes"] or 120,
                    "teacher": r["teacher_id"], "reason": p["reason"] if p else "الحجم الساعي الأسبوعي"})
    out.sort(key=lambda x: (-x["left"], x["subject"]))
    return out


def place_first(db: Database, section_id: int, ws, subject_id: int, minutes: int, teacher: int | None = None):
    """يضع المادة في أول وقت متاح (القسم والأستاذ متفرغان). يعيد (sid، الوصف) أو (None، السبب)."""
    from .grid import TrayItem, WeekGrid
    g = WeekGrid(db, ws)
    r = db.one("SELECT id, name, short, color, COALESCE(category,'specialty') cat, COALESCE(kind,'teach') kind, "
               "shareable FROM subjects WHERE id=?", (subject_id,))
    if not r:
        return None, "المادة غير موجودة"
    it = TrayItem(f"pf{subject_id}", None, subject_id, r["name"], r["short"] or r["name"], r["color"] or "#CCC",
                  r["cat"], None, "", int(minutes), set(), shareable=bool(r["shareable"]), kind=r["kind"], free=True)
    slots = g.suggest_slots(it, section_id, limit=1, teacher=teacher)
    if not slots:
        return None, "لا يوجد وقت متاح هذا الأسبوع (القسم أو الأستاذ مشغول)"
    sl = slots[0]
    sid = g.place_free(it, section_id, sl["teacher"], sl["day"], sl["start"], sl["end"])
    return sid, f"{DAY_NAMES[(sl['day'].weekday() + 1) % 7]} {hm_range(sl['start'], sl['end'])}"


def day_summary(db: Database, section_id: int, ws, day_hours: float = 7.0) -> list[dict]:
    ws = week_start(to_date(ws))
    rows = _week_sessions(db, section_id, ws)
    out = []
    for i in range(7):
        d = ws + timedelta(days=i)
        day = [r for r in rows if r["date"] == iso(d)]
        study = sum(r["end_min"] - r["start_min"] for r in day if r["kind"] != "nonteach") / 60
        lunch = any("غذاء" in r["sname"] or "غداء" in r["sname"] for r in day)
        full = any(r["end_min"] - r["start_min"] >= 420 for r in day)
        state = "ok"
        if study > day_hours + 0.01:
            state = "over"
        elif study and not lunch and not full:
            state = "nolunch"
        out.append({"day": d, "study": round(study, 2), "lunch": lunch or full, "n": len(day), "state": state})
    return out


def set_lock(db: Database, session_ids: list[int], locked: bool) -> None:
    with db.tx():
        for sid in session_ids:
            db.execute("UPDATE sessions SET manual=? WHERE id=?", (int(locked), sid))
            db.log("قفل حصة" if locked else "فتح حصة", "sessions", sid)


def swap(db: Database, a: int, b: int) -> None:
    """تبديل وقتي حصتين (التاريخ والبداية والنهاية)."""
    ra = db.one("SELECT date, start_min, end_min FROM sessions WHERE id=?", (a,))
    rb = db.one("SELECT date, start_min, end_min FROM sessions WHERE id=?", (b,))
    if not ra or not rb:
        raise ValueError("الحصة غير موجودة.")
    with db.tx():
        db.execute("UPDATE sessions SET date=?, start_min=?, end_min=?, manual=1 WHERE id=?",
                   (rb["date"], rb["start_min"], rb["start_min"] + ra["end_min"] - ra["start_min"], a))
        db.execute("UPDATE sessions SET date=?, start_min=?, end_min=?, manual=1 WHERE id=?",
                   (ra["date"], ra["start_min"], ra["start_min"] + rb["end_min"] - rb["start_min"], b))
        db.log("تبديل حصتين", "sessions", a, {"with": b})


# ------------------------------------------------------------------ الأسبوع النموذجي
def save_template(db: Database, section_id: int, ws) -> int:
    ws = week_start(to_date(ws))
    items = []
    for s in _week_sessions(db, section_id, ws):
        groups = [r[0] for r in db.q("SELECT group_id FROM session_groups WHERE session_id=?", (s["id"],))]
        items.append({"wd": (to_date(s["date"]) - ws).days, "start": s["start_min"], "end": s["end_min"],
                      "subject": s["subject_id"], "teacher": s["teacher_id"], "room": s["room_id"], "groups": groups,
                      "req": s["requirement_id"]})
    st = _templates(db)
    st[str(section_id)] = {"from": iso(ws), "items": items}
    db.set_setting("week_templates", json.dumps(st, ensure_ascii=False))
    return len(items)


def _templates(db: Database) -> dict:
    try:
        return json.loads(db.get_setting("week_templates", "") or "{}")
    except ValueError:
        return {}


def template_info(db: Database, section_id: int) -> dict | None:
    return _templates(db).get(str(section_id))


def apply_template(db: Database, section_id: int, ws) -> tuple[int, list[str]]:
    """يضع حصص الأسبوع النموذجي في الأسبوع المحدد؛ الخانة المتعارضة تُتجاوز مع ذكر السبب."""
    from . import timetables as T
    tpl = template_info(db, section_id)
    if not tpl:
        raise ValueError("لا يوجد أسبوع نموذجي محفوظ لهذا القسم.")
    ws = week_start(to_date(ws))
    fid = db.scalar("SELECT formation_id FROM sections WHERE id=?", (section_id,))
    tt = T.get_or_create_timetable(db, fid, ws)
    n, skipped = 0, []
    for it in tpl["items"]:
        d = ws + timedelta(days=int(it["wd"]))
        try:
            T.create_session(db, tt, d, it["start"], it["end"], it["subject"], it["teacher"], it["room"],
                             it["groups"], it.get("req"))
            n += 1
        except T.ConflictError as e:
            skipped.append(f"{DAY_NAMES[int(it['wd'])]} {hm_range(it['start'], it['end'])}: {e.conflicts[0]}")
        except ValueError as e:
            skipped.append(f"{DAY_NAMES[int(it['wd'])]} {hm_range(it['start'], it['end'])}: {e}")
    return n, skipped


def copy_day(db: Database, section_id: int, src, dst) -> tuple[int, list[str]]:
    from . import timetables as T
    src, dst = to_date(src), to_date(dst)
    fid = db.scalar("SELECT formation_id FROM sections WHERE id=?", (section_id,))
    tt = T.get_or_create_timetable(db, fid, dst)
    n, skipped = 0, []
    for s in [x for x in _week_sessions(db, section_id, src) if x["date"] == iso(src)]:
        groups = [r[0] for r in db.q("SELECT group_id FROM session_groups WHERE session_id=?", (s["id"],))]
        try:
            T.create_session(db, tt, dst, s["start_min"], s["end_min"], s["subject_id"], s["teacher_id"], s["room_id"],
                             groups, s["requirement_id"])
            n += 1
        except (T.ConflictError, ValueError) as e:
            msg = e.conflicts[0] if isinstance(e, T.ConflictError) else str(e)
            skipped.append(f"{s['sname']} {hm_range(s['start_min'], s['end_min'])}: {msg}")
    return n, skipped


# ------------------------------------------------------------------ فحص قبل الطباعة
def check_week(db: Database, section_ids: list[int], ws, day_hours: float = 7.0) -> list[tuple[str, str]]:
    """[(الخطورة، الرسالة)] للأقسام المحددة في الأسبوع."""
    from .grid import WeekGrid
    ws = week_start(to_date(ws))
    g = WeekGrid(db, ws)
    out = []
    secs = set(section_ids)
    for c in g.conflicts:
        if c.ignored:
            continue
        if any(set(g.cards[s].sections) & secs for s in c.session_ids if s in g.cards):
            out.append(("عالية", f"تعارض: {c.message}"))
    for c in g.cards.values():
        if set(c.sections) & secs and not c.teacher and c.kind != "nonteach" and c.status == "planned":
            out.append(("متوسطة", f"حصة بلا أستاذ: {c.sname} — {', '.join(g.sec_by_id[s].short for s in c.sections if s in g.sec_by_id)} "
                                  f"{DAY_NAMES[c.wd]} {hm_range(c.start, c.end)}"))
    for sid in section_ids:
        name = g.sec_by_id[sid].short if sid in g.sec_by_id else str(sid)
        for d in day_summary(db, sid, ws, day_hours):
            if d["state"] == "over":
                out.append(("متوسطة", f"{name}: يوم {DAY_NAMES[(d['day'].weekday() + 1) % 7]} فيه {d['study']:g} سا دراسة "
                                      f"(أكثر من {day_hours:g})"))
            elif d["state"] == "nolunch":
                out.append(("منخفضة", f"{name}: يوم {DAY_NAMES[(d['day'].weekday() + 1) % 7]} بلا بطاقة غداء"))
        short = [n for n in needs(db, sid, ws) if n["left"] >= 1]
        if short:
            out.append(("منخفضة", f"{name}: ساعات ناقصة هذا الأسبوع: " +
                        "، ".join(f"{n['subject']} {n['left']:g} سا" for n in short[:5])))
    return out
