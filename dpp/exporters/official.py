"""ورقة البرنامج الأسبوعي الرسمية (نموذج المدرسة): الأيام أسطر والحصص أعمدة.

هذه الوحدة لا تعتمد على Qt: تبني «ورقة» (Sheet) من قاعدة البيانات، وتحفظ نصوص القالب لكل طور،
وتصدّر إلى Excel. الرسم والمعاينة والطباعة في ui/sheet_view.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..db.database import Database
from ..utils import DAY_NAMES, hm, iso, to_date, week_days, week_start

# ------------------------------------------------------------------ الأعداد الترتيبية
_ORD = ["", "الأول", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع", "العاشر"]
_ORD_C = ["", "الحادي", "الثاني", "الثالث", "الرابع", "الخامس", "السادس", "السابع", "الثامن", "التاسع"]
_TENS = {2: "العشرون", 3: "الثلاثون", 4: "الأربعون", 5: "الخمسون", 6: "الستون", 7: "السبعون"}


def arabic_ordinal(n: int) -> str:
    """1 → الأول، 11 → الحادي عشر، 21 → الحادي والعشرون."""
    if n <= 0:
        return str(n)
    if n <= 10:
        return _ORD[n]
    if n < 20:
        return f"{_ORD_C[n - 10]} عشر"
    t, u = divmod(n, 10)
    if t not in _TENS:
        return str(n)
    return _TENS[t] if u == 0 else f"{_ORD_C[u]} و{_TENS[t]}"


def week_number(db: Database, d) -> int:
    """رقم الأسبوع من بداية السنة الدراسية (إعداد week1_start)."""
    w1 = to_date(db.get_setting("week1_start", "2026-09-13") or "2026-09-13")
    return (week_start(d) - week_start(w1)).days // 7 + 1


def school_year(db: Database, d) -> str:
    """«2027/2026» كما في النماذج (تُقرأ من اليمين)."""
    w1 = to_date(db.get_setting("week1_start", "2026-09-13") or "2026-09-13")
    y = w1.year if to_date(d) >= w1 else w1.year - 1
    return f"{y + 1}/{y}"


def ymd(d) -> str:
    return to_date(d).strftime("%Y/%m/%d")


# ------------------------------------------------------------------ نصوص القالب
COMMON = {
    "republic": "الجمهورية الجزائرية الديمقراطية الشعبية",
    "right_block": "وزارة الدفاع الوطني\nالناحية العسكرية الأولى\nمدرسة تقنيات المعتمدية\nالشهيد الجيلالي بونعامة\n"
                   "مديرية التعليم\nدائرة التخطيط والبرمجة",
    "approval": "مصادقة قائد مدرسة تقنيات المعتمدية\nالشهيد الجيلالي بونعامة /ن ع 1",
    "note": "ملاحظة: في حالة غياب الأستاذ يعوض مباشرة من طرف رئيس الدائرة",
    "created": "تم إنشاء الجدول: {today}",
    "sign_right": "رئيس مكتب التخطيط والبرمجة",
    "sign_center": "رئيس دائرة التخطيط والبرمجة",
    "sign_left": "مدير التعليم",
}
DEFAULT_FIELDS = {
    "section": COMMON | {
        "left_block": "السنة الدراسية : {year}\n{level}\nالقاعة : {room}",
        "center_block": "الأسبوع : {week_words}\nالمقرر رقم : {decree} المؤرخ في {decree_date}\n"
                        "البرنامج الأسبوعي الدراسي لـ : {target}\nإختصاص : {level}\n"
                        "خلال الفترة الممتدة من : {d0} إلى غاية : {d1}",
    },
    "teacher": COMMON | {
        "left_block": "السنة الدراسية : {year}",
        "center_block": "الأسبوع : {week_words}\nالبرنامج الأسبوعي للأستاذ : {target}\n"
                        "خلال الفترة الممتدة من : {d0} إلى غاية : {d1}",
        "note": "الحجم الساعي للأسبوع: {hours} سا",
    },
    "room": COMMON | {
        "left_block": "السنة الدراسية : {year}",
        "center_block": "الأسبوع : {week_words}\nبرنامج استغلال : {target}\n"
                        "خلال الفترة الممتدة من : {d0} إلى غاية : {d1}",
        "note": "",
    },
    "report": COMMON | {
        "left_block": "السنة الدراسية : {year}\nتاريخ الطباعة : {today}",
        "center_block": "{title}\n{info}",
        "note": "",
        "created": "",
    },
}
FIELD_LABELS = {
    "republic": "الجمهورية", "right_block": "الرأس الأيمن", "left_block": "الرأس الأيسر", "approval": "المصادقة",
    "center_block": "وسط الرأس", "note": "الملاحظة", "created": "تاريخ الإنشاء", "sign_right": "التوقيع الأيمن",
    "sign_center": "التوقيع الأوسط", "sign_left": "التوقيع الأيسر",
}
# مقررات الاختصاصات الموجودة في النماذج (تُعبّأ مرة واحدة إذا كانت فارغة)
KNOWN_DECREES = [
    ("BMP1", "تسخين وتبريد", "2012/013/أج و ش/ب1", "2012/05/31"),
    ("BMP1", "كتابة الضبط", "2013/036/أج و ش/ب1", "2013/06/08"),
    ("BMP1", "فندقة+تكوين مكونين", "2014/85/أج و ش/ب1", "2014/11/29"),
    ("BMP1", "تكوين مكونين-تمويين وتسيير", "2014/085/و د و/أ ج ش/ب1", "29 نوفمبر 2014"),
    ("BMP1", "تكوين مكونين-أمانة وموارد بشرية", "2014/085/و د و/أ ج ش/ب1", "29 نوفمبر 2014"),
    ("BMP1", "تكوين مكونين-ميزانية ومالية", "2014/085/و د و/أ ج ش/ب1", "29 نوفمبر 2014"),
]
STYLE = {"font": "Arial", "head_pt": 9.0, "center_pt": 10.0, "title_pt": 8.5, "sub_pt": 6.5,
         "title_bold": True, "title_italic": True, "title_underline": True}
_TPL_KEY = "official_tpl"


def seed_decrees(db: Database) -> int:
    """يعبّئ أرقام المقررات المعروفة في الاختصاصات التي ليس لها مقرر."""
    n = 0
    for code, needle, dec, dd in KNOWN_DECREES:
        for s in db.q("""SELECT sp.id, sp.name FROM specialties sp JOIN levels l ON l.id=sp.level_id
                         WHERE l.code=? AND COALESCE(sp.decree,'')=''""", (code,)):
            name = s["name"].replace(" ", "")
            if needle.replace(" ", "") in name and (needle != "تسخين وتبريد" or "مكونين" not in name):
                db.execute("UPDATE specialties SET decree=?, decree_date=? WHERE id=?", (dec, dd, s["id"]))
                n += 1
    if n:
        db.commit()
    return n


def seed_decrees_once(db: Database):
    if db.get_setting("decrees_seeded", "") != "1":
        seed_decrees(db)
        db.set_setting("decrees_seeded", 1)


def load_store(db: Database) -> dict:
    try:
        return json.loads(db.get_setting(_TPL_KEY, "") or "{}")
    except ValueError:
        return {}


def scope_of(kind: str, level_id: int | None) -> str:
    return f"level:{level_id}" if kind == "section" and level_id else kind


def template_fields(db: Database, kind: str, level_id: int | None = None) -> dict:
    st = load_store(db)
    out = dict(DEFAULT_FIELDS[kind])
    out.update({k: v for k, v in st.get("global", {}).items() if k in COMMON})
    out.update(st.get(scope_of(kind, level_id), {}))
    return out


def template_style(db: Database) -> dict:
    return STYLE | load_store(db).get("style", {})


def save_template_fields(db: Database, scope: str, fields: dict):
    """scope: «global» (كل الأطوار) أو «level:ID» أو «teacher» أو «room»."""
    st = load_store(db)
    cur = st.setdefault(scope, {})
    for k, v in fields.items():
        if scope == "global" and k not in COMMON:
            continue
        cur[k] = v
    db.set_setting(_TPL_KEY, json.dumps(st, ensure_ascii=False))


def reset_template(db: Database, scope: str):
    st = load_store(db)
    st.pop(scope, None)
    db.set_setting(_TPL_KEY, json.dumps(st, ensure_ascii=False))


_PH = re.compile(r"\{(\w+)\}")


def fill(raw: str, values: dict) -> str:
    lines = []
    for line in (raw or "").split("\n"):
        keys = _PH.findall(line)
        if "decree" in keys and not values.get("decree"):
            continue                       # سطر المقرر يختفي إذا لم يُحدد مقرر للاختصاص
        lines.append(_PH.sub(lambda m: str(values.get(m.group(1), m.group(0))), line))
    return "\n".join(lines)


def unfill(text: str, raw: str, values: dict) -> str:
    """يعيد القيم المتغيرة (اسم القسم، التواريخ…) إلى رموزها قبل حفظ النص في القالب."""
    out = text
    # الأطول أولاً حتى لا يُستبدل جزء من قيمة أطول
    for k, v in sorted(values.items(), key=lambda kv: -len(str(kv[1]))):
        v = str(v)
        if len(v) >= 2 and ("{" + k + "}") in raw and v in out:
            out = out.replace(v, "{" + k + "}")
    # سطر المقرر المخفي (لأن هذا الاختصاص بلا مقرر) يبقى في القالب لبقية الاختصاصات
    if not values.get("decree"):
        lines = out.split("\n")
        for i, line in enumerate((raw or "").split("\n")):
            if "{decree}" in line and line not in lines:
                lines.insert(min(i, len(lines)), line)
        out = "\n".join(lines)
    return out


# ------------------------------------------------------------------ الورقة
@dataclass
class SheetCell:
    day: int                  # 0 = الأحد
    c0: int                   # أول عمود (فهرس في periods)
    c1: int                   # آخر عمود
    title: str
    sub: str = ""             # «الرتبة: الاسم» أو القسم
    corner: str = ""          # القاعة
    note: str = ""            # الوقت إذا لم يطابق الحصة، أو الحالة
    color: str | None = None
    kind: str = "teach"


@dataclass
class Sheet:
    kind: str                         # section | teacher | room
    target_id: int
    ws: date
    scope: str
    level_id: int | None
    raw: dict                         # نصوص القالب الخام (فيها {رموز})
    values: dict                      # القيم المتغيرة
    fields: dict                      # النصوص النهائية
    days: list[str]
    periods: list[tuple[str, str]]    # (اسم الحصة، «16:00 - 14:00»)
    cells: list[SheetCell] = field(default_factory=list)
    style: dict = field(default_factory=dict)
    name: str = ""                    # اسم قصير للملف
    edits: dict = field(default_factory=dict)   # تعديلات لهذه الطباعة فقط (مفتاح → نص)
    section_id: int | None = None
    layout: dict = field(default_factory=dict)  # التخطيط البصري الفعلي (exporters/layout.py)
    layout_scopes: list = field(default_factory=list)   # النطاقات التي جاء منها التخطيط

    def text(self, key: str) -> str:
        return self.edits.get(key, self.fields.get(key, ""))


def _session_rows(db: Database, d0: date, d1: date, section_id=None, teacher_id=None, room_id=None):
    sql = """SELECT s.id, s.date, s.start_min, s.end_min, s.status, s.is_makeup, s.room_id,
                    sub.name sname, sub.kind skind, sub.color,
                    t.full_name tname, t.rank trank, st.full_name stname, st.rank strank,
                    r.name rname, r.short rshort,
                    GROUP_CONCAT(DISTINCT sec.short) secs, GROUP_CONCAT(DISTINCT sec.id) sec_ids,
                    GROUP_CONCAT(DISTINCT CASE WHEN g.is_whole=0 THEN g.name END) gnames
             FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
             LEFT JOIN teachers t ON t.id=s.teacher_id LEFT JOIN teachers st ON st.id=s.substitute_id
             LEFT JOIN rooms r ON r.id=s.room_id
             LEFT JOIN session_groups sg ON sg.session_id=s.id LEFT JOIN groups_ g ON g.id=sg.group_id
             LEFT JOIN sections sec ON sec.id=g.section_id
             WHERE s.date BETWEEN ? AND ? AND s.status NOT IN ('cancelled','tray')"""
    p: list = [iso(d0), iso(d1)]
    if teacher_id:
        sql += " AND COALESCE(s.substitute_id, s.teacher_id)=?"
        p.append(teacher_id)
    if room_id:
        sql += " AND s.room_id=?"
        p.append(room_id)
    sql += " GROUP BY s.id ORDER BY s.date, s.start_min"
    rows = [dict(r) for r in db.q(sql, p)]
    if section_id:
        rows = [r for r in rows if str(section_id) in (r["sec_ids"] or "").split(",")]
    return rows


def _who(r: dict) -> str:
    if r.get("stname"):
        return f"{r['strank'] + ': ' if r.get('strank') else ''}{r['stname']}"
    if r.get("tname"):
        return f"{r['trank'] + ': ' if r.get('trank') else ''}{r['tname']}"
    return ""


def _profile_periods(db: Database, profile: str):
    rows = db.q("SELECT * FROM periods WHERE profile=? ORDER BY idx", (profile,)) or \
        db.q("SELECT * FROM periods WHERE profile='standard' ORDER BY idx")
    return [(r["label"], r["start_min"], r["end_min"], r["kind"] or "day") for r in rows]


def _place(rows: list[dict], periods, days: list[date], cell_of) -> list[SheetCell]:
    """يوزع الحصص على خانات (يوم × مجال حصص)، ويجمع المتداخلة في خانة واحدة."""
    cells: list[SheetCell] = []
    for di, d in enumerate(days):
        day_rows = sorted((r for r in rows if r["date"] == iso(d)), key=lambda r: (r["start_min"], r["end_min"]))
        groups: list[list] = []        # [c0, c1, [rows]]
        for r in day_rows:
            hit = [i for i, p in enumerate(periods) if p[1] < r["end_min"] and p[2] > r["start_min"]]
            if not hit:
                continue
            c0, c1 = hit[0], hit[-1]
            if groups and c0 <= groups[-1][1]:
                groups[-1][1] = max(groups[-1][1], c1)
                groups[-1][2].append(r)
            else:
                groups.append([c0, c1, [r]])
        for c0, c1, rs in groups:
            cells.append(cell_of(di, c0, c1, rs, periods))
    return cells


def _status_note(r: dict, periods, c0, c1) -> str:
    bits = []
    if r["start_min"] != periods[c0][1] or r["end_min"] != periods[c1][2]:
        bits.append(f"{hm(r['start_min'])} - {hm(r['end_min'])}")
    if r["status"] == "postponed":
        bits.append("مؤجلة")
    if r.get("is_makeup"):
        bits.append("تعويضية")
    return " · ".join(bits)


def _common_values(db: Database, ws: date) -> dict:
    days = week_days(ws)
    n = week_number(db, ws)
    return {"year": school_year(db, ws), "week": n, "week_words": arabic_ordinal(n),
            "d0": ymd(days[0]), "d1": ymd(days[-1]), "today": date.today().strftime("%d/%m/%Y")}


def _used_periods(periods, rows):
    """يحذف الفترة الليلية إذا لم تُستعمل هذا الأسبوع."""
    keep = []
    for p in periods:
        if p[3] == "night" and not any(r["start_min"] < p[2] and r["end_min"] > p[1] for r in rows):
            continue
        keep.append(p)
    return keep


def _finish(db, kind, target_id, ws, level_id, values, periods, cells, name) -> Sheet:
    from . import layout as L
    raw = template_fields(db, kind, level_id)
    values = {"institution": db.get_setting("institution_name", "")} | values
    sec_id = target_id if kind == "section" else None
    lay, used = L.effective(db, kind, level_id, sec_id)
    return Sheet(kind=kind, target_id=target_id, ws=ws, scope=scope_of(kind, level_id), level_id=level_id,
                 raw=raw, values=values, fields={k: fill(v, values) for k, v in raw.items()},
                 days=list(DAY_NAMES), periods=[(p[0], f"{hm(p[1])} - {hm(p[2])}") for p in periods],
                 cells=cells, style=template_style(db), name=name, section_id=sec_id, layout=lay,
                 layout_scopes=used)


def build_section_sheet(db: Database, section_id: int, ws) -> Sheet:
    seed_decrees_once(db)
    ws = week_start(ws)
    days = week_days(ws)
    sec = db.one("""SELECT s.*, l.name lname, l.full_name lfull, l.profile lprof, sp.decree, sp.decree_date,
                           sp.name spname, f.name fname,
                           r.name room FROM sections s LEFT JOIN levels l ON l.id=s.level_id
                    LEFT JOIN formations f ON f.id=s.formation_id
                    LEFT JOIN specialties sp ON sp.id=s.specialty_id LEFT JOIN rooms r ON r.id=s.room_id
                    WHERE s.id=?""", (section_id,))
    rows = _session_rows(db, days[0], days[-1], section_id=section_id)
    periods = _used_periods(_profile_periods(db, sec["profile"] or sec["lprof"] or "standard"), rows)

    def cell_of(di, c0, c1, rs, ps):
        if len(rs) == 1:
            r = rs[0]
            title = r["sname"] + (f" ({r['gnames']})" if r.get("gnames") else "")
            return SheetCell(di, c0, c1, title, _who(r), r.get("rname") or "", _status_note(r, ps, c0, c1),
                             r.get("color"), r.get("skind") or "teach")
        title = " / ".join(dict.fromkeys(x["sname"] + (f" ({x['gnames']})" if x.get("gnames") else "") for x in rs))
        sub = " / ".join(dict.fromkeys(w for w in (_who(x) for x in rs) if w))
        rooms = " / ".join(dict.fromkeys(x["rname"] for x in rs if x.get("rname")))
        return SheetCell(di, c0, c1, title, sub, rooms, "", None, rs[0].get("skind") or "teach")

    values = _common_values(db, ws) | {
        "target": sec["name"], "section": sec["name"], "short": sec["short"] or "",
        "level": sec["lfull"] or sec["lname"] or "", "room": "",
        "decree": sec["decree"] or "", "decree_date": sec["decree_date"] or "",
        "specialty": sec["spname"] or "", "formation": sec["fname"] or ""}
    return _finish(db, "section", section_id, ws, sec["level_id"], values, periods,
                   _place(rows, periods, days, cell_of), sec["short"] or sec["name"])


def _majority_profile(db: Database, rows) -> str:
    ids = [int(x) for r in rows for x in (r["sec_ids"] or "").split(",") if x]
    if not ids:
        return "standard"
    prof = db.q(f"""SELECT COALESCE(s.profile, l.profile, 'standard') p, COUNT(*) n FROM sections s
                    LEFT JOIN levels l ON l.id=s.level_id WHERE s.id IN ({','.join(map(str, set(ids)))})
                    GROUP BY p ORDER BY n DESC""")
    return prof[0]["p"] if prof else "standard"


def build_teacher_sheet(db: Database, teacher_id: int, ws) -> Sheet:
    ws = week_start(ws)
    days = week_days(ws)
    t = db.one("SELECT * FROM teachers WHERE id=?", (teacher_id,))
    rows = _session_rows(db, days[0], days[-1], teacher_id=teacher_id)
    periods = _used_periods(_profile_periods(db, _majority_profile(db, rows)), rows)

    def cell_of(di, c0, c1, rs, ps):
        title = " / ".join(dict.fromkeys(x["sname"] for x in rs))
        sub = " / ".join(dict.fromkeys(x["secs"] or "" for x in rs if x.get("secs")))
        rooms = " / ".join(dict.fromkeys(x["rname"] for x in rs if x.get("rname")))
        note = _status_note(rs[0], ps, c0, c1) if len(rs) == 1 else ""
        return SheetCell(di, c0, c1, title, sub, rooms, note, rs[0].get("color"), rs[0].get("skind") or "teach")

    hours = sum(r["end_min"] - r["start_min"] for r in rows if (r.get("skind") or "teach") == "teach") / 60
    values = _common_values(db, ws) | {"target": f"{t['rank'] + ': ' if t['rank'] else ''}{t['full_name']}",
                                       "hours": f"{hours:g}"}
    return _finish(db, "teacher", teacher_id, ws, None, values, periods,
                   _place(rows, periods, days, cell_of), t["full_name"])


def build_room_sheet(db: Database, room_id: int, ws) -> Sheet:
    ws = week_start(ws)
    days = week_days(ws)
    rm = db.one("SELECT * FROM rooms WHERE id=?", (room_id,))
    rows = _session_rows(db, days[0], days[-1], room_id=room_id)
    periods = _used_periods(_profile_periods(db, _majority_profile(db, rows)), rows)

    def cell_of(di, c0, c1, rs, ps):
        title = " / ".join(dict.fromkeys(x["sname"] for x in rs))
        sub = " / ".join(dict.fromkeys(x["secs"] or "" for x in rs if x.get("secs")))
        who = " / ".join(dict.fromkeys(w for w in (_who(x) for x in rs) if w))
        return SheetCell(di, c0, c1, title, sub, who, "", rs[0].get("color"), rs[0].get("skind") or "teach")

    values = _common_values(db, ws) | {"target": rm["name"]}
    return _finish(db, "room", room_id, ws, None, values, periods, _place(rows, periods, days, cell_of), rm["name"])


def build(db: Database, kind: str, target_id: int, ws) -> Sheet:
    return {"section": build_section_sheet, "teacher": build_teacher_sheet, "room": build_room_sheet}[kind](
        db, target_id, ws)


# ------------------------------------------------------------------ قوائم الأهداف
def sections_with_sessions(db: Database, ws, formation_ids: list[int] | None = None, level_id: int | None = None):
    days = week_days(week_start(ws))
    sql = """SELECT DISTINCT sec.id, sec.short, sec.name FROM sessions s
             JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
             JOIN sections sec ON sec.id=g.section_id
             WHERE s.date BETWEEN ? AND ? AND s.status NOT IN ('cancelled','tray')"""
    p: list = [iso(days[0]), iso(days[-1])]
    if formation_ids:
        sql += f" AND sec.formation_id IN ({','.join('?' * len(formation_ids))})"
        p += formation_ids
    if level_id:
        sql += " AND sec.level_id=?"
        p.append(level_id)
    sql += " ORDER BY sec.sort, sec.id"
    return [dict(r) for r in db.q(sql, p)]


def teachers_with_sessions(db: Database, ws):
    days = week_days(week_start(ws))
    return [dict(r) for r in db.q("""SELECT DISTINCT t.id, t.full_name FROM sessions s
                                      JOIN teachers t ON t.id=COALESCE(s.substitute_id, s.teacher_id)
                                      JOIN subjects sub ON sub.id=s.subject_id
                                      WHERE s.date BETWEEN ? AND ? AND s.status NOT IN ('cancelled','tray')
                                      ORDER BY t.full_name""", (iso(days[0]), iso(days[-1])))]


def safe_filename(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", s).strip() or "برنامج"


# ------------------------------------------------------------------ تصدير Excel
def to_xlsx(sheets: list[Sheet], path, show_room: bool = True, color: bool = False):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    thin = Side(style="thin", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    used = set()
    for sh in sheets:
        title = safe_filename(sh.name)[:28] or "ورقة"
        base, i = title, 2
        while title in used:
            title, i = f"{base[:25]}-{i}", i + 1
        used.add(title)
        ws = wb.create_sheet(title)
        ws.sheet_view.rightToLeft = True
        ws.page_setup.orientation = "landscape"
        ws.page_setup.paperSize = ws.PAPERSIZE_A4
        ws.page_setup.fitToWidth = 1
        ws.page_setup.fitToHeight = 1
        ws.sheet_properties.pageSetUpPr.fitToPage = True
        ncol = len(sh.periods) + 1
        f_b = Font(name=sh.style["font"], bold=True, size=sh.style["head_pt"])
        center = Alignment(horizontal="center", vertical="center", wrap_text=True)
        right = Alignment(horizontal="right", vertical="top", wrap_text=True)
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncol)
        ws.cell(1, 1, sh.text("republic")).font = f_b
        ws.cell(1, 1).alignment = center
        ws.cell(2, 1, sh.text("right_block")).alignment = right
        ws.cell(2, 1).font = f_b
        mid = max(2, ncol // 2)
        ws.cell(2, mid, sh.text("center_block")).alignment = center
        ws.cell(2, mid).font = Font(name=sh.style["font"], bold=True, size=sh.style["center_pt"])
        ws.cell(2, ncol, sh.text("left_block") + "\n\n" + sh.text("approval")).alignment = right
        ws.cell(2, ncol).font = f_b
        ws.row_dimensions[2].height = 110
        r0 = 4
        ws.cell(r0, 1, "").border = box
        for j, (lab, tm) in enumerate(sh.periods):
            c = ws.cell(r0, j + 2, f"{lab}\n{tm}")
            c.font, c.alignment, c.border = f_b, center, box
        ws.row_dimensions[r0].height = 30
        for di, dn in enumerate(sh.days):
            c = ws.cell(r0 + 1 + di, 1, dn)
            c.font = Font(name=sh.style["font"], bold=True, size=12)
            c.alignment, c.border = center, box
            ws.row_dimensions[r0 + 1 + di].height = 48
            for j in range(len(sh.periods)):
                ws.cell(r0 + 1 + di, j + 2).border = box
        for cl in sh.cells:
            row = r0 + 1 + cl.day
            key = f"cell:{cl.day}:{cl.c0}"
            parts = [sh.edits.get(key + ":title", cl.title)]
            sub = sh.edits.get(key + ":sub", cl.sub)
            if sub:
                parts.append(sub)
            if show_room and cl.corner:
                parts.append(sh.edits.get(key + ":corner", cl.corner))
            if cl.note:
                parts.append(cl.note)
            if cl.c1 > cl.c0:
                ws.merge_cells(start_row=row, start_column=cl.c0 + 2, end_row=row, end_column=cl.c1 + 2)
            c = ws.cell(row, cl.c0 + 2, "\n".join(parts))
            c.font = Font(name=sh.style["font"], bold=True, italic=True, size=sh.style["title_pt"])
            c.alignment = center
            if color and cl.color and cl.color.startswith("#") and len(cl.color) == 7:
                h = cl.color[1:]
                rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
                light = "".join(f"{int(x + (255 - x) * 0.7):02X}" for x in rgb)
                c.fill = PatternFill("solid", fgColor=light)
        foot = r0 + 2 + len(sh.days)
        ws.cell(foot, 1, sh.text("note")).font = f_b
        ws.cell(foot + 1, 1, sh.text("created"))
        ws.cell(foot + 3, 1, sh.text("sign_right")).font = f_b
        ws.cell(foot + 3, mid, sh.text("sign_center")).font = f_b
        ws.cell(foot + 3, ncol, sh.text("sign_left")).font = f_b
        ws.column_dimensions["A"].width = 12
        for j in range(len(sh.periods)):
            ws.column_dimensions[openpyxl.utils.get_column_letter(j + 2)].width = 30
    wb.save(path)
    return path


def week_label(db: Database, ws) -> str:
    n = week_number(db, ws)
    return f"الأسبوع {n}"


__all__ = ["Sheet", "SheetCell", "build", "build_section_sheet", "build_teacher_sheet", "build_room_sheet",
           "arabic_ordinal", "week_number", "template_fields", "save_template_fields", "seed_decrees", "to_xlsx",
           "sections_with_sessions", "teachers_with_sessions", "unfill", "fill", "FIELD_LABELS", "timedelta"]
