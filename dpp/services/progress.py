"""تقدم الأقسام: قداش قرا كل قسم من كل مادة مقارنة بالمقرر، وقداش باقيلو باش ما يتأخرش.

الحساب لكل (قسم × مادة)، بلا اعتبار للأستاذ:
  * المقرر: الحجم الساعي للمادة في المرحلة الحالية (جدول curriculum؛ للاختصاص ثم للطور كاملاً).
  * المرحلة الحالية وأسابيعها من المخطط الزمني (أسابيع الدراسة فقط، بلا إجازات ولا امتحانات ولا استقبال).
  * المنجز: الحصص «منجزة» داخل المرحلة الحالية (غير الدراسية لا تُحتسب).
  * نسبة الإنجاز = المنجز ÷ المقرر.
  * المتوقع حتى التاريخ = المقرر × (أسابيع الدراسة المنقضية ÷ كل أسابيع المرحلة).
  * نسبة التنفيذ = المنجز ÷ المتوقع.  التأخر = المنجز − المتوقع.
  * المطلوب أسبوعياً = الباقي ÷ أسابيع الدراسة الباقية.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from ..db.database import Database
from ..utils import iso, to_date, week_start

STUDY = ("basic", "specialized")
PHASE_LABELS = {"basic": "قاعدي مشترك", "specialized": "تخصصي", "all": "التكوين كاملاً"}
DAYS_PER_WEEK = 5      # الأحد → الخميس


@dataclass
class Phase:
    kind: str                 # basic | specialized | all
    start: date
    end: date
    study_weeks: list[date]   # بدايات أسابيع الدراسة في المرحلة
    elapsed: float            # أسابيع الدراسة المنقضية (كسرية)
    from_timeline: bool

    @property
    def total(self) -> int:
        return len(self.study_weeks)

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self.elapsed)

    @property
    def label(self) -> str:
        return PHASE_LABELS.get(self.kind, self.kind)


def _elapsed(weeks: list[date], today: date) -> float:
    e = 0.0
    for ws in weeks:
        d = (today - ws).days
        if d >= DAYS_PER_WEEK:
            e += 1
        elif d > 0:
            e += d / DAYS_PER_WEEK
    return e


def current_phase(db: Database, level_code: str, specialty: str | None, today: date,
                  fallback: tuple[date, date] | None = None) -> Phase | None:
    """المرحلة التي يقع فيها التاريخ، حسب صف المخطط الزمني للطور (أو صف خاص بالاختصاص إن وُجد)."""
    rows = db.q("SELECT week_start, kind, specialty_like FROM timeline WHERE level_code=? ORDER BY week_no",
                (level_code,))
    spec_rows = [r for r in rows if r["specialty_like"] and specialty and r["specialty_like"] in specialty]
    base = spec_rows or [r for r in rows if not r["specialty_like"]]
    weeks = [(to_date(r["week_start"]), r["kind"]) for r in base]
    if not weeks:
        if not fallback:
            return None
        s, e = fallback
        ws = [week_start(s) + timedelta(days=7 * i) for i in range(max(1, ((e - s).days + 1) // 7))]
        return Phase("all", s, e, ws, _elapsed(ws, today), False)
    # الأسبوع الحالي
    idx = max((i for i, (ws, _k) in enumerate(weeks) if ws <= today), default=0)
    kind = next((k for _ws, k in reversed(weeks[:idx + 1]) if k in STUDY), None) \
        or next((k for _ws, k in weeks[idx:] if k in STUDY), None)
    if kind is None:
        return None
    # امتداد المرحلة: نتوقف عند أسبوع دراسة من نوع آخر
    # حدود المرحلة: أسبوع دراسة من نوع آخر، أو «استقبال» (بداية دورة/دفعة جديدة)، أو بعد «امتحان نهائي»
    def other(k):
        return k in STUDY and k != kind
    a = idx
    while a > 0 and weeks[a][1] != "reception" and not other(weeks[a - 1][1]) and weeks[a - 1][1] != "final_exam":
        a -= 1
    b = idx
    while b + 1 < len(weeks) and weeks[b][1] != "final_exam" and not other(weeks[b + 1][1]) \
            and weeks[b + 1][1] != "reception":
        b += 1
    seg = weeks[a:b + 1]
    study = [ws for ws, k in seg if k == kind]
    return Phase(kind, seg[0][0], seg[-1][0] + timedelta(days=6), study, _elapsed(study, today), True)


def curriculum_hours(db: Database) -> dict[tuple, float]:
    """{(level_id, specialty_id, subject_id, phase): hours}"""
    return {(r["level_id"], r["specialty_id"], r["subject_id"], r["phase"]): r["hours"]
            for r in db.q("SELECT level_id, specialty_id, subject_id, phase, hours FROM curriculum")}


def lookup_hours(cur: dict, level_id, specialty_id, subject_id, phase: str) -> float | None:
    for key in ((level_id, specialty_id or 0, subject_id, phase), (level_id, 0, subject_id, phase),
                (level_id, specialty_id or 0, subject_id, "all"), (level_id, 0, subject_id, "all")):
        if key in cur:
            return cur[key]
    if phase == "all":           # بلا مخطط زمني: مجموع مراحل المادة
        for sp in (specialty_id or 0, 0):
            hs = [cur[(level_id, sp, subject_id, ph)] for ph in ("basic", "specialized")
                  if (level_id, sp, subject_id, ph) in cur]
            if hs:
                return sum(hs)
    return None


def set_hours(db: Database, level_id: int, specialty_id: int | None, subject_id: int, phase: str, hours: float,
              source: str = "manual"):
    with db.tx():
        db.execute("""INSERT INTO curriculum(level_id, specialty_id, subject_id, phase, hours, source) VALUES (?,?,?,?,?,?)
                      ON CONFLICT(level_id, specialty_id, subject_id, phase) DO UPDATE SET hours=excluded.hours,
                      source=excluded.source""", (level_id, specialty_id or 0, subject_id, phase, hours, source))
        db.log("تعديل المقرر", "curriculum", None, {"level": level_id, "specialty": specialty_id,
                                                    "subject": subject_id, "phase": phase, "hours": hours})


def section_progress(db: Database, formation_ids: list[int], today=None, section_id: int | None = None) -> list[dict]:
    today = to_date(today or date.today())
    if not formation_ids:
        return []
    marks = ",".join("?" * len(formation_ids))
    secs = db.q(f"""SELECT s.id, s.short, s.name, s.level_id, s.specialty_id, l.code, l.name lname, sp.name spname,
                           f.start_date fs, f.end_date fe, c.start_date cs, c.end_date ce
                    FROM sections s LEFT JOIN levels l ON l.id=s.level_id LEFT JOIN specialties sp ON sp.id=s.specialty_id
                    LEFT JOIN cohorts c ON c.id=s.cohort_id JOIN formations f ON f.id=s.formation_id
                    WHERE s.formation_id IN ({marks}) {'AND s.id=?' if section_id else ''}
                    ORDER BY COALESCE(l.sort, 99), s.sort, s.id""",
                (*formation_ids, *([section_id] if section_id else [])))
    if not secs:
        return []
    cur = curriculum_hours(db)
    phases: dict[int, Phase | None] = {}
    for s in secs:
        st = to_date(s["cs"] or s["fs"]) if (s["cs"] or s["fs"]) else today
        en = to_date(s["ce"] or s["fe"]) if (s["ce"] or s["fe"]) else today
        phases[s["id"]] = current_phase(db, s["code"] or "", s["spname"] or s["name"], today, (st, en))
    sec_ids = [s["id"] for s in secs]
    sm = ",".join("?" * len(sec_ids))
    # كل حصة تُحتسب مرة واحدة لكل قسم (حتى لو شملت عدة أفواج منه)
    rows = db.q(f"""SELECT DISTINCT s.id sid, g.section_id sec, s.subject_id, s.date, s.status, s.end_min-s.start_min m
                    FROM sessions s JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
                    JOIN subjects sub ON sub.id=s.subject_id
                    WHERE g.section_id IN ({sm}) AND COALESCE(sub.kind,'teach')<>'nonteach'
                    AND s.status IN ('planned','done')""", sec_ids)
    agg = defaultdict(lambda: {"done": 0, "planned_future": 0, "planned_past": 0, "total_done": 0})
    week_done: dict[tuple, float] = defaultdict(float)     # (قسم، مادة، أسبوع) → دقائق منجزة في المرحلة
    for r in rows:
        ph = phases.get(r["sec"])
        d = to_date(r["date"])
        a = agg[(r["sec"], r["subject_id"])]
        if r["status"] == "done":
            a["total_done"] += r["m"]
        if ph and not (ph.start <= d <= ph.end):
            continue
        if r["status"] == "done":
            if d <= today:
                a["done"] += r["m"]
                week_done[(r["sec"], r["subject_id"], iso(week_start(d)))] += r["m"]
        elif d > today:
            a["planned_future"] += r["m"]
        else:
            a["planned_past"] += r["m"]
    # تصحيحات الحجم الساعي الأسبوعي تحل محل ما سُجّل في ذلك الأسبوع
    for adj in db.q(f"SELECT * FROM hours_adjust WHERE section_id IN ({sm})", sec_ids):
        ph = phases.get(adj["section_id"])
        w = to_date(adj["week_start"])
        if w > today or (ph and not (ph.start <= w <= ph.end)):
            continue
        a = agg[(adj["section_id"], adj["subject_id"])]
        a["done"] += adj["hours"] * 60 - week_done.get((adj["section_id"], adj["subject_id"], adj["week_start"]), 0)
        a["adjusted"] = True
    # المواد المعنية: ما دُرِّس للقسم + ما له مقرر في طوره/اختصاصه
    subj_names = {r[0]: (r[1], r[2]) for r in db.q("SELECT id, name, short FROM subjects")}
    out = []
    for s in secs:
        ph = phases[s["id"]]
        pk = ph.kind if ph else "all"
        subjects = {k[1] for k in agg if k[0] == s["id"]}
        subjects |= {k[2] for k in cur if k[0] == s["level_id"] and k[1] in (0, s["specialty_id"] or 0)
                     and k[3] in (pk, "all") and cur[k] > 0}
        for sub in subjects:
            a = agg.get((s["id"], sub), {"done": 0, "planned_future": 0, "planned_past": 0, "total_done": 0})
            hours = lookup_hours(cur, s["level_id"], s["specialty_id"], sub, pk)
            done = a["done"] / 60
            row = {
                "section_id": s["id"], "section": s["short"] or s["name"], "section_name": s["name"],
                "level": s["code"] or s["lname"] or "", "level_id": s["level_id"], "specialty_id": s["specialty_id"],
                "subject_id": sub, "subject": subj_names.get(sub, ("?", "?"))[0],
                "phase": pk, "phase_label": PHASE_LABELS.get(pk, pk), "from_timeline": bool(ph and ph.from_timeline),
                "hours": hours, "done": round(done, 2), "planned": round(a["planned_future"] / 60, 2),
                "unrecorded": round(a["planned_past"] / 60, 2),
                "weeks_total": ph.total if ph else 0, "weeks_elapsed": round(ph.elapsed, 2) if ph else 0,
                "weeks_left": round(ph.remaining, 2) if ph else 0,
                "pct_done": None, "expected": None, "pct_exec": None, "delta": None, "remaining": None,
                "per_week": None, "late": False, "adjusted": bool(a.get("adjusted")),
            }
            if hours:
                row["remaining"] = round(max(0.0, hours - done), 2)
                row["pct_done"] = round(done / hours * 100, 1)
                if ph and ph.total:
                    exp = hours * min(1.0, ph.elapsed / ph.total)
                    row["expected"] = round(exp, 2)
                    row["pct_exec"] = round(done / exp * 100, 1) if exp > 0 else None
                    row["delta"] = round(done - exp, 2)
                    row["late"] = row["delta"] < -1e-6 and (exp - done) >= 1
                    row["per_week"] = round(row["remaining"] / ph.remaining, 2) if ph.remaining > 0.05 else None
            out.append(row)
    out.sort(key=lambda r: (sec_ids.index(r["section_id"]), r["subject"]))
    return out


def summarize(rows: list[dict]) -> dict:
    with_h = [r for r in rows if r["hours"]]
    hours = sum(r["hours"] for r in with_h)
    done = sum(r["done"] for r in with_h)
    exp = sum(r["expected"] or 0 for r in with_h)
    return {"hours": hours, "done": done, "expected": exp,
            "pct_done": round(done / hours * 100, 1) if hours else None,
            "pct_exec": round(done / exp * 100, 1) if exp else None,
            "late": sum(1 for r in rows if r["late"]), "missing": sum(1 for r in rows if not r["hours"])}


# ====================================================================== الحجم الساعي الأسبوعي
def weekly_hours(db: Database, formation_ids: list[int], section_id: int | None = None,
                 include_planned: bool = True) -> dict:
    """ساعات كل مادة لكل قسم في كل أسبوع (من الحصص المستوردة والمبرمجة) + التصحيحات.

    يعيد {"weeks": [بدايات الأسابيع], "rows": [{section_id, section, subject_id, subject, hours (المقرر),
    actual: {أسبوع: سا}, adjust: {أسبوع: سا}, effective: {أسبوع: سا}, total}]}
    """
    if not formation_ids:
        return {"weeks": [], "rows": []}
    marks = ",".join("?" * len(formation_ids))
    secs = db.q(f"""SELECT s.id, s.short, s.name, s.level_id, s.specialty_id FROM sections s
                    LEFT JOIN levels l ON l.id=s.level_id WHERE s.formation_id IN ({marks})
                    {'AND s.id=?' if section_id else ''} ORDER BY COALESCE(l.sort, 99), s.sort, s.id""",
                (*formation_ids, *([section_id] if section_id else [])))
    if not secs:
        return {"weeks": [], "rows": []}
    ids = [s["id"] for s in secs]
    sm = ",".join("?" * len(ids))
    statuses = "('planned','done')" if include_planned else "('done')"
    rows = db.q(f"""SELECT DISTINCT s.id sid, g.section_id sec, s.subject_id, s.date, s.end_min-s.start_min m
                    FROM sessions s JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
                    JOIN subjects sub ON sub.id=s.subject_id
                    WHERE g.section_id IN ({sm}) AND COALESCE(sub.kind,'teach')<>'nonteach'
                    AND s.status IN {statuses}""", ids)
    actual: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    weeks: set[str] = set()
    for r in rows:
        w = iso(week_start(to_date(r["date"])))
        actual[(r["sec"], r["subject_id"])][w] += r["m"] / 60
        weeks.add(w)
    adjust: dict[tuple, dict] = defaultdict(dict)
    notes: dict[tuple, str] = {}
    for a in db.q(f"SELECT * FROM hours_adjust WHERE section_id IN ({sm})", ids):
        adjust[(a["section_id"], a["subject_id"])][a["week_start"]] = a["hours"]
        notes[(a["section_id"], a["subject_id"], a["week_start"])] = a["note"] or ""
        weeks.add(a["week_start"])
    cur = curriculum_hours(db)
    names = {r[0]: r[1] for r in db.q("SELECT id, name FROM subjects")}
    out = []
    for s in secs:
        subs = {k[1] for k in actual if k[0] == s["id"]} | {k[1] for k in adjust if k[0] == s["id"]}
        for sub in sorted(subs, key=lambda x: names.get(x, "")):
            act = {w: round(v, 2) for w, v in actual.get((s["id"], sub), {}).items()}
            adj = dict(adjust.get((s["id"], sub), {}))
            eff = act | adj
            out.append({"section_id": s["id"], "section": s["short"] or s["name"], "subject_id": sub,
                        "subject": names.get(sub, "?"),
                        "hours": lookup_hours(cur, s["level_id"], s["specialty_id"], sub, "all"),
                        "actual": act, "adjust": adj, "effective": eff,
                        "notes": {w: notes.get((s["id"], sub, w), "") for w in adj},
                        "total": round(sum(eff.values()), 2)})
    return {"weeks": sorted(weeks), "rows": out}


def set_adjust(db: Database, section_id: int, subject_id: int, ws, hours: float, note: str = ""):
    w = iso(week_start(to_date(ws)))
    with db.tx():
        db.execute("""INSERT INTO hours_adjust(section_id, subject_id, week_start, hours, note) VALUES (?,?,?,?,?)
                      ON CONFLICT(section_id, subject_id, week_start) DO UPDATE SET hours=excluded.hours,
                      note=excluded.note""", (section_id, subject_id, w, hours, note))
        db.log("تصحيح الحجم الساعي", "hours_adjust", None,
               {"section": section_id, "subject": subject_id, "week": w, "hours": hours})


def clear_adjust(db: Database, section_id: int, subject_id: int, ws):
    w = iso(week_start(to_date(ws)))
    with db.tx():
        db.execute("DELETE FROM hours_adjust WHERE section_id=? AND subject_id=? AND week_start=?",
                   (section_id, subject_id, w))
        db.log("إلغاء تصحيح الحجم الساعي", "hours_adjust", None, {"section": section_id, "subject": subject_id,
                                                                  "week": w})


# ====================================================================== المقرر والمنجز (بسيط) والتحليلات
def _family(cat: str | None) -> str:
    return {"military": "military", "pe": "military", "drill": "military", "general": "general",
            "nonteach": "nonteach"}.get(cat or "specialty", "specialty")


def curriculum_total(cur: dict, level_id, specialty_id, subject_id) -> float | None:
    """مقرر المادة للتكوين كاملاً: «all» إن وُجد، وإلا مجموع المراحل."""
    for sp in (specialty_id or 0, 0):
        if (level_id, sp, subject_id, "all") in cur and not any(
                (level_id, sp, subject_id, ph) in cur for ph in ("basic", "specialized")):
            return cur[(level_id, sp, subject_id, "all")]
        hs = [cur[(level_id, sp, subject_id, ph)] for ph in ("all", "basic", "specialized")
              if (level_id, sp, subject_id, ph) in cur]
        if hs:
            return sum(hs)
    return None


def simple_progress(db: Database, formation_ids: list[int], today=None, section_id: int | None = None,
                    include_planned: bool = False) -> list[dict]:
    """المقرر والمنجز فقط، للتكوين كاملاً (بلا مراحل ولا متوقع):
    سطر لكل قسم × مادة: المقرر، المنجز (الحصص المنجزة + تصحيحات الحجم الساعي)، النسبة، الباقي، الحصص المنجزة.
    include_planned: تُحتسب أيضاً الحصص المبرمجة حتى التاريخ (لشريط الجدول العام: «حتى نهاية الأسبوع المعروض»)."""
    today = to_date(today or date.today())
    if not formation_ids:
        return []
    marks = ",".join("?" * len(formation_ids))
    secs = db.q(f"""SELECT s.id, s.short, s.name, s.level_id, s.specialty_id, l.code, l.name lname, sp.name spname
                    FROM sections s LEFT JOIN levels l ON l.id=s.level_id LEFT JOIN specialties sp ON sp.id=s.specialty_id
                    WHERE s.formation_id IN ({marks}) {'AND s.id=?' if section_id else ''}
                    ORDER BY COALESCE(l.sort, 99), s.sort, s.id""",
                (*formation_ids, *([section_id] if section_id else [])))
    if not secs:
        return []
    ids = [s["id"] for s in secs]
    sm = ",".join("?" * len(ids))
    done = defaultdict(float)
    count = defaultdict(int)
    week_min = defaultdict(float)
    st_in = "'done','planned'" if include_planned else "'done'"
    for r in db.q(f"""SELECT DISTINCT s.id sid, g.section_id sec, s.subject_id, s.date, s.end_min-s.start_min m
                      FROM sessions s JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
                      JOIN subjects sub ON sub.id=s.subject_id
                      WHERE g.section_id IN ({sm}) AND COALESCE(sub.kind,'teach')<>'nonteach'
                      AND s.status IN ({st_in}) AND s.date<=?""",
                  (*ids, iso(today))):
        done[(r["sec"], r["subject_id"])] += r["m"] / 60
        count[(r["sec"], r["subject_id"])] += 1
        week_min[(r["sec"], r["subject_id"], iso(week_start(to_date(r["date"]))))] += r["m"] / 60
    for a in db.q(f"SELECT * FROM hours_adjust WHERE section_id IN ({sm}) AND week_start<=?", (*ids, iso(today))):
        k = (a["section_id"], a["subject_id"])
        done[k] += a["hours"] - week_min.get((*k, a["week_start"]), 0)
    cur = curriculum_hours(db)
    subj = {r["id"]: r for r in db.q("SELECT id, name, COALESCE(category,'specialty') cat, COALESCE(kind,'teach') kind "
                                     "FROM subjects")}
    out = []
    for s in secs:
        subs = {k[1] for k in done if k[0] == s["id"]}
        subs |= {k[2] for k in cur if k[0] == s["level_id"] and k[1] in (0, s["specialty_id"] or 0) and cur[k] > 0}
        for sub in subs:
            info = subj.get(sub)
            if not info or info["kind"] == "nonteach":
                continue
            hours = curriculum_total(cur, s["level_id"], s["specialty_id"], sub)
            d = round(done.get((s["id"], sub), 0.0), 2)
            out.append({"section_id": s["id"], "section": s["short"] or s["name"], "section_name": s["name"],
                        "level": s["code"] or s["lname"] or "", "level_id": s["level_id"],
                        "specialty_id": s["specialty_id"], "specialty": s["spname"] or "",
                        "subject_id": sub, "subject": info["name"], "family": _family(info["cat"]),
                        "hours": hours, "done": d, "sessions": count.get((s["id"], sub), 0),
                        "pct": round(d / hours * 100, 1) if hours else None,
                        "remaining": round(max(0.0, hours - d), 2) if hours else None,
                        "over": bool(hours and d > hours + 0.01)})
    out.sort(key=lambda r: (ids.index(r["section_id"]), {"specialty": 0, "military": 1, "general": 2}.get(r["family"], 3),
                            r["subject"]))
    return out


def summarize_simple(rows: list[dict]) -> dict:
    with_h = [r for r in rows if r["hours"]]
    hours = sum(r["hours"] for r in with_h)
    done = sum(min(r["done"], r["hours"]) for r in with_h)
    return {"hours": hours, "done": done, "pct": round(done / hours * 100, 1) if hours else None,
            "remaining": round(sum(r["remaining"] or 0 for r in with_h), 2),
            "missing": sum(1 for r in rows if not r["hours"]), "over": sum(1 for r in rows if r["over"]),
            "complete": sum(1 for r in with_h if r["done"] >= r["hours"] - 0.01)}


def weekly_family_hours(db: Database, formation_ids: list[int], section_id: int | None = None, today=None) -> dict:
    """منحنى الساعات المنجزة أسبوعاً بأسبوع حسب نوع المادة: {"weeks": [...], "series": {family: [..]}}."""
    today = to_date(today or date.today())
    if not formation_ids:
        return {"weeks": [], "series": {}}
    marks = ",".join("?" * len(formation_ids))
    rows = db.q(f"""SELECT DISTINCT s.id, s.date, s.end_min-s.start_min m, COALESCE(sub.category,'specialty') cat
                    FROM sessions s JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
                    JOIN sections sec ON sec.id=g.section_id JOIN subjects sub ON sub.id=s.subject_id
                    WHERE sec.formation_id IN ({marks}) {'AND sec.id=?' if section_id else ''}
                    AND COALESCE(sub.kind,'teach')<>'nonteach' AND s.status IN ('planned','done') AND s.date<=?""",
                (*formation_ids, *([section_id] if section_id else []), iso(today + timedelta(days=6))))
    acc: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        acc[iso(week_start(to_date(r["date"])))][_family(r["cat"])] += r["m"] / 60
    weeks = sorted(acc)
    fams = ("specialty", "military", "general")
    return {"weeks": weeks, "series": {f: [round(acc[w].get(f, 0.0), 1) for w in weeks] for f in fams}}


def forecast(db: Database, rows: list[dict], today=None, recent_weeks: int = 4) -> list[dict]:
    """تاريخ الانتهاء المتوقع لكل قسم × مادة بالوتيرة الحالية (متوسط الساعات المنجزة في آخر أسابيع)،
    ومقارنته بنهاية تكوين القسم."""
    today = to_date(today or date.today())
    if not rows:
        return []
    ids = sorted({r["section_id"] for r in rows})
    sm = ",".join("?" * len(ids))
    since = week_start(today) - timedelta(days=7 * recent_weeks)
    pace = defaultdict(float)
    for r in db.q(f"""SELECT DISTINCT s.id, g.section_id sec, s.subject_id, s.end_min-s.start_min m
                      FROM sessions s JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
                      WHERE g.section_id IN ({sm}) AND s.status='done' AND s.date>=? AND s.date<=?""",
                  (*ids, iso(since), iso(today))):
        pace[(r["sec"], r["subject_id"])] += r["m"] / 60 / recent_weeks
    ends = {r["id"]: to_date(r["e"]) if r["e"] else None for r in db.q(
        f"""SELECT s.id, COALESCE(c.end_date, f.end_date) e FROM sections s JOIN formations f ON f.id=s.formation_id
            LEFT JOIN cohorts c ON c.id=s.cohort_id WHERE s.id IN ({sm})""", ids)}
    out = []
    for r in rows:
        if not r["hours"]:
            continue
        p = round(pace.get((r["section_id"], r["subject_id"]), 0.0), 2)
        rem = r["remaining"] or 0.0
        end = ends.get(r["section_id"])
        if rem <= 0.01:
            eta, status = None, "done"
        elif p <= 0.01:
            eta, status = None, "stalled"
        else:
            eta = today + timedelta(days=int(round(rem / p * 7)))
            status = "late" if end and eta > end else "ok"
        need = None
        if end and end > today and rem > 0:
            weeks_left = max(0.2, (end - today).days / 7)
            need = round(rem / weeks_left, 2)
        out.append(dict(r, pace=p, eta=eta, end=end, status=status, need=need))
    return out


def compare_specialty(rows: list[dict]) -> list[dict]:
    """أقسام نفس الطور والاختصاص جنباً إلى جنب: المنجز لكل مادة والفرق بين الأكثر والأقل."""
    groups: dict[tuple, dict] = {}
    for r in rows:
        k = (r["level_id"], r["specialty_id"])
        g = groups.setdefault(k, {"level": r["level"], "specialty": r["specialty"], "sections": [], "subjects": {}})
        if r["section"] not in g["sections"]:
            g["sections"].append(r["section"])
        g["subjects"].setdefault((r["subject_id"], r["subject"], r["hours"]), {})[r["section"]] = r["done"]
    out = []
    for g in groups.values():
        if len(g["sections"]) < 2:
            continue
        for (sid, name, hours), vals in g["subjects"].items():
            vs = [vals.get(s, 0.0) for s in g["sections"]]
            out.append({"level": g["level"], "specialty": g["specialty"], "sections": g["sections"], "subject": name,
                        "subject_id": sid, "hours": hours, "values": vs, "spread": round(max(vs) - min(vs), 2)})
    out.sort(key=lambda x: (x["level"], x["specialty"], -x["spread"]))
    return out


def progress_alerts(db: Database, formation_ids: list[int], today=None) -> list[dict]:
    """تنبيهات محسوبة من البيانات (لا تُحفظ): مادة دُرِّست بلا مقرر، منجز يتجاوز المقرر، قسم بلا اختصاص."""
    rows = simple_progress(db, formation_ids, today)
    out = []
    miss = defaultdict(list)
    for r in rows:
        if not r["hours"] and r["done"] > 0:
            miss[(r["level"], r["specialty"] or "—")].append(f"{r['subject']} ({r['section']}: {r['done']:g} سا)")
        if r["over"]:
            out.append({"severity": "medium", "kind": "progress", "title": f"«{r['subject']}» تجاوز المقرر في {r['section']}",
                        "details": f"المنجز {r['done']:g} سا والمقرر {r['hours']:g} سا", "target": "progress",
                        "section_id": r["section_id"], "subject_id": r["subject_id"]})
    for (lvl, spec), lst in miss.items():
        out.append({"severity": "medium", "kind": "progress",
                    "title": f"{len(lst)} مادة دُرِّست بلا مقرر — {lvl} {spec}",
                    "details": "\n".join(lst[:60]), "target": "curriculum"})
    if formation_ids:
        marks = ",".join("?" * len(formation_ids))
        nospec = [r[0] for r in db.q(f"SELECT short FROM sections WHERE specialty_id IS NULL AND formation_id IN ({marks})",
                                     formation_ids)]
        if nospec:
            out.append({"severity": "high", "kind": "data", "title": f"{len(nospec)} قسم بلا اختصاص",
                        "details": "لا يُعرف مقررها: " + "، ".join(nospec), "target": "sections"})
    return out
