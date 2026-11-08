"""نموذج مستند مستقل عن الصيغة + بناء الجداول والتقارير من قاعدة البيانات."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..db.database import Database
from ..utils import DAY_NAMES, STATUS_LABELS, hm, hm_range, iso, parse_rest_days, to_date, week_days


@dataclass
class Cell:
    row: int
    col: int
    rowspan: int
    text: str
    color: str | None = None


@dataclass
class Grid:
    col_labels: list[str]
    row_labels: list[str]
    cells: list[Cell] = field(default_factory=list)


@dataclass
class Table:
    headers: list[str]
    rows: list[list]
    widths: list[float] | None = None   # نسب تقريبية


@dataclass
class Report:
    title: str
    info_lines: list[str] = field(default_factory=list)
    blocks: list = field(default_factory=list)       # Grid | Table | str (فقرة)
    institution: str = ""
    logo: str = ""


def _base(db: Database, title: str, tpl: dict) -> Report:
    r = Report(title=title)
    if tpl["show"].get("institution"):
        r.institution = db.get_setting("institution_name")
    if tpl["show"].get("logo"):
        r.logo = db.get_setting("institution_logo")
    r.info_lines += list(tpl.get("header_lines") or [])
    return r


def _sessions(db: Database, d0: date, d1: date, formation_id=None, section_id=None, teacher_id=None, group_id=None):
    sql = """SELECT s.*, sub.name sname, sub.short sshort, sub.color, r.short rshort, r.name rname,
                    t.full_name tname, t.rank trank, st.full_name stname,
                    GROUP_CONCAT(DISTINCT g.name) gnames, GROUP_CONCAT(DISTINCT sec.short) secs,
                    GROUP_CONCAT(DISTINCT sec.id) sec_ids, GROUP_CONCAT(DISTINCT g.id) gids
             FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
             LEFT JOIN rooms r ON r.id=s.room_id LEFT JOIN teachers t ON t.id=s.teacher_id
             LEFT JOIN teachers st ON st.id=s.substitute_id
             LEFT JOIN session_groups sg ON sg.session_id=s.id LEFT JOIN groups_ g ON g.id=sg.group_id
             LEFT JOIN sections sec ON sec.id=g.section_id
             LEFT JOIN timetables tt ON tt.id=s.timetable_id
             WHERE s.date>=? AND s.date<=? AND s.status<>'cancelled'"""
    p: list = [iso(d0), iso(d1)]
    if formation_id:
        sql += " AND (tt.formation_id=? OR sec.formation_id=?)"
        p += [formation_id, formation_id]
    if teacher_id:
        sql += " AND COALESCE(s.substitute_id, s.teacher_id)=?"
        p.append(teacher_id)
    sql += " GROUP BY s.id ORDER BY s.date, s.start_min"
    rows = [dict(r) for r in db.q(sql, p)]
    if section_id:
        rows = [r for r in rows if str(section_id) in (r["sec_ids"] or "").split(",")]
    if group_id:
        rows = [r for r in rows if str(group_id) in (r["gids"] or "").split(",")]
    return rows


def session_text(r: dict, show: dict, with_section=False) -> str:
    parts = []
    if show.get("subject", True):
        parts.append(r["sname"])
    if with_section and r.get("secs"):
        parts.append(r["secs"])
    if r.get("gnames") and "الفوج الكامل" not in (r["gnames"] or "") and not with_section:
        parts.append(r["gnames"])
    if show.get("teacher", True) and r.get("tname"):
        t = r["tname"]
        if r.get("stname"):
            t = f"{r['stname']} (مستخلف عن {r['tname']})"
        parts.append(t)
    if show.get("room", True) and (r.get("rshort") or r.get("rname")):
        parts.append(r.get("rshort") or r["rname"])
    if show.get("time", True):
        parts.append(hm_range(r["start_min"], r["end_min"]))
    if r["status"] in ("postponed",):
        parts.append(f"[{STATUS_LABELS[r['status']]}]")
    if r.get("is_makeup"):
        parts.append("[تعويضية]")
    if show.get("notes") and r.get("note"):
        parts.append(r["note"])
    return "\n".join(parts)


def week_grid(db: Database, ws, tpl: dict, formation_id=None, section_id=None, teacher_id=None, group_id=None,
              rest_days: set[int] | None = None) -> Grid:
    days = week_days(ws)
    if rest_days is None and formation_id:
        rest_days = parse_rest_days(db.scalar("SELECT rest_days FROM formations WHERE id=?", (formation_id,)))
    rest_days = rest_days or set()
    rows = _sessions(db, days[0], days[-1], formation_id, section_id, teacher_id, group_id)
    used_days = [d for i, d in enumerate(days) if i not in rest_days or any(r["date"] == iso(d) for r in rows)]
    slot = db.get_int("slot_minutes") or 30
    start, end = db.get_int("day_start"), db.get_int("day_end")
    # الصفوف: حدود زمنية فعلية (بدايات ونهايات الحصص + بداية ونهاية اليوم)
    ls, le = db.get_int("lunch_start"), db.get_int("lunch_end")
    bounds = sorted({start, end, ls, le} | {r["start_min"] for r in rows} | {r["end_min"] for r in rows})
    bounds = [b for b in bounds if start <= b <= end] or [start, end]
    if len(bounds) < 2:
        bounds = [start, end]
    grid = Grid(col_labels=[f"{DAY_NAMES[(d.weekday() + 1) % 7]}\n{d.strftime('%d/%m')}" for d in used_days],
                row_labels=[hm_range(a, b) for a, b in zip(bounds, bounds[1:])])
    _ = slot
    with_section = section_id is None and teacher_id is None and group_id is None
    for ci, d in enumerate(used_days):
        day_rows = [r for r in rows if r["date"] == iso(d)]
        # دمج الحصص المتداخلة في كتلة واحدة
        blocks: list[list[dict]] = []
        for r in sorted(day_rows, key=lambda r: (r["start_min"], r["end_min"])):
            if blocks and r["start_min"] < max(x["end_min"] for x in blocks[-1]):
                blocks[-1].append(r)
            else:
                blocks.append([r])
        for b in blocks:
            s0 = min(x["start_min"] for x in b)
            s1 = max(x["end_min"] for x in b)
            r0 = bounds.index(s0) if s0 in bounds else 0
            r1 = bounds.index(s1) if s1 in bounds else len(bounds) - 1
            text = "\n—\n".join(session_text(x, tpl["show"], with_section or teacher_id is not None) for x in b)
            color = b[0]["color"] if (tpl.get("use_subject_colors") and len(b) == 1) else None
            grid.cells.append(Cell(r0, ci, max(1, r1 - r0), text, color))
    return grid


# ------------------------------------------------------------------ تقارير جاهزة
def report_week(db: Database, formation_id: int, ws, tpl: dict, section_id=None, teacher_id=None, group_id=None) -> Report:
    f = db.one("SELECT * FROM formations WHERE id=?", (formation_id,)) if formation_id else None
    if teacher_id:
        t = db.one("SELECT * FROM teachers WHERE id=?", (teacher_id,))
        title = f"جدول الأستاذ: {(t['rank'] + ': ') if t['rank'] else ''}{t['full_name']}"
    elif section_id:
        s = db.one("SELECT * FROM sections WHERE id=?", (section_id,))
        title = f"الجدول الأسبوعي — {s['name']}"
    else:
        title = "جدول جميع الأقسام"
    rep = _base(db, title, tpl)
    if f and tpl["show"].get("formation"):
        rep.info_lines.append(f"التكوين: {f['name']}")
    if tpl["show"].get("week"):
        days = week_days(ws)
        rep.info_lines.append(f"الأسبوع: من {days[0].strftime('%d/%m/%Y')} إلى {days[-1].strftime('%d/%m/%Y')}")
    rep.blocks.append(week_grid(db, ws, tpl, formation_id, section_id, teacher_id, group_id))
    return rep


def report_table(db: Database, title: str, headers: list[str], rows: list[list], tpl: dict,
                 info: list[str] | None = None) -> Report:
    rep = _base(db, title, tpl)
    rep.info_lines += info or []
    rep.blocks.append(Table(headers, rows))
    return rep


def report_progress(db: Database, formation_id, tpl: dict, today=None) -> Report:
    """إنجاز كل قسم في كل مادة مقارنة بالمقرر (المرحلة الحالية حسب المخطط الزمني)."""
    from ..services.progress import section_progress
    fids = formation_id if isinstance(formation_id, (list, tuple)) else [formation_id]
    rows = section_progress(db, list(fids), today)
    names = "، ".join(r[0] for r in db.q(f"SELECT name FROM formations WHERE id IN ({','.join('?' * len(fids))})", fids))

    def f(v, suf=""):
        return "—" if v is None else f"{v:g}{suf}"
    return report_table(db, "تقرير إنجاز المواد",
                        ["القسم", "المادة", "المرحلة", "المقرر", "المنجز", "الباقي", "نسبة الإنجاز", "المتوقع",
                         "نسبة التنفيذ", "التأخر", "المطلوب/أسبوع"],
                        [[r["section"], r["subject"], r["phase_label"], f(r["hours"]), f(r["done"]), f(r["remaining"]),
                          f(r["pct_done"], "%"), f(r["expected"]), f(r["pct_exec"], "%"), f(r["delta"]),
                          f(r["per_week"])] for r in rows], tpl,
                        [f"التكوين: {names}", f"بتاريخ: {to_date(today or date.today()).strftime('%d/%m/%Y')}"])


def report_teacher_hours(db: Database, start, end, tpl: dict) -> Report:
    from ..services.hours import teacher_hours
    rows = []
    for t in db.q("""SELECT t.*, c.name cat FROM teachers t LEFT JOIN teacher_categories c ON c.id=t.category_id
                     WHERE t.active=1 ORDER BY t.full_name"""):
        h = teacher_hours(db, t["id"], start, end)
        if h["planned"] or h["done"] or h["replaced_by_others"]:
            rows.append([t["full_name"], t["rank"] or "", t["cat"] or "", h["planned"], h["done"], h["remaining"],
                         h["as_substitute"], h["replaced_by_others"]])
    return report_table(db, "كشف ساعات الأساتذة",
                        ["الأستاذ", "الرتبة", "التصنيف", "المبرمجة", "المنجزة", "المتبقية", "منها كمستخلف",
                         "استُخلف فيها"], rows, tpl,
                        [f"الفترة: من {to_date(start).strftime('%d/%m/%Y')} إلى {to_date(end).strftime('%d/%m/%Y')}"])


def report_absences(db: Database, start, end, tpl: dict) -> Report:
    rows = []
    for a in db.q("""SELECT a.*, t.full_name FROM absences a JOIN teachers t ON t.id=a.teacher_id
                     WHERE a.end_date>=? AND a.start_date<=? ORDER BY a.start_date""", (iso(to_date(start)), iso(to_date(end)))):
        subs = db.q("""SELECT s.date, s.start_min, sub.name sname, st.full_name stname, s.status FROM sessions s
                       JOIN subjects sub ON sub.id=s.subject_id LEFT JOIN teachers st ON st.id=s.substitute_id
                       WHERE s.teacher_id=? AND s.date BETWEEN ? AND ?""", (a["teacher_id"], a["start_date"], a["end_date"]))
        covered = sum(1 for s in subs if s["stname"])
        rows.append([a["full_name"], a["reason"], a["start_date"], a["end_date"], len(subs), covered, a["notes"] or ""])
    return report_table(db, "تقرير الغيابات والاستخلاف",
                        ["الأستاذ", "السبب", "من", "إلى", "الحصص المتأثرة", "المستخلفة", "ملاحظات"], rows, tpl)


def report_sessions_status(db: Database, formation_id, tpl: dict) -> Report:
    rows = []
    fids = list(formation_id) if isinstance(formation_id, (list, tuple)) else [formation_id]
    for s in db.q(f"""SELECT s.*, sub.name sname, t.full_name tname FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                     LEFT JOIN teachers t ON t.id=s.teacher_id JOIN timetables tt ON tt.id=s.timetable_id
                     WHERE tt.formation_id IN ({','.join('?' * len(fids))})
                     AND (s.status IN ('postponed','cancelled') OR s.is_makeup=1)
                     ORDER BY s.date""", fids):
        rows.append([s["date"], hm_range(s["start_min"], s["end_min"]), s["sname"], s["tname"] or "",
                     "تعويضية" if s["is_makeup"] else STATUS_LABELS[s["status"]], s["note"] or ""])
    return report_table(db, "الحصص المؤجلة والملغاة والتعويضية", ["التاريخ", "التوقيت", "المادة", "الأستاذ", "الحالة",
                                                                  "ملاحظات"], rows, tpl)


def report_events(db: Database, tpl: dict, kinds: set[str] | None = None, start=None, end=None) -> Report:
    from ..services.calendar import EVENT_KINDS
    rows = []
    for e in db.q("""SELECT e.*, f.name fname FROM calendar_events e LEFT JOIN formations f ON f.id=e.formation_id
                     WHERE (? IS NULL OR e.end_date>=?) AND (? IS NULL OR e.start_date<=?) ORDER BY e.start_date""",
                  (start, start, end, end)):
        if kinds and e["kind"] not in kinds:
            continue
        rows.append([e["title"], EVENT_KINDS.get(e["kind"], e["kind"]), e["start_date"], e["end_date"],
                     e["fname"] or "الكل", e["description"] or ""])
    title = "رزنامة الامتحانات" if kinds and kinds <= {"exam", "final_exam", "evaluation"} else "الرزنامة والمواعيد"
    return report_table(db, title, ["العنوان", "النوع", "من", "إلى", "التكوين", "الوصف"], rows, tpl)


def report_period_plan(db: Database, formation_id: int, tpl: dict) -> Report:
    """مخطط الفترة: ساعات كل مادة لكل قسم في كل أسبوع."""
    from ..utils import weeks_between
    f = db.one("SELECT * FROM formations WHERE id=?", (formation_id,))
    weeks = weeks_between(f["start_date"], f["end_date"])
    rows = []
    reqs = db.q("""SELECT r.*, s.short ss, s.name sn, g.name gn, sec.short secs FROM requirements r
                   JOIN subjects s ON s.id=r.subject_id JOIN groups_ g ON g.id=r.group_id
                   JOIN sections sec ON sec.id=g.section_id WHERE r.formation_id=? ORDER BY sec.short, s.name""",
                (formation_id,))
    for r in reqs:
        line = [f"{r['secs']}/{r['gn']}", r["sn"]]
        tot = 0.0
        for w in weeks:
            m = db.scalar("""SELECT SUM(s.end_min-s.start_min) FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                             WHERE sg.group_id=? AND s.subject_id=? AND s.date>=? AND s.date<=date(?, '+6 days')
                             AND s.status IN ('planned','done')""", (r["group_id"], r["subject_id"], iso(w), iso(w)), 0) or 0
            line.append(round(m / 60, 1) or "")
            tot += m / 60
        line += [round(tot, 1), r["total_hours"] or 0]
        rows.append(line)
    rep = report_table(db, f"مخطط فترة التكوين — {f['name']}",
                       ["القسم/الفوج", "المادة"] + [w.strftime("%d/%m") for w in weeks] + ["المجموع", "المقرر"], rows, tpl,
                       [f"من {f['start_date']} إلى {f['end_date']} ({len(weeks)} أسبوعاً)"])
    return rep
