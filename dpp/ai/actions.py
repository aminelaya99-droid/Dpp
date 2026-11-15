"""أدوات «الاقتراح» للمساعد (1.8): النموذج يقترح، والمستخدم يوافق، ثم يُنفَّذ.

قاعدة صارمة: هذه الأدوات **لا تكتب** شيئاً أثناء المحادثة. كل أداة تحسب التغيير (بقراءة فقط)
وتُنشئ «اقتراحاً» (Proposal) فيه قائمة التغييرات بالضبط والتحذيرات. الواجهة تعرضه بطاقةً
فيها «تطبيق» و«تجاهل»؛ لا شيء يُكتب في قاعدة البيانات قبل «تطبيق».

التنفيذ (apply) يجري في خيط الواجهة على قاعدة البيانات الرئيسية:
* نقل/إضافة حصص: عبر نموذج الجدول العام (WeekGrid) داخل مجموعة تراجع واحدة،
  فيُتراجع عنها بـ Ctrl+Z في الجدول العام أو بزر «تراجع» في البطاقة.
* برمجة أسبوع، الخفارة، ملاحظة الأسبوع: يُحفظ ما يلزم للتراجع (الحصص المضافة، التعيينات السابقة…).

برمجة الأسابيع لا يقوم بها النموذج نفسه: يحوّل طلب المستخدم إلى أولويات (مواد وساعات، المتأخرة أولاً)
ثم يبني الجدول محرك OR-Tools الموجود، فيبقى الجدول بلا تعارضات.
"""
from __future__ import annotations

import itertools
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..utils import hm, iso, parse_hm, to_date, week_start
from .tools import DAYS, Env, _Ask, _date, _day_label, _match, _one, _week, tool

_ids = itertools.count(1)


@dataclass
class Proposal:
    kind: str                       # move | add | fill | fix | duty | plan | note
    title: str
    ws: date
    lines: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ops: list[dict] = field(default_factory=list)
    id: int = field(default_factory=lambda: next(_ids))
    state: str = "pending"          # pending | applied | dismissed | undone
    undo: dict | None = None
    result: str = ""

    def summary(self) -> str:
        return f"اقتراح رقم {self.id}: {self.title} ({len(self.lines)} تغيير)"


def _add(env: Env, p: Proposal) -> str:
    if not p.ops:
        raise _Ask("لم أجد ما يمكن اقتراحه: " + (p.warnings[0] if p.warnings else "لا توجد تغييرات ممكنة."))
    env.proposals.append(p)
    txt = [p.summary() + " — جاهز وينتظر موافقة المستخدم بزر «تطبيق» (لم يُنفَّذ بعد):"]
    txt += [f"• {x}" for x in p.lines[:12]]
    if p.warnings:
        txt.append("تحذيرات: " + "؛ ".join(p.warnings[:4]))
    txt.append("قل للمستخدم باختصار ما اقترحتَه، وأنه يستطيع تطبيقه أو تجاهله من البطاقة تحت الجواب.")
    return "\n".join(txt)


# ---------------------------------------------------------------- أدوات مساعدة
def _grid(env: Env, ws: date):
    from ..services.grid import WeekGrid
    key = iso(ws)
    cache = env.cache.setdefault("grids", {})
    if key not in cache:
        cache[key] = WeekGrid(env.db, ws, today=env.today)
    return cache[key]


def _section(env: Env, name: str) -> dict:
    if not name:
        raise _Ask("حدّد القسم (اسمه أو رمزه).")
    return _one(env, "section", name)


def _minutes(hours) -> int:
    try:
        h = float(str(hours).replace(",", ".").replace("سا", "").strip() or 2)
    except ValueError:
        raise _Ask(f"لم أفهم المدة «{hours}». اكتبها بالساعات مثل 1.5 أو 2.")
    m = int(round(h * 2)) * 30
    if not 30 <= m <= 240:
        raise _Ask("المدة يجب أن تكون بين نصف ساعة و4 ساعات.")
    return m


