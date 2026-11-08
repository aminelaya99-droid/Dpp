"""الخفارة والخدمات: نظام منفصل عن الجدول.

* أنواع المناوبة (خفارة، خدمة، …): عدد الأقسام في اليوم، الأيام، والأقسام المعنية (أقسام أو أطوار أو سنوات).
* التوزيع الآلي بتناوب عادل: القسم الأقل مناوبات أولاً، ثم الأبعد عن آخر مناوبة له، مع تجنب:
  يومين متتاليين لنفس القسم، ونوعين في نفس اليوم لنفس القسم، وأيام «اليوم كاملاً» (اختبار…) والأحداث.
  التعيينات اليدوية لا تُمس.
* لا تدخل الجدول إلا عند الطلب: insert_week يضع بطاقات «يوم كامل» في أسبوع محدد.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

from ..db.database import Database
from ..utils import DAY_NAMES, iso, to_date, weekday_sun0

DEFAULT_TYPES = [("خفارة", 1, "#CDB89B"), ("خدمة", 1, "#B6C6D8")]


# ------------------------------------------------------------------ الأنواع
def ensure_defaults(db: Database) -> None:
    if db.scalar("SELECT COUNT(*) FROM duty_types", (), 0):
        return
    from . import fullday as FD
    subs = {db.scalar("SELECT name FROM subjects WHERE id=?", (i,)): i for i in FD.subjects(db)}
    with db.tx():
        for k, (name, n, color) in enumerate(DEFAULT_TYPES):
            db.insert("duty_types", name=name, per_day=n, color=color, subject_id=subs.get(name), sort=k)


def types(db: Database, active_only=False) -> list[dict]:
    out = []
    for r in db.q("SELECT * FROM duty_types ORDER BY sort, id"):
        if active_only and not r["active"]:
            continue
        d = dict(r)
        try:
            d["scope"] = json.loads(r["scope"] or "{}")
        except ValueError:
            d["scope"] = {}
        d["days"] = [int(x) for x in (r["days"] or "").split(",") if x.strip().isdigit()]
        out.append(d)
    return out


def save_type(db: Database, name: str, per_day: int, days: list[int], scope: dict, color: str = "#CDB89B",
              type_id: int | None = None, active: bool = True) -> int:
    from . import fullday as FD
    name = " ".join(name.split())
    if not name:
        raise ValueError("اكتب اسم النوع.")
    sub = db.scalar("SELECT id FROM subjects WHERE name=?", (name,))
    if not sub:
        sub = FD._subject(db, name, "nonteach", "nonteach", color)
    FD.add(db, sub)                                  # تظهر أيضاً بطاقة «يوم كامل» في شريط الجدول
    vals = dict(name=name, per_day=max(1, int(per_day)), days=",".join(str(d) for d in sorted(set(days))),
                scope=json.dumps(scope or {}, ensure_ascii=False), color=color, subject_id=sub, active=int(active))
    with db.tx():
        if type_id:
            db.update("duty_types", type_id, **vals)
            return type_id
        return db.insert("duty_types", **vals)


def delete_type(db: Database, type_id: int) -> None:
    with db.tx():
        db.execute("DELETE FROM duty_types WHERE id=?", (type_id,))


def scope_label(db: Database, scope: dict) -> str:
    parts = []
    if scope.get("years"):
        parts.append("السنوات: " + "، ".join(str(y) for y in scope["years"]))
    if scope.get("levels"):
        parts.append("الأطوار: " + "، ".join(r[0] for r in db.q(
            f"SELECT COALESCE(code,name) FROM levels WHERE id IN ({','.join('?' * len(scope['levels']))})",
            scope["levels"])))
    if scope.get("sections"):
        parts.append(f"{len(scope['sections'])} قسم")
    return " · ".join(parts) or "كل الأقسام"


def eligible(db: Database, t: dict) -> list[dict]:
    """الأقسام المعنية بالنوع (قسم محدد، أو كل أقسام طور، أو كل أقسام سنة)."""
    sc = t.get("scope") or {}
    rows = [dict(r) for r in db.q("""SELECT s.id, s.short, s.name, s.level_id, l.year_no, l.sort lsort, s.sort
                                     FROM sections s LEFT JOIN levels l ON l.id=s.level_id
                                     JOIN formations f ON f.id=s.formation_id WHERE f.archived=0
                                     ORDER BY COALESCE(l.sort,99), s.sort, s.id""")]
    if not (sc.get("sections") or sc.get("levels") or sc.get("years")):
        return rows
    secs, lv, yr = set(sc.get("sections") or []), set(sc.get("levels") or []), set(sc.get("years") or [])
    return [r for r in rows if r["id"] in secs or r["level_id"] in lv or (r["year_no"] in yr if r["year_no"] else False)]


# ------------------------------------------------------------------ التعيينات
def assignments(db: Database, start, end) -> list[dict]:
    return [dict(r) for r in db.q("""SELECT a.*, s.short, t.name tname FROM duty_assignments a
                                     JOIN sections s ON s.id=a.section_id JOIN duty_types t ON t.id=a.type_id
                                     WHERE a.date BETWEEN ? AND ? ORDER BY a.date, t.sort, a.slot""",
                                  (iso(to_date(start)), iso(to_date(end))))]


def set_manual(db: Database, type_id: int, d, section_ids: list[int]) -> None:
    """تعيين يدوي ليوم ونوع: الأقسام المختارة بالترتيب (تبقى عند التوزيع الآلي)."""
    d = iso(to_date(d))
    with db.tx():
        db.execute("DELETE FROM duty_assignments WHERE type_id=? AND date=?", (type_id, d))
        for k, sid in enumerate(section_ids):
            db.insert("duty_assignments", type_id=type_id, date=d, slot=k, section_id=sid, manual=1)


def clear_auto(db: Database, start, end, type_ids: list[int] | None = None) -> int:
    sql = "DELETE FROM duty_assignments WHERE manual=0 AND date BETWEEN ? AND ?"
    p: list = [iso(to_date(start)), iso(to_date(end))]
    if type_ids:
        sql += f" AND type_id IN ({','.join('?' * len(type_ids))})"
        p += type_ids
    with db.tx():
        n = db.scalar(sql.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1), p, 0)
        db.execute(sql, p)
        return n


def _busy_days(db: Database, start, end) -> dict[int, set]:
    """أيام لا يُناوب فيها القسم: «يوم كامل» دراسي (اختبار) أو حدث يحجب اليوم."""
    out: dict[int, set] = defaultdict(set)
    from . import fullday as FD
    exam = FD.exam_subject(db)
    for r in db.q("""SELECT DISTINCT g.section_id, s.date FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                     JOIN groups_ g ON g.id=sg.group_id WHERE s.subject_id=? AND s.date BETWEEN ? AND ?
                     AND s.status IN ('planned','done')""", (exam, iso(to_date(start)), iso(to_date(end)))):
        out[r[0]].add(to_date(r[1]))
    try:
        from .calendar import section_day_events
        ids = [r[0] for r in db.q("SELECT id FROM sections")]
        for (sid, d), evs in section_day_events(db, start, end, ids).items():
            if any(k not in ("duty", "service") for _t, k in evs):
                out[sid].add(d)
    except Exception:
        pass
    return out


def generate(db: Database, start, end, type_ids: list[int] | None = None, gap_days: int = 1) -> dict:
    """توزيع آلي عادل للفترة (يحتفظ باليدوي). يعيد {"placed": n, "missing": [(التاريخ، النوع، السبب)]}."""
    start, end = to_date(start), to_date(end)
    ts = [t for t in types(db, active_only=True) if not type_ids or t["id"] in type_ids]
    clear_auto(db, start, end, [t["id"] for t in ts])
    busy = _busy_days(db, start, end)
    # العدّ يشمل ما قبل الفترة (لعدل مستمر عبر الأشهر)
    count = defaultdict(int)
    last = {}
    for r in db.q("SELECT type_id, section_id, MAX(date) d, COUNT(*) n FROM duty_assignments GROUP BY type_id, section_id"):
        count[(r["type_id"], r["section_id"])] = r["n"]
        last[(r["type_id"], r["section_id"])] = to_date(r["d"])
    any_last = {}
    for r in db.q("SELECT section_id, date FROM duty_assignments"):
        any_last.setdefault(r[0], set()).add(to_date(r[1]))
    placed, missing = 0, []
    d = start
    with db.tx():
        while d <= end:
            wd = weekday_sun0(d)
            taken_today = {r[0] for r in db.q("SELECT section_id FROM duty_assignments WHERE date=?", (iso(d),))}
            for t in ts:
                if wd not in t["days"]:
                    continue
                have = db.q("SELECT slot, section_id FROM duty_assignments WHERE type_id=? AND date=?", (t["id"], iso(d)))
                used_slots = {r[0] for r in have}
                for slot in range(t["per_day"]):
                    if slot in used_slots:
                        continue
                    cands = [s for s in eligible(db, t) if s["id"] not in taken_today and d not in busy.get(s["id"], ())]
                    if not cands:
                        missing.append((d, t["name"], "لا يوجد قسم متاح (كل الأقسام مشغولة أو في اختبار)"))
                        continue

                    def score(s):
                        recent = any_last.get(s["id"], set())
                        near = any(abs((d - x).days) <= gap_days for x in recent)
                        lt = last.get((t["id"], s["id"]))
                        return (near, count[(t["id"], s["id"])], lt or date.min, s["lsort"] or 99, s["sort"] or 0, s["id"])
                    best = min(cands, key=score)
                    db.insert("duty_assignments", type_id=t["id"], date=iso(d), slot=slot, section_id=best["id"],
                              manual=0)
                    count[(t["id"], best["id"])] += 1
                    last[(t["id"], best["id"])] = d
                    any_last.setdefault(best["id"], set()).add(d)
                    taken_today.add(best["id"])
                    placed += 1
            d += timedelta(days=1)
    return {"placed": placed, "missing": missing}


def stats(db: Database, start=None, end=None) -> dict:
    """{"types": [...], "rows": [(section_short, {type_id: n}, total)]} للتأكد من العدل."""
    sql = "SELECT type_id, section_id, COUNT(*) n FROM duty_assignments"
    p: list = []
    if start and end:
        sql += " WHERE date BETWEEN ? AND ?"
        p = [iso(to_date(start)), iso(to_date(end))]
    sql += " GROUP BY type_id, section_id"
    cnt = defaultdict(dict)
    for r in db.q(sql, p):
        cnt[r["section_id"]][r["type_id"]] = r["n"]
    ts = types(db)
    secs = {}
    for t in ts:
        for s in eligible(db, t):
            secs[s["id"]] = s["short"]
    rows = [(secs[s], cnt.get(s, {}), sum(cnt.get(s, {}).values())) for s in secs]
    return {"types": ts, "rows": rows}


# ------------------------------------------------------------------ الإدراج في الجدول (عند الطلب)
def week_items(db: Database, ws) -> list[dict]:
    ws = to_date(ws)
    out = []
    for a in assignments(db, ws, ws + timedelta(days=6)):
        t = db.one("SELECT subject_id, name FROM duty_types WHERE id=?", (a["type_id"],))
        out.append(dict(a, subject_id=t["subject_id"], day=to_date(a["date"])))
    return out


def insert_week(db: Database, ws, confirm_busy=None) -> dict:
    """يضع مناوبات الأسبوع في الجدول كبطاقات «يوم كامل». confirm_busy(قسم، يوم، حصص) يقرر إرجاع الحصص
    الموجودة إلى الشريط (True) أو تخطي هذا اليوم (False). يعيد {"inserted": n, "skipped": [...]}."""
    from .grid import GridError, TrayItem, WeekGrid
    g = WeekGrid(db, ws)
    res = {"inserted": 0, "skipped": []}
    g.begin_group()
    for a in week_items(db, ws):
        if a.get("session_id") and db.scalar("SELECT 1 FROM sessions WHERE id=? AND status<>'tray'", (a["session_id"],)):
            continue                                       # مُدرجة مسبقاً
        sec, d = a["section_id"], a["day"]
        if sec not in g.sec_by_id or not a["subject_id"]:
            res["skipped"].append((a["short"], d, "القسم أو المادة غير موجودة"))
            continue
        busy = g.day_cards(sec, d)
        if any(c.subject == a["subject_id"] for c in busy):
            continue
        if busy:
            if not (confirm_busy and confirm_busy(a["short"], d, busy)):
                res["skipped"].append((a["short"], d, f"{len(busy)} حصة في اليوم"))
                continue
            for c in busy:
                g.to_tray(c)
        r = db.one("SELECT id, name, short, color FROM subjects WHERE id=?", (a["subject_id"],))
        it = TrayItem(f"duty{a['id']}", None, r["id"], r["name"], r["short"] or r["name"], r["color"] or "#CCC",
                      "nonteach", None, "", 480, set(), shareable=True, kind="nonteach", free=True, full_day=True)
        s, e = g.full_day_range(sec)
        try:
            sid = g.place_free(it, sec, None, d, s, e)
        except GridError as ex:
            res["skipped"].append((a["short"], d, str(ex)))
            continue
        with db.tx():
            db.execute("UPDATE duty_assignments SET session_id=? WHERE id=?", (sid, a["id"]))
        res["inserted"] += 1
    g.end_group("إدراج المناوبات")
    return res


# ------------------------------------------------------------------ الطباعة وExcel
def roster(db: Database, start, end) -> tuple[list[str], list[list[str]], list[dict]]:
    ts = types(db, active_only=True)
    by = defaultdict(list)
    for a in assignments(db, start, end):
        by[(a["date"], a["type_id"])].append(a["short"] + (" ✎" if a["manual"] else ""))
    headers = ["اليوم", "التاريخ"] + [t["name"] for t in ts]
    rows = []
    d = to_date(start)
    while d <= to_date(end):
        rows.append([DAY_NAMES[weekday_sun0(d)], d.strftime("%d/%m/%Y")] +
                    ["، ".join(by.get((iso(d), t["id"]), [])) for t in ts])
        d += timedelta(days=1)
    return headers, rows, ts


def report_doc(db: Database, start, end):
    from ..exporters.report_sheet import ReportDoc
    headers, rows, ts = roster(db, start, end)
    doc = ReportDoc("duty", "جدول المناوبات (الخفارة والخدمات)",
                    [f"من {to_date(start).strftime('%Y/%m/%d')} إلى {to_date(end).strftime('%Y/%m/%d')}"],
                    name="جدول_المناوبات")
    fills = {}
    for i, r in enumerate(rows):
        if r[0] in (DAY_NAMES[5], DAY_NAMES[6]):
            for j in range(len(headers)):
                fills[f"{i}:{j}"] = "#F3F4F6"
    doc.table(headers, rows, fills=fills, widths=[8, 10] + [20] * len(ts))
    st = stats(db, start, end)
    if st["rows"]:
        doc.table(["القسم"] + [t["name"] for t in st["types"]] + ["المجموع"],
                  [[name] + [str(c.get(t["id"], 0)) for t in st["types"]] + [str(tot)] for name, c, tot in st["rows"]],
                  caption="عدد المناوبات لكل قسم في الفترة")
    return doc


def to_xlsx(db: Database, start, end, path):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    headers, rows, ts = roster(db, start, end)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "المناوبات"
    ws.sheet_view.rightToLeft = True
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    c = ws.cell(1, 1, "جدول المناوبات")
    c.font = Font(bold=True, size=14)
    for j, h in enumerate(headers, 1):
        c = ws.cell(3, j, h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DCE6F1")
        c.border = box
    for i, r in enumerate(rows):
        for j, v in enumerate(r, 1):
            c = ws.cell(4 + i, j, v)
            c.border = box
            c.alignment = Alignment(horizontal="center")
    for j in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(j)].width = 12 if j <= 2 else 28
    st = stats(db, start, end)
    w2 = wb.create_sheet("الإحصائيات")
    w2.sheet_view.rightToLeft = True
    hs = ["القسم"] + [t["name"] for t in st["types"]] + ["المجموع"]
    for j, h in enumerate(hs, 1):
        c = w2.cell(1, j, h)
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DCE6F1")
    for i, (name, cnt, tot) in enumerate(st["rows"]):
        w2.cell(2 + i, 1, name)
        for j, t in enumerate(st["types"], 2):
            w2.cell(2 + i, j, cnt.get(t["id"], 0))
        w2.cell(2 + i, len(hs), f"=SUM(B{2 + i}:{openpyxl.utils.get_column_letter(len(hs) - 1)}{2 + i})")
    w2.column_dimensions["A"].width = 30
    wb.save(path)
    return path
