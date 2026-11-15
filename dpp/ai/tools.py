"""أدوات قراءة قاعدة البيانات التي ينادِيها النموذج المحلي.

قاعدة صارمة: كل أداة هنا **تقرأ فقط** (SELECT) ولا تعدّل أي شيء. الكتابة (نقل حصة،
برمجة أسبوع…) ستأتي في إصدار لاحق عبر اقتراح + تأكيد صريح من المستخدم.

المخرجات نصوص عربية مختصرة (لا JSON): النموذج 4B على جهاز بـ 8 غيغا لا يتحمل سياقاً كبيراً،
فكل أداة تعيد أسطراً قصيرة وتقصّ الزائد.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Callable

from ..utils import fmt_hours, hm, iso, parse_hm, to_date, week_start

DAYS = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
MAX_LINES = 60          # أقصى عدد أسطر في جواب أداة واحدة


@dataclass
class Env:
    """ما تحتاجه الأدوات: القاعدة، التكوينات المعنية، واليوم."""
    db: object
    formation_ids: list[int]
    today: date

    def fids(self) -> list[int]:
        if self.formation_ids:
            return list(self.formation_ids)
        return [r[0] for r in self.db.q("SELECT id FROM formations WHERE archived=0 ORDER BY start_date, id")]


@dataclass
class Tool:
    name: str
    desc: str
    params: dict
    fn: Callable[..., str]

    def spec(self) -> dict:
        return {"type": "function",
                "function": {"name": self.name, "description": self.desc, "parameters": self.params}}


REGISTRY: dict[str, Tool] = {}


def tool(name: str, desc: str, props: dict | None = None, required: list[str] | None = None):
    def deco(fn):
        REGISTRY[name] = Tool(name, desc, {"type": "object", "properties": props or {},
                                           "required": required or []}, fn)
        return fn
    return deco


def specs() -> list[dict]:
    return [t.spec() for t in REGISTRY.values()]


def run(env: Env, name: str, args: dict) -> str:
    """تنفيذ أداة باسمها؛ الأخطاء تُعاد كنصّ حتى يتمكن النموذج من تصحيح نفسه."""
    t = REGISTRY.get(name)
    if t is None:
        return f"لا توجد أداة بالاسم «{name}». الأدوات المتاحة: " + "، ".join(REGISTRY)
    clean = {k: v for k, v in (args or {}).items() if k in t.params["properties"] and v not in (None, "")}
    try:
        out = t.fn(env, **clean)
    except _Ask as e:
        return str(e)
    except TypeError as e:
        return f"وسائط غير صحيحة للأداة «{name}»: {e}"
    except Exception as e:                                  # لا نُسقط الواجهة بسبب سؤال
        return f"تعذّر تنفيذ «{name}»: {type(e).__name__}: {e}"
    return _cut(out or "لا توجد نتائج.")


class _Ask(Exception):
    """رسالة موجّهة للنموذج (اسم غير واضح، وسيط ناقص…)."""


def _cut(text: str) -> str:
    lines = str(text).splitlines()
    if len(lines) <= MAX_LINES:
        return "\n".join(lines)
    return "\n".join(lines[:MAX_LINES]) + f"\n… و{len(lines) - MAX_LINES} سطراً أخرى (حدّد سؤالك أكثر)."


# ---------------------------------------------------------------- مساعدات
def _day_label(d: date) -> str:
    return f"{DAYS[(d.weekday() + 1) % 7]} {d.strftime('%d/%m')}"


def _week(env: Env, week=None) -> date:
    """بداية الأسبوع من تاريخ أو رقم أسبوع أو فراغ (= الأسبوع الحالي)."""
    if week in (None, "", "الحالي", "هذا"):
        return week_start(env.today)
    s = str(week).strip()
    if s.lstrip("-").isdigit() and len(s) <= 3:
        from ..services.grid import week_of_number
        return week_of_number(env.db, int(s))
    try:
        return week_start(to_date(s))
    except (ValueError, TypeError):
        raise _Ask(f"لم أفهم «{week}». اكتب تاريخاً مثل 2026-11-08 أو رقم أسبوع مثل 9.")


def _date(env: Env, value=None) -> date:
    if value in (None, "", "اليوم"):
        return env.today
    s = str(value).strip()
    if s == "غدا" or s == "غداً":
        return env.today + timedelta(days=1)
    if s in DAYS:
        return week_start(env.today) + timedelta(days=DAYS.index(s))
    try:
        return to_date(s)
    except (ValueError, TypeError):
        raise _Ask(f"لم أفهم التاريخ «{value}». اكتبه هكذا: 2026-11-10، أو اسم يوم مثل «الثلاثاء».")


KINDS_SQL = {
    "teacher": ("teachers", "full_name", "rank", "أستاذ"),
    "section": ("sections", "name", "short", "قسم"),
    "subject": ("subjects", "name", "short", "مادة"),
    "room": ("rooms", "name", "short", "قاعة"),
    "level": ("levels", "name", "short", "طور"),
    "formation": ("formations", "name", "short", "تكوين"),
}


def _match(env: Env, kind: str, name: str) -> list[dict]:
    if kind not in KINDS_SQL:
        raise _Ask("النوع يجب أن يكون أحدها: " + "، ".join(KINDS_SQL))
    table, col, alt, _label = KINDS_SQL[kind]
    txt = str(name).strip()
    rows = env.db.q(f"SELECT id, {col} nm, {alt} alt FROM {table} "
                    f"WHERE {col}=? OR {alt}=? COLLATE NOCASE", (txt, txt))
    if not rows:
        rows = env.db.q(f"SELECT id, {col} nm, {alt} alt FROM {table} "
                        f"WHERE {col} LIKE ? OR {alt} LIKE ? ORDER BY LENGTH({col}) LIMIT 8",
                        (f"%{txt}%", f"%{txt}%"))
    return [dict(r) for r in rows]


def _one(env: Env, kind: str, name: str) -> dict:
    rows = _match(env, kind, name)
    label = KINDS_SQL[kind][3]
    if not rows:
        return _nope(env, kind, name)
    if len(rows) > 1:
        exact = [r for r in rows if str(r["nm"]).strip() == str(name).strip()]
        if len(exact) == 1:
            return exact[0]
        names = "، ".join(f"{r['nm']}" + (f" ({r['alt']})" if r["alt"] else "") for r in rows[:8])
        raise _Ask(f"«{name}» يطابق أكثر من {label}: {names}. اسأل المستخدم أيّهما يقصد.")
    return rows[0]


def _nope(env: Env, kind: str, name: str):
    table, col, alt, label = KINDS_SQL[kind]
    some = [r[0] for r in env.db.q(f"SELECT {col} FROM {table} ORDER BY id LIMIT 12")]
    raise _Ask(f"لا يوجد {label} بالاسم «{name}». الموجود مثلاً: " + "، ".join(x for x in some if x))


def _sessions(env: Env, d0: date, d1: date, *, section_id=None, teacher_id=None, room_id=None) -> list[dict]:
    where = ["s.date BETWEEN ? AND ?", "s.status NOT IN ('tray','cancelled')"]
    params: list = [iso(d0), iso(d1)]
    if section_id:
        where.append("g.section_id=?")
        params.append(section_id)
    if teacher_id:
        where.append("COALESCE(s.substitute_id, s.teacher_id)=?")
        params.append(teacher_id)
    if room_id:
        where.append("s.room_id=?")
        params.append(room_id)
    rows = env.db.q(f"""SELECT DISTINCT s.id, s.date, s.start_min a, s.end_min b, s.status,
                               sub.name subject, t.full_name teacher, sb.full_name sub_t, r.name room,
                               sec.short sec_short, sec.name sec_name
                        FROM sessions s
                        JOIN session_groups sg ON sg.session_id=s.id
                        JOIN groups_ g ON g.id=sg.group_id
                        JOIN sections sec ON sec.id=g.section_id
                        JOIN subjects sub ON sub.id=s.subject_id
                        LEFT JOIN teachers t ON t.id=s.teacher_id
                        LEFT JOIN teachers sb ON sb.id=s.substitute_id
                        LEFT JOIN rooms r ON r.id=s.room_id
                        WHERE {' AND '.join(where)}
                        ORDER BY s.date, s.start_min, sec.sort, sec.id""", params)
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(dict(r))
    return out


STATUS_AR = {"done": "منجزة", "planned": "مبرمجة", "postponed": "مؤجلة"}


def _line(r: dict, *, with_section=False) -> str:
    who = r["sub_t"] or r["teacher"] or "بلا أستاذ"
    bits = [f"{hm(r['a'])}-{hm(r['b'])}", r["subject"], who]
    if with_section:
        bits.insert(1, r["sec_short"] or r["sec_name"])
    if r["room"]:
        bits.append(r["room"])
    if r["status"] != "planned":
        bits.append(STATUS_AR.get(r["status"], r["status"]))
    return " | ".join(str(b) for b in bits)


# ---------------------------------------------------------------- الأدوات
@tool("today", "التاريخ الحالي ورقم الأسبوع والتكوين الحالي وأرقام عامة عن المؤسسة. استعملها أولاً إن ذُكر «اليوم» أو «هذا الأسبوع».")
def t_today(env: Env) -> str:
    from ..services.grid import week_number
    ws = week_start(env.today)
    fids = env.fids()
    names = [r[0] for r in env.db.q("SELECT name FROM formations WHERE archived=0 ORDER BY start_date, id")]
    marks = ",".join("?" * len(fids)) or "0"
    nsec = env.db.scalar(f"SELECT COUNT(*) FROM sections WHERE formation_id IN ({marks})", fids, default=0)
    nteach = env.db.scalar("SELECT COUNT(*) FROM teachers WHERE active=1", default=0)
    nsess = env.db.scalar("SELECT COUNT(*) FROM sessions WHERE date BETWEEN ? AND ? AND status<>'tray'",
                          (iso(ws), iso(ws + timedelta(days=6))), default=0)
    return (f"اليوم: {DAYS[(env.today.weekday() + 1) % 7]} {iso(env.today)}.\n"
            f"الأسبوع رقم {week_number(env.db, env.today)}، يبدأ الأحد {iso(ws)} وينتهي السبت {iso(ws + timedelta(days=6))}.\n"
            f"التكوينات النشطة: {'، '.join(names) or 'لا شيء'}.\n"
            f"الأقسام: {nsec} | الأساتذة النشطون: {nteach} | حصص هذا الأسبوع: {nsess}.")


@tool("find", "البحث عن اسم في البيانات ومعرفة صيغته الصحيحة (أستاذ، قسم، مادة، قاعة، طور، تكوين).",
      {"kind": {"type": "string", "enum": list(KINDS_SQL), "description": "نوع العنصر"},
       "name": {"type": "string", "description": "جزء من الاسم"}}, ["kind", "name"])
def t_find(env: Env, kind: str, name: str) -> str:
    rows = _match(env, kind, name)
    if not rows:
        return f"لا شيء يطابق «{name}» في {KINDS_SQL.get(kind, ('', '', '', kind))[3]}."
    return "\n".join(f"{r['nm']}" + (f" ({r['alt']})" if r["alt"] else "") for r in rows)


@tool("schedule", "الجدول الزمني: حصص قسم أو أستاذ أو قاعة في أسبوع أو في يوم محدد. بلا اسم = ملخص كل الأقسام.",
      {"scope": {"type": "string", "enum": ["section", "teacher", "room", "all"],
                 "description": "جدول من؟ قسم أو أستاذ أو قاعة أو ملخص الكل"},
       "name": {"type": "string", "description": "اسم القسم أو الأستاذ أو القاعة"},
       "week": {"type": "string", "description": "تاريخ بداية الأسبوع (2026-11-08) أو رقمه (9)؛ بلا قيمة = الأسبوع الحالي"},
       "day": {"type": "string", "description": "يوم واحد فقط: تاريخ أو اسم يوم مثل «الثلاثاء»"}},
      ["scope"])
def t_schedule(env: Env, scope: str, name: str = "", week=None, day=None) -> str:
    if scope not in ("section", "teacher", "room", "all"):
        raise _Ask("scope يجب أن يكون: section أو teacher أو room أو all.")
    if day:
        d0 = d1 = _date(env, day)
        head = _day_label(d0)
    else:
        d0 = _week(env, week)
        d1 = d0 + timedelta(days=6)
        head = f"أسبوع {iso(d0)}"
    kw: dict = {}
    if scope in ("section", "teacher", "room"):
        if not name:
            raise _Ask("حدّد الاسم: جدول من بالضبط؟")
        row = _one(env, scope, name)
        kw[{"section": "section_id", "teacher": "teacher_id", "room": "room_id"}[scope]] = row["id"]
        title = f"جدول {KINDS_SQL[scope][3]} {row['nm']} — {head}"
    else:
        title = f"ملخص {head}"
    rows = _sessions(env, d0, d1, **kw)
    if not rows:
        return f"{title}: لا توجد حصص."
    if scope == "all":
        per: dict[str, list] = {}
        for r in rows:
            per.setdefault(r["sec_short"] or r["sec_name"], []).append(r)
        out = [title]
        for sec, lst in per.items():
            hours = sum(r["b"] - r["a"] for r in lst) / 60
            out.append(f"{sec}: {len(lst)} حصة، {fmt_hours(round(hours, 1))} سا")
        return "\n".join(out)
    out, cur = [title], None
    for r in rows:
        if r["date"] != cur:
            cur = r["date"]
            out.append(_day_label(to_date(cur)) + ":")
        out.append("  " + _line(r, with_section=(scope != "section")))
    total = sum(r["b"] - r["a"] for r in rows) / 60
    out.append(f"المجموع: {len(rows)} حصة، {fmt_hours(round(total, 1))} ساعة.")
    return "\n".join(out)


@tool("free", "من/ما هو فارغ في وقت محدد: الأساتذة أو القاعات غير المشغولة (مع مراعاة الغياب وعدم التوفر).",
      {"kind": {"type": "string", "enum": ["teacher", "room"], "description": "أستاذ أم قاعة"},
       "date": {"type": "string", "description": "التاريخ أو اسم اليوم؛ بلا قيمة = اليوم"},
       "start": {"type": "string", "description": "وقت البداية HH:MM (الافتراضي 08:00)"},
       "end": {"type": "string", "description": "وقت النهاية HH:MM (الافتراضي 16:00)"},
       "subject": {"type": "string", "description": "للأساتذة فقط: الاقتصار على من يدرّس هذه المادة"}},
      ["kind"])
def t_free(env: Env, kind: str, date=None, start="08:00", end="16:00", subject="") -> str:
    if kind not in ("teacher", "room"):
        raise _Ask("kind يجب أن يكون teacher أو room.")
    d = _date(env, date)
    try:
        a, b = parse_hm(str(start)), parse_hm(str(end))
    except (ValueError, AttributeError):
        raise _Ask("الوقت يُكتب هكذا: 08:00 و10:00.")
    if b <= a:
        raise _Ask("وقت النهاية يجب أن يكون بعد البداية.")
    busy = {r[0] for r in env.db.q(
        """SELECT DISTINCT CASE WHEN ?='teacher' THEN COALESCE(s.substitute_id, s.teacher_id) ELSE s.room_id END
           FROM sessions s WHERE s.date=? AND s.status NOT IN ('tray','cancelled')
           AND s.start_min < ? AND s.end_min > ?""", (kind, iso(d), b, a)) if r[0]}
    wd = (d.weekday() + 1) % 7
    for r in env.db.q("""SELECT ref_id FROM unavailability WHERE kind=? AND start_min < ? AND end_min > ?
                         AND (date=? OR (date IS NULL AND weekday=?))""", (kind, b, a, iso(d), wd)):
        busy.add(r[0])
    if kind == "teacher":
        from ..services import absences as A
        busy |= A.absent_teachers(env.db, iso(d))
        sql = "SELECT id, full_name nm FROM teachers WHERE active=1"
        params: list = []
        if subject:
            sub = _one(env, "subject", subject)
            sql += " AND id IN (SELECT teacher_id FROM teacher_subjects WHERE subject_id=?)"
            params.append(sub["id"])
        sql += " ORDER BY full_name"
        rows = env.db.q(sql, params)
        label = "أستاذ"
    else:
        rows = env.db.q("SELECT id, name nm FROM rooms ORDER BY name")
        label = "قاعة"
    free = [r["nm"] for r in rows if r["id"] not in busy]
    head = f"{_day_label(d)} من {hm(a)} إلى {hm(b)}"
    if subject:
        head += f" (مادة: {subject})"
    if not free:
        return f"{head}: لا يوجد {label} فارغ ({len(rows)} الكل، كلهم مشغولون أو غائبون)."
    return f"{head}: {len(free)} {label} فارغ من {len(rows)}:\n" + "، ".join(free)


@tool("progress", "تقدم المقرر: المنجز مقابل المقرر لكل مادة في قسم (أو ملخص كل الأقسام بلا اسم).",
      {"section": {"type": "string", "description": "اسم القسم أو رمزه؛ بلا قيمة = ملخص كل الأقسام"}})
def t_progress(env: Env, section: str = "") -> str:
    from ..services import progress as P
    sid = _one(env, "section", section)["id"] if section else None
    rows = P.simple_progress(env.db, env.fids(), env.today, section_id=sid)
    if not rows:
        return "لا توجد بيانات تقدم (تحقّق من المقرر وبيانات الأقسام)."
    s = P.summarize_simple(rows)
    head = (f"المقرر {fmt_hours(round(s['hours'], 1))} سا، المنجز {fmt_hours(round(s['done'], 1))} سا"
            f" ({s['pct'] if s['pct'] is not None else '—'}%)، الباقي {fmt_hours(s['remaining'])} سا.")
    if not sid:
        per: dict[str, list] = {}
        for r in rows:
            per.setdefault(r["section"], []).append(r)
        out = ["ملخص كل الأقسام: " + head]
        for sec, lst in per.items():
            ss = P.summarize_simple(lst)
            out.append(f"{sec}: {ss['pct'] if ss['pct'] is not None else '—'}% "
                       f"({fmt_hours(round(ss['done'], 1))}/{fmt_hours(round(ss['hours'], 1))} سا)")
        return "\n".join(out)
    out = [f"تقدم {rows[0]['section']}: {head}"]
    for r in rows:
        if not r["hours"]:
            out.append(f"{r['subject']}: {fmt_hours(r['done'])} سا منجزة، بلا مقرر مسجّل")
        else:
            out.append(f"{r['subject']}: {fmt_hours(r['done'])}/{fmt_hours(r['hours'])} سا "
                       f"({r['pct']}%)، الباقي {fmt_hours(r['remaining'])} سا" + ("، تجاوز المقرر" if r["over"] else ""))
    return "\n".join(out)


@tool("late", "المواد المتأخرة عن المقرر: أين التأخر وكم ساعة وكم يلزم أسبوعياً لتعويضه.",
      {"section": {"type": "string", "description": "الاقتصار على قسم واحد (اختياري)"}})
def t_late(env: Env, section: str = "") -> str:
    from ..services import progress as P
    sid = _one(env, "section", section)["id"] if section else None
    rows = [r for r in P.section_progress(env.db, env.fids(), env.today, section_id=sid) if r["late"]]
    if not rows:
        return "لا توجد مادة متأخرة عن المقرر" + (f" في {section}." if section else " في أي قسم.")
    rows.sort(key=lambda r: r["delta"] or 0)
    out = [f"{len(rows)} مادة متأخرة (الأكثر تأخراً أولاً):"]
    for r in rows:
        per = f"، يلزم {fmt_hours(r['per_week'])} سا/أسبوع" if r["per_week"] else ""
        out.append(f"{r['section']} — {r['subject']}: منجز {fmt_hours(r['done'])} سا والمتوقع "
                   f"{fmt_hours(r['expected'])} سا (تأخر {fmt_hours(round(abs(r['delta']), 1))} سا){per}")
    return "\n".join(out)


@tool("conflicts", "تعارضات أسبوع: أستاذ أو قاعة أو فوج في مكانين في نفس الوقت.",
      {"week": {"type": "string", "description": "بداية الأسبوع أو رقمه؛ بلا قيمة = الأسبوع الحالي"}})
def t_conflicts(env: Env, week=None) -> str:
    from ..services import conflicts as CF
    ws = _week(env, week)
    rows = [c for c in CF.find_conflicts(env.db, ws, ws + timedelta(days=6)) if not c.ignored]
    if not rows:
        return f"أسبوع {iso(ws)}: لا توجد تعارضات."
    kinds = {"teacher": "أستاذ", "room": "قاعة", "group": "فوج"}
    out = [f"أسبوع {iso(ws)}: {len(rows)} تعارض."]
    for c in rows:
        out.append(f"{kinds.get(c.kind, c.kind)} — {_day_label(to_date(c.date))}: {c.message}")
    return "\n".join(out)


@tool("duty", "الخفارة والخدمات في أسبوع: أي قسم مكلّف بأي خدمة وفي أي يوم.",
      {"week": {"type": "string", "description": "بداية الأسبوع أو رقمه؛ بلا قيمة = الأسبوع الحالي"}})
def t_duty(env: Env, week=None) -> str:
    from ..services import duty as D
    ws = _week(env, week)
    rows = D.assignments(env.db, ws, ws + timedelta(days=6))
    if not rows:
        return f"أسبوع {iso(ws)}: لا توجد خفارة أو خدمة مسجّلة."
    out = [f"خفارة وخدمات أسبوع {iso(ws)}:"]
    for r in rows:
        out.append(f"{_day_label(to_date(r['date']))}: {r.get('tname') or ''} — {r.get('short') or ''}"
                   + ("  (يدوي)" if r.get("manual") else ""))
    return "\n".join(out)


@tool("status", "حالة المؤسسة الآن: الغيابات الجارية، المواعيد القريبة، وتنبيهات البيانات.")
def t_status(env: Env) -> str:
    from ..services import absences as A
    from ..services import calendar as C
    from ..services import progress as P
    out = []
    ab = A.current_absences(env.db, env.today)
    if ab:
        out.append(f"الغيابات الجارية ({len(ab)}):")
        for r in ab:
            out.append(f"  {r.get('full_name', '')} — {r.get('reason', '')} "
                       f"من {r.get('start_date', '')} إلى {r.get('end_date', '')}")
    else:
        out.append("لا غيابات جارية.")
    ev = C.upcoming(env.db, env.today, horizon_days=30)
    if ev:
        out.append(f"مواعيد خلال 30 يوماً ({len(ev)}):")
        for r in ev[:12]:
            left = r.get("days_left")
            when = "اليوم" if left == 0 else (f"بعد {left} يوماً" if (left or 0) > 0 else "جار")
            out.append(f"  {r.get('start_date', '')} ({when}): {r.get('title', '')} — {r.get('kind_label', '')}")
    else:
        out.append("لا مواعيد خلال 30 يوماً.")
    al = P.progress_alerts(env.db, env.fids(), env.today)
    if al:
        out.append(f"تنبيهات ({len(al)}):")
        for a in al[:10]:
            out.append("  " + a["title"])
    return "\n".join(out)