def _start(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return parse_hm(str(value).strip())
    except (ValueError, TypeError):
        raise _Ask(f"لم أفهم الوقت «{value}». اكتبه هكذا: 08:00 أو 13:30.")


def _rng(a: int, b: int) -> str:
    """«من 08:00 إلى 10:00» (الشكل 08:00-10:00 ينقلب بصرياً في سطر عربي)."""
    return f"من {hm(a)} إلى {hm(b)}"


def _card_label(c) -> str:
    return f"«{c.sname}» {_day_label(c.day)} {_rng(c.start, c.end)}"


def _first_free(g, check, section_id: int, day: date, minutes: int, avoid: list[tuple] = ()) -> int | None:
    """أول بداية (بخطوة 30 د) في اليوم بلا تعارض ولا تداخل مع ما اقتُرح قبلها."""
    a = g.day_start(section_id)
    while True:
        b = a + minutes
        if b > g.day_limit(section_id, a):
            return None
        overlap = any(d == day and a < e and s < b for d, s, e in avoid)
        if not overlap and not check(day, a, b):
            return a
        a += 30


# ---------------------------------------------------------------- نقل حصة
@tool("propose_move", "اقتراح نقل حصة موجودة إلى يوم أو وقت آخر (لا يُنفَّذ إلا بموافقة المستخدم). "
      "حدّد القسم واليوم، ووقت بداية الحصة أو مادتها، ثم اليوم والوقت الجديدين.",
      {"section": {"type": "string", "description": "اسم القسم أو رمزه"},
       "day": {"type": "string", "description": "يوم الحصة الحالي: تاريخ أو اسم يوم"},
       "start": {"type": "string", "description": "وقت بداية الحصة الحالي مثل 08:00 (اختياري إن ذُكرت المادة)"},
       "subject": {"type": "string", "description": "مادة الحصة (اختياري)"},
       "new_day": {"type": "string", "description": "اليوم الجديد (بلا قيمة = نفس اليوم)"},
       "new_start": {"type": "string", "description": "وقت البداية الجديد (بلا قيمة = أول وقت متاح)"}},
      ["section", "day"])
def p_move(env: Env, section: str, day, start="", subject="", new_day="", new_start="") -> str:
    sec = _section(env, section)
    d = _date(env, day)
    g = _grid(env, week_start(d))
    cards = [c for c in g.cards.values() if sec["id"] in c.sections and c.day == d and c.status == "planned"]
    a = _start(start)
    if a is not None:
        cards = [c for c in cards if c.start <= a < c.end]
    if subject:
        cards = [c for c in cards if subject in c.sname or subject in (c.sshort or "")]
    if not cards:
        raise _Ask(f"لا توجد حصة مبرمجة للقسم {sec['nm']} يوم {_day_label(d)} بهذه المواصفات.")
    if len(cards) > 1:
        raise _Ask("أكثر من حصة تطابق: " + "، ".join(_card_label(c) for c in cards[:6]) + ". اسأل المستخدم أيّها.")
    c = cards[0]
    nd = _date(env, new_day) if new_day else d
    if week_start(nd) != g.ws:
        raise _Ask("النقل يكون داخل نفس الأسبوع فقط.")
    mins = c.end - c.start
    ns = _start(new_start)
    if ns is None:
        ns = _first_free(g, lambda dd, x, y: g.check_card(c, dd, x, y), sec["id"], nd, mins)
        if ns is None:
            raise _Ask(f"لا يوجد وقت فارغ يوم {_day_label(nd)} يتسع لهذه الحصة.")
    warn = g.check_card(c, nd, ns, ns + mins)
    p = Proposal("move", f"نقل حصة {c.sname} ({sec['alt'] or sec['nm']})", g.ws,
                 [f"نقل {_card_label(c)} إلى {_day_label(nd)} {_rng(ns, ns + mins)}"], list(warn),
                 [{"op": "move", "sid": c.sid, "day": iso(nd), "start": ns, "end": ns + mins}])
    return _add(env, p)


# ---------------------------------------------------------------- إضافة حصة
@tool("propose_add", "اقتراح إضافة حصة مادة لقسم (لا يُنفَّذ إلا بموافقة المستخدم). "
      "بلا يوم أو وقت = أقرب وقت متاح؛ بلا أستاذ = أستاذها المعتاد مع هذا القسم.",
      {"section": {"type": "string", "description": "اسم القسم أو رمزه"},
       "subject": {"type": "string", "description": "اسم المادة"},
       "hours": {"type": "string", "description": "المدة بالساعات (0.5 إلى 4)، الافتراضي 2"},
       "day": {"type": "string", "description": "اليوم (اختياري)"},
       "start": {"type": "string", "description": "وقت البداية مثل 10:00 (اختياري)"},
       "teacher": {"type": "string", "description": "اسم الأستاذ (اختياري)"},
       "week": {"type": "string", "description": "الأسبوع إن لم يُذكر يوم (تاريخ أو رقم)"}},
      ["section", "subject"])
def p_add(env: Env, section: str, subject: str, hours="2", day="", start="", teacher="", week=None) -> str:
    sec = _section(env, section)
    sub = _one(env, "subject", subject)
    mins = _minutes(hours)
    ws = week_start(_date(env, day)) if day else _week(env, week)
    g = _grid(env, ws)
    item = next((it for it in g.subject_items(sec["id"], include_nonteach=True) if it.subject == sub["id"]), None)
    if item is None:
        raise _Ask(f"المادة {sub['nm']} غير متاحة.")
    item.minutes = mins
    tid = _one(env, "teacher", teacher)["id"] if teacher else g.usual_teacher(sec["id"], sub["id"])
    check = lambda d, a, b: g.check_free(item, sec["id"], d, a, b, teacher=tid)
    if day:
        d = _date(env, day)
        a = _start(start)
        if a is None:
            a = _first_free(g, check, sec["id"], d, mins)
            if a is None:
                raise _Ask(f"لا يوجد وقت فارغ يوم {_day_label(d)} للقسم والأستاذ.")
    else:
        slots = g.suggest_slots(item, sec["id"], limit=1, teacher=tid)
        if not slots:
            raise _Ask("لا يوجد وقت فارغ هذا الأسبوع للقسم والأستاذ معاً.")
        d, a = slots[0]["day"], slots[0]["start"]
    tname = env.db.scalar("SELECT full_name FROM teachers WHERE id=?", (tid,), "") if tid else "بلا أستاذ"
    warn = check(d, a, a + mins)
    p = Proposal("add", f"إضافة {sub['nm']} لـ {sec['alt'] or sec['nm']}", ws,
                 [f"إضافة «{sub['nm']}» {_day_label(d)} {_rng(a, a + mins)} مع {tname}"], list(warn),
                 [{"op": "add", "section": sec["id"], "subject": sub["id"], "teacher": tid, "day": iso(d),
                   "start": a, "end": a + mins}])
    return _add(env, p)


# ---------------------------------------------------------------- ملء الفراغات
@tool("propose_fill", "اقتراح إكمال ما ينقص قسماً في أسبوع: يضع المواد الناقصة (حسب الحجم الساعي والأولويات) "
      "في أقرب الأوقات الفارغة. لا يُنفَّذ إلا بموافقة المستخدم.",
      {"section": {"type": "string", "description": "اسم القسم أو رمزه"},
       "week": {"type": "string", "description": "الأسبوع (تاريخ أو رقم)؛ بلا قيمة = الحالي"}},
      ["section"])
def p_fill(env: Env, section: str, week=None) -> str:
    from ..services.planner_tools import needs
    sec = _section(env, section)
    ws = _week(env, week)
    g = _grid(env, ws)
    items = {it.subject: it for it in g.subject_items(sec["id"], include_nonteach=True)}
    taken: list[tuple] = []           # (اليوم، البداية، النهاية) لما اقتُرح للقسم
    by_teacher: dict = {}
    p = Proposal("fill", f"إكمال أسبوع {sec['alt'] or sec['nm']}", ws)
    for n in needs(env.db, sec["id"], ws):
        left = int(round(n["left"] * 60))
        it = items.get(n["subject_id"])
        while left >= 30 and it is not None and len(p.ops) < 12:
            mins = min(left, n["mins"] or 120, 240)
            mins -= mins % 30
            it.minutes = mins
            tid = n["teacher"] or g.usual_teacher(sec["id"], n["subject_id"])
            avoid = taken + by_teacher.get(tid, [])
            spot = None
            for di in range(7):
                d = ws + timedelta(days=di)
                if d < env.today:
                    continue
                a = _first_free(g, lambda dd, x, y: g.check_free(it, sec["id"], dd, x, y, teacher=tid),
                                sec["id"], d, mins, avoid)
                if a is not None:
                    spot = (d, a)
                    break
            if spot is None:
                p.warnings.append(f"لا وقت فارغ لـ «{n['subject']}» ({left / 60:g} سا ناقصة)")
                break
            d, a = spot
            tname = env.db.scalar("SELECT full_name FROM teachers WHERE id=?", (tid,), "") if tid else "بلا أستاذ"
            p.lines.append(f"«{n['subject']}» {_day_label(d)} {_rng(a, a + mins)} مع {tname}")
            p.ops.append({"op": "add", "section": sec["id"], "subject": n["subject_id"], "teacher": tid,
                          "day": iso(d), "start": a, "end": a + mins})
            taken.append((d, a, a + mins))
            by_teacher.setdefault(tid, []).append((d, a, a + mins))
            left -= mins
    if not p.ops and not p.warnings:
        raise _Ask(f"القسم {sec['nm']} لا ينقصه شيء هذا الأسبوع حسب الحجم الساعي.")
    return _add(env, p)


# ---------------------------------------------------------------- إصلاح التعارضات
@tool("propose_fix_conflicts", "اقتراح إصلاح تعارضات أسبوع: لكل تعارض ينقل حصة واحدة إلى أقرب وقت فارغ. "
      "لا يُنفَّذ إلا بموافقة المستخدم.",
      {"week": {"type": "string", "description": "الأسبوع (تاريخ أو رقم)؛ بلا قيمة = الحالي"}})
def p_fix(env: Env, week=None) -> str:
    ws = _week(env, week)
    g = _grid(env, ws)
    p = Proposal("fix", f"إصلاح تعارضات أسبوع {iso(ws)}", ws)
    moved: set[int] = set()
    taken: list[tuple] = []
    for cf in g.conflicts:
        if cf.ignored or len(p.ops) >= 10:
            continue
        cands = [g.cards[s] for s in cf.session_ids if s in g.cards and s not in moved and g.cards[s].status == "planned"]
        if not cands:
            continue
        c = max(cands, key=lambda c: (c.day, c.start))          # ننقل الأحدث في اليوم
        sec_id = c.sections[0] if c.sections else None
        if sec_id is None:
            continue
        spot = None
        for di in range(7):
            d = ws + timedelta(days=di)
            if d < env.today:
                continue
            a = _first_free(g, lambda dd, x, y: g.check_card(c, dd, x, y), sec_id, d, c.end - c.start, taken)
            if a is not None:
                spot = (d, a)
                break
        if spot is None:
            p.warnings.append(f"لم أجد وقتاً بديلاً لـ {_card_label(c)}")
            continue
        d, a = spot
        b = a + c.end - c.start
        p.lines.append(f"{cf.message} ← نقل {_card_label(c)} إلى "
                       f"{_day_label(d)} {_rng(a, b)}")
        p.ops.append({"op": "move", "sid": c.sid, "day": iso(d), "start": a, "end": b})
        moved.add(c.sid)
        taken.append((d, a, b))
    if not p.ops and not p.warnings:
        raise _Ask("لا توجد تعارضات غير متجاهَلة في هذا الأسبوع.")
    return _add(env, p)


# ---------------------------------------------------------------- الخفارة
@tool("propose_duty", "اقتراح توزيع الخفارة والخدمات آلياً بالتناوب العادل لأسبوع (يحتفظ بالتعيين اليدوي). "
      "لا يُنفَّذ إلا بموافقة المستخدم.",
      {"week": {"type": "string", "description": "الأسبوع (تاريخ أو رقم)؛ بلا قيمة = الحالي"}})
def p_duty(env: Env, week=None) -> str:
    from ..services import duty as D
    ws = _week(env, week)
    ts = D.types(env.db, active_only=True)
    if not ts:
        raise _Ask("لا توجد أنواع خفارة أو خدمات مفعّلة (صفحة الخفارة والخدمات).")
    have = len(D.assignments(env.db, ws, ws + timedelta(days=6)))
    p = Proposal("duty", f"توزيع الخفارة والخدمات لأسبوع {iso(ws)}", ws,
                 [f"توزيع آلي عادل لـ: {'، '.join(t['name'] for t in ts)} من {iso(ws)} إلى {iso(ws + timedelta(days=6))}",
                  "التعيينات اليدوية تبقى كما هي، والتوزيع الآلي السابق لهذا الأسبوع يُعاد حسابه"],
                 [f"في هذا الأسبوع {have} تعيين حالياً"] if have else [],
                 [{"op": "duty", "start": iso(ws), "end": iso(ws + timedelta(days=6))}])
    return _add(env, p)


# ---------------------------------------------------------------- برمجة أسبوع
FOCUS_RE = re.compile(r"\s*([^=:،,;]+?)\s*[=:]\s*([0-9]+(?:[.,][0-9]+)?)")


@tool("propose_week_plan", "برمجة أسبوع آلياً بمحرك البرنامج (OR-Tools) حسب طلب المستخدم، ثم عرض النتيجة للموافقة. "
      "scope: قسم أو طور أو تكوين (بلا قيمة = كل الأقسام). focus: مواد بساعات محددة هذا الأسبوع مثل "
      "«الرماية=6، التاريخ=4». late_first: إعطاء ساعات أكثر للمواد المتأخرة عن المقرر.",
      {"week": {"type": "string", "description": "الأسبوع (تاريخ أو رقم)؛ بلا قيمة = الأسبوع القادم"},
       "scope": {"type": "string", "description": "اسم قسم أو طور أو تكوين (اختياري)"},
       "focus": {"type": "string", "description": "مواد وساعاتها: مادة=ساعات، مفصولة بفاصلة (اختياري)"},
       "late_first": {"type": "boolean", "description": "المتأخرة أولاً (الافتراضي نعم)"}})
def p_plan(env: Env, week=None, scope="", focus="", late_first=True) -> str:
    from ..scheduler.engine import available, unavailable_message
    from ..services import priorities as PRI
    if not available():
        raise _Ask(unavailable_message())
    ws = _week(env, week) if week not in (None, "") else week_start(env.today) + timedelta(days=7)
    db = env.db
    # النطاق → (تكوين، أفواج)
    groups_by_f: dict[int, list[int]] = {}
    label = "كل الأقسام"
    sec_ids: list[int] = []
    if scope:
        for kind in ("section", "level", "formation"):
            rows = _match(env, kind, scope)
            if len(rows) == 1:
                r = rows[0]
                label = r["nm"]
                col = {"section": "s.id", "level": "s.level_id", "formation": "s.formation_id"}[kind]
                sec_ids = [x[0] for x in db.q(f"SELECT s.id FROM sections s WHERE {col}=?", (r["id"],))]
                break
        else:
            raise _Ask(f"لم أعرف «{scope}»: اكتب اسم قسم أو طور أو تكوين كما هو في البرنامج.")
    else:
        fids = env.fids()
        sec_ids = [x[0] for x in db.q(f"SELECT id FROM sections WHERE formation_id IN ({','.join('?' * len(fids)) or '0'})",
                                      fids)]
    for s in sec_ids:
        f = db.scalar("SELECT formation_id FROM sections WHERE id=?", (s,))
        groups_by_f.setdefault(f, []).extend(x[0] for x in db.q("SELECT id FROM groups_ WHERE section_id=?", (s,)))
    if not groups_by_f:
        raise _Ask("لا توجد أقسام في هذا النطاق.")
    # الأولويات المؤقتة لهذا الطلب
    cfg = PRI.load(db)
    cfg = dict(cfg, enabled=True)
    cfg["late_first"] = bool(late_first) if not isinstance(late_first, str) else late_first not in ("false", "لا", "0")
    targets = list(cfg.get("targets") or [])
    asked = []
    for m in FOCUS_RE.finditer(str(focus or "")):
        sub = _one(env, "subject", m.group(1).strip())
        h = float(m.group(2).replace(",", "."))
        asked.append(f"{sub['nm']} {h:g} سا")
        for s in sec_ids:
            targets.append({"scope": "section", "ref": s, "subject": sub["id"], "hours": h})
    cfg["targets"] = targets
    from ..scheduler.engine import Scheduler
    sched = Scheduler(db, time_limit=float(db.get_setting("engine_time_limit", "20") or 20))
    p = Proposal("plan", f"برمجة أسبوع {iso(ws)} — {label}", ws)
    total = 0
    for fid, groups in groups_by_f.items():
        override, _rows = PRI.week_plan(db, fid, ws, groups, cfg, create_missing=False)
        res = sched.schedule_week(fid, ws, groups, hours_override=override, rules=cfg.get("rules"),
                                  exclude_timetable=-1)
        per_sec: dict[str, float] = {}
        for pl in res.placements:
            secs = {db.scalar("SELECT s.short FROM groups_ g JOIN sections s ON s.id=g.section_id WHERE g.id=?", (g,))
                    for g in pl.meeting.group_ids}
            for sname in secs:
                per_sec[sname] = per_sec.get(sname, 0) + (pl.end_min - pl.start_min) / 60
            p.ops.append({"op": "session", "formation": fid, "day": iso(pl.day), "start": pl.start_min,
                          "end": pl.end_min, "subject": pl.meeting.subject_id, "teacher": pl.meeting.teacher_id,
                          "room": pl.room_id, "groups": list(pl.meeting.group_ids),
                          "req": pl.meeting.requirement_ids[0] if pl.meeting.requirement_ids else None})
        total += len(res.placements)
        for sname, h in sorted(per_sec.items()):
            p.lines.append(f"{sname}: {h:g} سا جديدة")
        for u in res.unplaced[:6]:
            p.warnings.append(f"{u.meeting.label}: {u.reason}")
    if asked:
        p.lines.insert(0, "التركيز المطلوب: " + "، ".join(asked))
    p.lines.insert(0, f"{total} حصة جديدة يضعها المحرك (الحصص الموجودة تبقى كما هي)")
    return _add(env, p)


# ---------------------------------------------------------------- ملاحظة الأسبوع
@tool("propose_week_note", "اقتراح كتابة ملاحظة لأسبوع (تظهر في صفحة الأسابيع). لا تُحفظ إلا بموافقة المستخدم.",
      {"week": {"type": "string", "description": "الأسبوع (تاريخ أو رقم)؛ بلا قيمة = الحالي"},
       "text": {"type": "string", "description": "نص الملاحظة"}}, ["text"])
def p_note(env: Env, text: str, week=None) -> str:
    ws = _week(env, week)
    p = Proposal("note", f"ملاحظة أسبوع {iso(ws)}", ws, [f"«{str(text).strip()[:300]}»"], [],
                 [{"op": "note", "text": str(text).strip()}])
    return _add(env, p)


ACTION_TOOLS = ["propose_move", "propose_add", "propose_fill", "propose_fix_conflicts", "propose_duty",
                "propose_week_plan", "propose_week_note"]


# ====================================================================== التنفيذ (خيط الواجهة)
class ApplyError(Exception):
    pass


def apply(db, p: Proposal, grid=None) -> str:
    """ينفّذ اقتراحاً على القاعدة الرئيسية. grid: نموذج الجدول العام لنفس الأسبوع (للتراجع بـ Ctrl+Z)."""
    if p.state == "applied":
        raise ApplyError("طُبّق هذا الاقتراح من قبل.")
    kinds = {o["op"] for o in p.ops}
    if kinds <= {"move", "add"}:
        msg = _apply_grid(db, p, grid)
    elif kinds == {"session"}:
        msg = _apply_sessions(db, p)
    elif kinds == {"duty"}:
        msg = _apply_duty(db, p)
    elif kinds == {"note"}:
        msg = _apply_note(db, p)
    else:
        raise ApplyError("نوع اقتراح غير معروف.")
    p.state = "applied"
    p.result = msg
    db.log("تطبيق اقتراح المساعد", "ai", p.id, {"title": p.title, "changes": len(p.ops)})
    return msg


def _apply_grid(db, p: Proposal, grid) -> str:
    from ..services.grid import WeekGrid
    g = grid if grid is not None and grid.ws == p.ws else WeekGrid(db, p.ws)
    g.reload()
    done = 0
    g.begin_group()
    try:
        for o in p.ops:
            if o["op"] == "move":
                c = g.cards.get(o["sid"])
                if c is None:
                    raise ApplyError("الحصة لم تعد موجودة (تغيّر الجدول منذ الاقتراح). اطلب اقتراحاً جديداً.")
                g.move(c, to_date(o["day"]), o["start"], o["end"], label="المساعد: نقل حصة")
            else:
                item = next((it for it in g.subject_items(o["section"], include_nonteach=True)
                             if it.subject == o["subject"]), None)
                if item is None:
                    raise ApplyError("المادة لم تعد متاحة.")
                item.minutes = o["end"] - o["start"]
                g.place_free(item, o["section"], o["teacher"], to_date(o["day"]), o["start"], o["end"])
            done += 1
    finally:
        g.end_group(f"المساعد: {p.title}")
    g.reload()
    p.undo = {"grid": g, "depth": len(g.undo_stack)}
    return f"طُبّق: {done} تغيير. للتراجع: زر «تراجع» هنا أو Ctrl+Z في الجدول العام."


def _apply_sessions(db, p: Proposal) -> str:
    from ..services import timetables as T
    created = []
    with db.tx():
        for o in p.ops:
            tt = T.get_or_create_timetable(db, o["formation"], p.ws)
            created.append(T.create_session(db, tt, to_date(o["day"]), o["start"], o["end"], o["subject"],
                                            o["teacher"], o["room"], o["groups"], o["req"], manual=False, force=True))
    p.undo = {"sessions": created}
    return f"أُضيفت {len(created)} حصة. للتراجع: زر «تراجع» هنا."


def _apply_duty(db, p: Proposal) -> str:
    from ..services import duty as D
    o = p.ops[0]
    before = [dict(r) for r in db.q("SELECT * FROM duty_assignments WHERE date BETWEEN ? AND ?", (o["start"], o["end"]))]
    res = D.generate(db, o["start"], o["end"])
    p.undo = {"duty": before, "range": (o["start"], o["end"])}
    miss = f"، تعذّر {len(res.get('missing', []))}" if res.get("missing") else ""
    return f"وُزّعت {res.get('placed', 0)} مناوبة{miss}. للتراجع: زر «تراجع» هنا."


def _apply_note(db, p: Proposal) -> str:
    from ..services import weeks as WK
    before = WK.notes(db).get(iso(p.ws), "")
    WK.set_note(db, p.ws, p.ops[0]["text"])
    p.undo = {"note": before}
    return "حُفظت الملاحظة في صفحة الأسابيع."


def undo(db, p: Proposal) -> str:
    """التراجع عن اقتراح طُبّق (من البطاقة نفسها)."""
    if p.state != "applied" or not p.undo:
        raise ApplyError("لا يوجد ما يُتراجع عنه.")
    u = p.undo
    if "grid" in u:
        g = u["grid"]
        if len(g.undo_stack) != u["depth"]:
            raise ApplyError("أُجريت تعديلات أخرى بعده في الجدول العام: تراجع من هناك بـ Ctrl+Z.")
        g.undo()
    elif "sessions" in u:
        with db.tx():
            for sid in u["sessions"]:
                db.execute("DELETE FROM session_groups WHERE session_id=?", (sid,))
                db.execute("DELETE FROM sessions WHERE id=?", (sid,))
    elif "duty" in u:
        a, b = u["range"]
        with db.tx():
            db.execute("DELETE FROM duty_assignments WHERE date BETWEEN ? AND ?", (a, b))
            for r in u["duty"]:
                db.insert("duty_assignments", **{k: v for k, v in r.items() if k != "id"})
    elif "note" in u:
        from ..services import weeks as WK
        WK.set_note(db, p.ws, u["note"])
    p.state = "undone"
    db.log("تراجع عن اقتراح المساعد", "ai", p.id, {"title": p.title})
    return "تم التراجع."


_ = (DAYS, date)
