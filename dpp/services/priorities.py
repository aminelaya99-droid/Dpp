"""أولويات البرمجة الآلية للأسبوع: تحدد كم ساعة يطلب المحرك لكل (فوج × مادة) هذا الأسبوع.

1. الأساس: الحجم الساعي الأسبوعي للمتطلب (requirements.weekly_hours).
2. المواد المتأخرة أولاً: المادة التي نسبة إنجازها أقل من متوسط قسمها تأخذ ساعات إضافية بقدر تأخرها
   (حسب «قوة الأولوية»)، والمتقدمة تتنازل عن جزء من ساعاتها، مع بقاء مجموع القسم كما هو تقريباً.
3. مواد محددة بساعات محددة: «قتال 6 سا هذا الأسبوع» لقسم أو طور أو اختصاص — تُفرض كما هي.
4. إنهاء مادة بتاريخ: الباقي من المقرر ÷ الأسابيع المتبقية حتى التاريخ.
5. قواعد اليوم (تُمرر للمحرك): ساعات الدراسة في اليوم، حد حصص نفس المادة في اليوم، ومواد في الصباح.

النتيجة: hours_override للمحرك + جدول «الخطة» يشرح لكل سطر من أين جاءت ساعاته.
الإعدادات محفوظة في auto_priorities (JSON).
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from datetime import date, timedelta

from ..db.database import Database
from ..utils import iso, to_date, week_start

KEY = "auto_priorities"
DEFAULTS = {
    "enabled": False,
    "late_first": True, "late_strength": 50,          # %
    "targets": [],        # [{"scope": "section|level|specialty", "ref": id, "subject": sid, "hours": h}]
    "deadlines": [],      # [{"scope", "ref", "subject", "date": "YYYY-MM-DD"}]
    "rules": {"day_hours": 7, "max_per_day": 2, "morning": [], "morning_end": 720},
}
SCOPE_LABELS = {"section": "قسم", "level": "طور", "specialty": "اختصاص"}


def load(db: Database) -> dict:
    o = json.loads(json.dumps(DEFAULTS))
    try:
        st = json.loads(db.get_setting(KEY, "") or "{}")
        o.update({k: v for k, v in st.items() if k != "rules"})
        o["rules"].update(st.get("rules") or {})
    except ValueError:
        pass
    return o


def save(db: Database, o: dict) -> None:
    db.set_setting(KEY, json.dumps(o, ensure_ascii=False))


def _sections(db: Database, formation_id: int) -> dict[int, dict]:
    return {r["id"]: dict(r) for r in db.q("""SELECT s.id, s.short, s.name, s.level_id, s.specialty_id FROM sections s
                                             WHERE s.formation_id=?""", (formation_id,))}


def matches(scope: str, ref, sec: dict) -> bool:
    return (scope == "section" and sec["id"] == ref) or (scope == "level" and sec["level_id"] == ref) \
        or (scope == "specialty" and sec["specialty_id"] == ref)


def _round(h: float, mins: int = 60) -> float:
    """تقريب إلى أقرب ساعة (المحرك يقسم الساعات إلى حصص بمدتها، والباقي حصة أقصر)."""
    if h <= 0.25:
        return 0.0
    return max(1.0, float(round(h)))


def week_plan(db: Database, formation_id: int, ws, group_ids: list[int] | None = None,
              cfg: dict | None = None, create_missing: bool = True) -> tuple[dict[int, float], list[dict]]:
    """(hours_override، خطة مفصلة). الخطة: سطر لكل متطلب فيه الأساس والمطلوب والسبب."""
    from .progress import simple_progress
    cfg = cfg or load(db)
    ws = week_start(to_date(ws))
    secs = _sections(db, formation_id)
    reqs = [dict(r) for r in db.q("""SELECT r.*, g.section_id, g.is_whole, s.name sname FROM requirements r
                                     JOIN groups_ g ON g.id=r.group_id JOIN subjects s ON s.id=r.subject_id
                                     WHERE r.formation_id=?""", (formation_id,))]
    if group_ids is not None:
        gs = set(group_ids)
        reqs = [r for r in reqs if r["group_id"] in gs]
    prog = {(r["section_id"], r["subject_id"]): r for r in simple_progress(db, [formation_id], ws)}
    plan: dict[int, dict] = {}
    for r in reqs:
        base = float(r["weekly_hours"] or 0)
        plan[r["id"]] = {"req": r["id"], "section_id": r["section_id"], "section": secs.get(r["section_id"], {}).get("short", ""),
                         "subject_id": r["subject_id"], "subject": r["sname"], "base": round(base, 2),
                         "hours": base, "reason": "الحجم الساعي الأسبوعي", "mins": r["session_minutes"] or 120,
                         "pct": (prog.get((r["section_id"], r["subject_id"])) or {}).get("pct")}

    # 2) المواد المتأخرة أولاً (داخل كل قسم، مجموع الساعات ثابت تقريباً)
    if cfg.get("late_first"):
        k = max(0, min(100, int(cfg.get("late_strength", 50)))) / 100
        by_sec = defaultdict(list)
        for p in plan.values():
            if p["pct"] is not None and p["base"] > 0:
                by_sec[p["section_id"]].append(p)
        for lst in by_sec.values():
            if len(lst) < 2:
                continue
            avg = sum(p["pct"] for p in lst) / len(lst)
            total = sum(p["base"] for p in lst)
            raw = {p["req"]: max(0.0, p["base"] * (1 + k * (avg - p["pct"]) / max(avg, 10))) for p in lst}
            s = sum(raw.values()) or 1
            for p in lst:
                new = raw[p["req"]] * total / s
                if abs(new - p["base"]) >= 0.5:
                    p["hours"] = new
                    p["reason"] = ("متأخرة" if new > p["base"] else "متقدمة") + f" ({p['pct']:g}% مقابل متوسط {avg:.0f}%)"

    # 4) إنهاء مادة بتاريخ
    for dl in cfg.get("deadlines") or []:
        try:
            end = to_date(dl["date"])
        except Exception:
            continue
        weeks_left = max(1, math.ceil(((end - ws).days + 1) / 7))
        for p in plan.values():
            sec = secs.get(p["section_id"])
            if not sec or p["subject_id"] != dl.get("subject") or not matches(dl.get("scope"), dl.get("ref"), sec):
                continue
            pr = prog.get((p["section_id"], p["subject_id"]))
            if not pr or pr["remaining"] is None:
                continue
            if end < ws:
                p["hours"], p["reason"] = 0.0, f"انتهى تاريخ الإنهاء {iso(end)}"
                continue
            p["hours"] = pr["remaining"] / weeks_left
            p["reason"] = f"إنهاء قبل {end.strftime('%d/%m')}: الباقي {pr['remaining']:g} سا ÷ {weeks_left} أسبوع"

    # 3) مواد محددة بساعات محددة (الأقوى: تُطبَّق أخيراً)
    for tg in cfg.get("targets") or []:
        hit_secs = set()
        for p in plan.values():
            sec = secs.get(p["section_id"])
            if sec and p["subject_id"] == tg.get("subject") and matches(tg.get("scope"), tg.get("ref"), sec):
                p["hours"] = float(tg.get("hours") or 0)
                p["reason"] = f"محددة: {float(tg.get('hours') or 0):g} سا هذا الأسبوع"
                hit_secs.add(sec["id"])
        if create_missing:                       # القسم لا يملك متطلباً لهذه المادة: يُنشأ (بلا أستاذ، يختاره المحرك)
            for sec in secs.values():
                if sec["id"] in hit_secs or not matches(tg.get("scope"), tg.get("ref"), sec):
                    continue
                g = db.scalar("SELECT id FROM groups_ WHERE section_id=? AND is_whole=1", (sec["id"],))
                if not g or (group_ids is not None and g not in group_ids):
                    continue
                rid = db.scalar("SELECT id FROM requirements WHERE group_id=? AND subject_id=?", (g, tg.get("subject")))
                if not rid:
                    with db.tx():
                        rid = db.insert("requirements", formation_id=formation_id, group_id=g,
                                        subject_id=tg.get("subject"), weekly_hours=0, total_hours=0,
                                        session_minutes=120, needs_room=0)
                name = db.scalar("SELECT name FROM subjects WHERE id=?", (tg.get("subject"),)) or ""
                plan[rid] = {"req": rid, "section_id": sec["id"], "section": sec["short"], "subject_id": tg.get("subject"),
                             "subject": name, "base": 0.0, "hours": float(tg.get("hours") or 0),
                             "reason": f"محددة: {float(tg.get('hours') or 0):g} سا (مادة جديدة للقسم)", "mins": 120,
                             "pct": None}
    hours = {}
    for p in plan.values():
        if not p["reason"].startswith(("الحجم الساعي", "محددة")):
            p["hours"] = _round(p["hours"])
        p["hours"] = round(p["hours"], 2)
        hours[p["req"]] = p["hours"]
    rows = sorted(plan.values(), key=lambda p: (p["section"], -(p["hours"] - p["base"]), p["subject"]))
    return hours, rows


def rules(db: Database, cfg: dict | None = None) -> dict:
    return (cfg or load(db)).get("rules") or {}


def compare_result(plan_rows: list[dict], res) -> list[dict]:
    """بعد الحل: المطلوب مقابل الموضوع لكل سطر، وسبب النقص من الحصص المتعذرة."""
    placed = defaultdict(float)
    reason = {}
    for p in res.placements:
        for rid in p.meeting.requirement_ids:
            placed[rid] += (p.end_min - p.start_min) / 60
    for u in res.unplaced:
        for rid in u.meeting.requirement_ids:
            reason.setdefault(rid, u.reason)
    out = []
    for r in plan_rows:
        got = round(placed.get(r["req"], 0.0), 2)
        short = round(max(0.0, r["hours"] - got), 2)
        short = short if short >= 0.5 else 0.0          # فروق أقل من نصف ساعة: تقريب مدة الحصص لا نقص حقيقي
        out.append(dict(r, placed=got, short=short, why=reason.get(r["req"], "الوقت المتاح لا يكفي") if short else ""))
    return out
