"""تقارير «المقرر والتقدم»: مقارنة أقسام الطور (مواد × أقسام)، تقرير كل قسم، التقرير الشامل، وملف Excel
بالألوان والمعادلات. البيانات من progress.simple_progress (المقرر والمنجز فقط)."""
from __future__ import annotations

from collections import OrderedDict
from datetime import date

from ..db.database import Database
from ..exporters.report_sheet import ReportDoc
from ..utils import to_date
from . import progress as P

FAMILY_LABELS = {"military": "عسكرية", "specialty": "اختصاص", "general": "عامة", "nonteach": "غير دراسية"}


def pct_hex(pct: float | None) -> str:
    """لون فاتح حسب النسبة (أحمر ← عسلي ← أخضر) صالح للطباعة."""
    if pct is None:
        return "#F1F3F5"
    x = max(0.0, min(1.0, pct / 100))
    stops = [(0.0, (0xF6, 0xC9, 0xC2)), (0.5, (0xF6, 0xE3, 0xB4)), (1.0, (0xBF, 0xE3, 0xC0))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if x <= b:
            k = (x - a) / (b - a)
            return "#" + "".join(f"{int(ca[i] + (cb[i] - ca[i]) * k):02X}" for i in range(3))
    return "#BFE3C0"


def fmt(v, suf="") -> str:
    return "—" if v is None else f"{v:g}{suf}"


# ------------------------------------------------------------------ مقارنة الأقسام
def matrix(rows: list[dict]) -> dict:
    """مواد × أقسام: {"sections": [(id, short, name)], "subjects": [(id, name, family)],
    "cell": {(sub, sec): row}, "sec_sum": {sec: summary}, "sub_avg": {sub: avg pct}}."""
    secs = OrderedDict()
    subs = OrderedDict()
    cell = {}
    for r in rows:
        secs.setdefault(r["section_id"], (r["section_id"], r["section"], r["section_name"]))
        subs.setdefault(r["subject_id"], (r["subject_id"], r["subject"], r["family"]))
        cell[(r["subject_id"], r["section_id"])] = r
    order = {"specialty": 0, "military": 1, "general": 2}
    sub_list = sorted(subs.values(), key=lambda s: (order.get(s[2], 3), s[1]))
    sec_sum = {s: P.summarize_simple([r for r in rows if r["section_id"] == s]) for s in secs}
    sub_avg = {}
    for sid, _n, _f in sub_list:
        vals = [cell[(sid, s)]["pct"] for s in secs if (sid, s) in cell and cell[(sid, s)]["pct"] is not None]
        sub_avg[sid] = round(sum(vals) / len(vals), 1) if vals else None
    return {"sections": list(secs.values()), "subjects": sub_list, "cell": cell, "sec_sum": sec_sum,
            "sub_avg": sub_avg}


def add_matrix_table(doc: ReportDoc, rows: list[dict], caption: str = ""):
    m = matrix(rows)
    headers = ["المادة", "النوع"] + [s[1] for s in m["sections"]] + ["المتوسط"]
    out, fills = [], {}
    for i, (sid, name, fam) in enumerate(m["subjects"]):
        line = [name, FAMILY_LABELS.get(fam, "")]
        for j, s in enumerate(m["sections"]):
            r = m["cell"].get((sid, s[0]))
            if r is None or r["pct"] is None:
                line.append("—" if r is None else "بلا مقرر")
            else:
                line.append(f"{r['pct']:g}%")
                fills[f"{i}:{j + 2}"] = pct_hex(r["pct"])
        avg = m["sub_avg"][sid]
        line.append(fmt(avg, "%"))
        if avg is not None:
            fills[f"{i}:{len(headers) - 1}"] = pct_hex(avg)
        out.append(line)
    tot = ["المجموع (كل المواد)", ""]
    for j, s in enumerate(m["sections"]):
        sm = m["sec_sum"][s[0]]
        tot.append(fmt(sm["pct"], "%"))
        if sm["pct"] is not None:
            fills[f"{len(out)}:{j + 2}"] = pct_hex(sm["pct"])
    allp = P.summarize_simple(rows)["pct"]
    tot.append(fmt(allp, "%"))
    out.append(tot)
    widths = [26, 8] + [9] * len(m["sections"]) + [9]
    doc.table(headers, out, fills=fills, widths=widths, bold_rows={len(out) - 1}, caption=caption,
              align=["right"] + ["center"] * (len(headers) - 1))
    return m


# ------------------------------------------------------------------ جداول
def groups_table(doc: ReportDoc, groups: list[dict], first_col: str, caption: str = ""):
    rows, fills = [], {}
    for i, g in enumerate(groups):
        rows.append([g["label"], fmt(g["hours"]), fmt(g["done"]), fmt(g["pct"], "%"), fmt(g["remaining"])])
        fills[f"{i}:3"] = pct_hex(g["pct"])
    doc.table([first_col, "المقرر (سا)", "المنجز (سا)", "نسبة الإنجاز", "الباقي (سا)"], rows, fills=fills,
              widths=[24, 9, 9, 9, 9], caption=caption, align=["right", "center", "center", "center", "center"])


def section_table(doc: ReportDoc, rows: list[dict], caption: str = ""):
    out, fills = [], {}
    for i, r in enumerate(rows):
        note = "بلا مقرر" if not r["hours"] else "تجاوز المقرر" if r["over"] else "مكتملة" if r["remaining"] == 0 else ""
        out.append([r["subject"], FAMILY_LABELS.get(r["family"], ""), fmt(r["hours"]), fmt(r["done"]),
                    fmt(r["pct"], "%"), fmt(r["remaining"]), str(r["sessions"]), note])
        if r["pct"] is not None:
            fills[f"{i}:4"] = pct_hex(r["pct"])
    s = P.summarize_simple(rows)
    out.append(["المجموع", "", fmt(round(s["hours"], 2)), fmt(round(s["done"], 2)), fmt(s["pct"], "%"),
                fmt(s["remaining"]), str(sum(r["sessions"] for r in rows)), ""])
    if s["pct"] is not None:
        fills[f"{len(out) - 1}:4"] = pct_hex(s["pct"])
    doc.table(["المادة", "النوع", "المقرر", "المنجز", "النسبة", "الباقي", "حصص", "ملاحظة"], out, fills=fills,
              widths=[28, 8, 7, 7, 7, 7, 6, 10], bold_rows={len(out) - 1}, caption=caption,
              align=["right"] + ["center"] * 7)


def _info(db: Database, today, scope_label: str) -> list[str]:
    return [scope_label, f"حتى تاريخ: {to_date(today).strftime('%Y/%m/%d')}"]


def summary_line(rows) -> str:
    s = P.summarize_simple(rows)
    parts = [f"{len({r['section_id'] for r in rows})} قسماً · {len(rows)} مادة"]
    if s["pct"] is not None:
        parts.append(f"نسبة الإنجاز {s['pct']:g}% ({s['done']:g} من {s['hours']:g} سا) · الباقي {s['remaining']:g} سا")
    if s["missing"]:
        parts.append(f"{s['missing']} مادة بلا مقرر")
    return " · ".join(parts)


# ------------------------------------------------------------------ المستندات
def doc_current(db, rows, groups, scope_label, today, chart_png: tuple | None = None, detail_rows=None,
                compare=False) -> ReportDoc:
    doc = ReportDoc("progress_simple", "المقرر والمنجز", _info(db, today, scope_label), name="المقرر_والمنجز")
    doc.para(summary_line(rows), bold=True)
    if chart_png:
        doc.image(*chart_png)
    if groups:
        groups_table(doc, groups, "البند")
    if compare:
        add_matrix_table(doc, rows, "مقارنة الأقسام (نسبة الإنجاز لكل مادة)")
    elif detail_rows is not None:
        out, fills = [], {}
        for i, r in enumerate(detail_rows):
            out.append([r["section"], r["subject"], FAMILY_LABELS.get(r["family"], ""), fmt(r["hours"]),
                        fmt(r["done"]), fmt(r["pct"], "%"), fmt(r["remaining"])])
            if r["pct"] is not None:
                fills[f"{i}:5"] = pct_hex(r["pct"])
        doc.table(["القسم", "المادة", "النوع", "المقرر", "المنجز", "النسبة", "الباقي"], out, fills=fills,
                  widths=[14, 26, 8, 7, 7, 7, 7], caption="التفصيل", align=["right", "right"] + ["center"] * 5)
    return doc


def doc_sections(db, rows, scope_label, today) -> ReportDoc:
    doc = ReportDoc("progress_sections", "تقدم الأقسام", _info(db, today, scope_label), name="تقدم_الأقسام")
    by = OrderedDict()
    for r in rows:
        by.setdefault(r["section_id"], []).append(r)
    for k, (sid, rs) in enumerate(by.items()):
        if k:
            doc.page_break()
        doc.heading(f"{rs[0]['section']} — {rs[0]['section_name']}")
        doc.para(summary_line(rs))
        section_table(doc, rs)
    return doc


def doc_compare(db, rows, scope_label, today) -> ReportDoc:
    doc = ReportDoc("progress_compare", "مقارنة أقسام الطور", _info(db, today, scope_label), name="مقارنة_الأقسام")
    doc.para(summary_line(rows), bold=True)
    m = add_matrix_table(doc, rows)
    ranks = sorted(((m["sec_sum"][s[0]]["pct"] or 0, s[1]) for s in m["sections"]), reverse=True)
    if ranks:
        doc.para("ترتيب الأقسام: " + " ، ".join(f"{i + 1}) {n} {p:g}%" for i, (p, n) in enumerate(ranks)))
    return doc


def doc_full(db, rows, scope_label, today) -> ReportDoc:
    """التقرير الشامل: ملخص التكوين، ثم كل طور (مقارنة أقسامه وأضعف المواد)، ثم كل قسم، ثم التنبيهات."""
    doc = ReportDoc("progress_full", "التقرير الشامل لتقدم الدروس", _info(db, today, scope_label),
                    name="التقرير_الشامل")
    doc.heading("1. ملخص التكوين")
    doc.para(summary_line(rows), bold=True)
    levels = OrderedDict()
    for r in rows:
        levels.setdefault((r["level_id"], r["level"]), []).append(r)
    lv_groups = []
    for (lid, code), rs in levels.items():
        s = P.summarize_simple(rs)
        if s["hours"]:
            lv_groups.append({"label": code or "—", "hours": round(s["hours"], 1), "done": round(s["done"], 1),
                              "pct": s["pct"], "remaining": s["remaining"]})
    groups_table(doc, lv_groups, "الطور", "الأطوار")
    n = 2
    for (lid, code), rs in levels.items():
        doc.page_break()
        doc.heading(f"{n}. الطور {code}")
        n += 1
        doc.para(summary_line(rs))
        add_matrix_table(doc, rs, "مقارنة الأقسام")
        weak = sorted((r for r in rs if r["pct"] is not None), key=lambda r: r["pct"])[:10]
        if weak:
            out, fills = [], {}
            for i, r in enumerate(weak):
                out.append([r["section"], r["subject"], fmt(r["hours"]), fmt(r["done"]), fmt(r["pct"], "%"),
                            fmt(r["remaining"])])
                fills[f"{i}:4"] = pct_hex(r["pct"])
            doc.table(["القسم", "المادة", "المقرر", "المنجز", "النسبة", "الباقي"], out, fills=fills,
                      widths=[14, 26, 7, 7, 7, 7], caption="أضعف المواد إنجازاً", align=["right", "right"] + ["center"] * 4)
    doc.page_break()
    doc.heading(f"{n}. تفصيل الأقسام")
    by = OrderedDict()
    for r in rows:
        by.setdefault(r["section_id"], []).append(r)
    for sid, rs in by.items():
        section_table(doc, rs, f"{rs[0]['section']} — {summary_line(rs)}")
    try:
        from . import alerts as AL
        al = AL.open_alerts(db)
    except Exception:
        al = []
    if al:
        doc.page_break()
        doc.heading(f"{n + 1}. التنبيهات المفتوحة ({len(al)})")
        doc.table(["الخطورة", "التنبيه", "التفصيل"],
                  [[AL.SEVERITY_LABELS.get(a["severity"], a["severity"]), a["title"], (a.get("detail") or "")[:160]]
                   for a in al], widths=[7, 24, 34], align=["center", "right", "right"])
    return doc


# ------------------------------------------------------------------ Excel بالألوان والمعادلات
def to_xlsx(db: Database, rows: list[dict], path, title: str = "المقرر والمنجز", today=None):
    """ملف واحد بأوراق: ملخص، ورقة لكل طور (مواد × أقسام)، ورقة لكل قسم.
    النسبة والباقي معادلات Excel، والألوان تنسيق شرطي يتغير مع القيم."""
    import openpyxl
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter as CL

    wb = openpyxl.Workbook()
    thin = Side(style="thin", color="999999")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    right = Alignment(horizontal="right", vertical="center", wrap_text=True)
    head = PatternFill("solid", fgColor="DCE6F1")
    bold = Font(bold=True)
    scale = dict(start_type="num", start_value=0, start_color="F6C9C2", mid_type="num", mid_value=0.5,
                 mid_color="F6E3B4", end_type="num", end_value=1, end_color="BFE3C0")
    used_names = set()

    def sheet(name):
        base = "".join(ch for ch in name if ch not in '[]:*?/\\')[:28] or "ورقة"
        n, k = base, 2
        while n in used_names:
            n, k = f"{base[:25]}-{k}", k + 1
        used_names.add(n)
        ws = wb.create_sheet(n)
        ws.sheet_view.rightToLeft = True
        return ws

    def hdr(ws, r, labels):
        for j, h in enumerate(labels, 1):
            c = ws.cell(r, j, h)
            c.font, c.alignment, c.border, c.fill = bold, center, box, head

    wb.remove(wb.active)
    by_sec = OrderedDict()
    for r in rows:
        by_sec.setdefault(r["section_id"], []).append(r)
    by_lvl = OrderedDict()
    for r in rows:
        by_lvl.setdefault((r["level_id"], r["level"] or "—"), []).append(r)

    # ورقة كل قسم (تُنشأ أولاً لأن الملخص يشير إليها)
    sec_cells = {}
    sec_sheets = []
    for sid, rs in by_sec.items():
        ws = sheet(rs[0]["section"])
        sec_sheets.append(ws)
        ws.cell(1, 1, f"{rs[0]['section']} — {rs[0]['section_name']}").font = Font(bold=True, size=13)
        hdr(ws, 3, ["المادة", "النوع", "المقرر (سا)", "المنجز (سا)", "نسبة الإنجاز", "الباقي (سا)", "حصص منجزة"])
        r0 = 4
        for i, r in enumerate(rs):
            row = r0 + i
            ws.cell(row, 1, r["subject"]).alignment = right
            ws.cell(row, 2, FAMILY_LABELS.get(r["family"], ""))
            ws.cell(row, 3, r["hours"] if r["hours"] else None)
            ws.cell(row, 4, r["done"])
            ws.cell(row, 5, f'=IF(N(C{row})>0,D{row}/C{row},"")').number_format = "0.0%"
            ws.cell(row, 6, f'=IF(N(C{row})>0,MAX(0,C{row}-D{row}),"")')
            ws.cell(row, 7, r["sessions"])
            for j in range(1, 8):
                ws.cell(row, j).border = box
                if j > 1:
                    ws.cell(row, j).alignment = center
        last = r0 + len(rs) - 1
        tr = last + 1
        ws.cell(tr, 1, "المجموع").font = bold
        ws.cell(tr, 3, f"=SUMIF(C{r0}:C{last},\">0\")")
        ws.cell(tr, 4, f'=SUMIFS(D{r0}:D{last},C{r0}:C{last},">0")')
        ws.cell(tr, 5, f'=IF(C{tr}>0,MIN(1,D{tr}/C{tr}),"")').number_format = "0.0%"
        ws.cell(tr, 6, f"=SUM(F{r0}:F{last})")
        ws.cell(tr, 7, f"=SUM(G{r0}:G{last})")
        for j in range(1, 8):
            c = ws.cell(tr, j)
            c.font, c.border, c.fill = bold, box, head
            if j > 1:
                c.alignment = center
        ws.conditional_formatting.add(f"E{r0}:E{tr}", ColorScaleRule(**scale))
        ws.column_dimensions["A"].width = 46
        for col in "BCDEFG":
            ws.column_dimensions[col].width = 13
        ws.freeze_panes = "B4"
        sec_cells[sid] = (ws.title, tr)

    # أوراق الأطوار: مواد × أقسام (المقرر والمنجز والنسبة لكل قسم)
    lvl_sheets = []
    for (lid, code), rs in by_lvl.items():
        ws = sheet(f"الطور {code}")
        lvl_sheets.append(ws)
        m = matrix(rs)
        ws.cell(1, 1, f"الطور {code}: مقارنة الأقسام").font = Font(bold=True, size=13)
        ws.cell(3, 1, "المادة")
        ws.cell(3, 2, "النوع")
        for k, s in enumerate(m["sections"]):
            c0 = 3 + k * 3
            ws.merge_cells(start_row=2, start_column=c0, end_row=2, end_column=c0 + 2)
            ws.cell(2, c0, s[1])
            for d, lab in enumerate(("مقرر", "منجز", "%")):
                ws.cell(3, c0 + d, lab)
        avg_c = 3 + len(m["sections"]) * 3
        ws.cell(3, avg_c, "المتوسط")
        for j in range(1, avg_c + 1):
            for rr in (2, 3):
                c = ws.cell(rr, j)
                c.font, c.alignment, c.border, c.fill = bold, center, box, head
        r0 = 4
        for i, (sub, name, fam) in enumerate(m["subjects"]):
            row = r0 + i
            ws.cell(row, 1, name).alignment = right
            ws.cell(row, 2, FAMILY_LABELS.get(fam, ""))
            pcts = []
            for k, s in enumerate(m["sections"]):
                c0 = 3 + k * 3
                r = m["cell"].get((sub, s[0]))
                if r is not None:
                    ws.cell(row, c0, r["hours"] if r["hours"] else None)
                    ws.cell(row, c0 + 1, r["done"])
                h, d = CL(c0), CL(c0 + 1)
                ws.cell(row, c0 + 2, f'=IF(N({h}{row})>0,{d}{row}/{h}{row},"")').number_format = "0%"
                pcts.append(f"{CL(c0 + 2)}{row}")
            ws.cell(row, avg_c, f'=IFERROR(AVERAGE({",".join(pcts)}),"")').number_format = "0%"
            for j in range(1, avg_c + 1):
                ws.cell(row, j).border = box
                if j > 1:
                    ws.cell(row, j).alignment = center
        last = r0 + len(m["subjects"]) - 1
        tr = last + 1
        ws.cell(tr, 1, "المجموع").font = bold
        for k, s in enumerate(m["sections"]):
            c0 = 3 + k * 3
            h, d = CL(c0), CL(c0 + 1)
            ws.cell(tr, c0, f"=SUM({h}{r0}:{h}{last})")
            ws.cell(tr, c0 + 1, f'=SUMIFS({d}{r0}:{d}{last},{h}{r0}:{h}{last},">0")')
            ws.cell(tr, c0 + 2, f'=IF({h}{tr}>0,MIN(1,{d}{tr}/{h}{tr}),"")').number_format = "0%"
            ws.conditional_formatting.add(f"{CL(c0 + 2)}{r0}:{CL(c0 + 2)}{tr}", ColorScaleRule(**scale))
        ws.conditional_formatting.add(f"{CL(avg_c)}{r0}:{CL(avg_c)}{last}", ColorScaleRule(**scale))
        for j in range(1, avg_c + 1):
            c = ws.cell(tr, j)
            c.font, c.border, c.fill = bold, box, head
        ws.column_dimensions["A"].width = 40
        for j in range(2, avg_c + 1):
            ws.column_dimensions[CL(j)].width = 8
        ws.freeze_panes = "C4"

    # الملخص: سطر لكل قسم مرتبط بورقته
    ws = wb.create_sheet("ملخص", 0)
    ws.sheet_view.rightToLeft = True
    ws.cell(1, 1, title).font = Font(bold=True, size=14)
    ws.cell(2, 1, f"حتى تاريخ: {to_date(today or date.today()).strftime('%Y/%m/%d')}")
    hdr(ws, 4, ["الطور", "القسم", "المقرر (سا)", "المنجز (سا)", "نسبة الإنجاز", "الباقي (سا)"])
    row = 5
    for sid, rs in by_sec.items():
        name, tr = sec_cells[sid]
        q = f"'{name}'"
        ws.cell(row, 1, rs[0]["level"])
        c = ws.cell(row, 2, rs[0]["section"])
        c.hyperlink = f"#{q}!A1"
        c.font = Font(color="1F4E79", underline="single")
        ws.cell(row, 3, f"={q}!C{tr}")
        ws.cell(row, 4, f"={q}!D{tr}")
        ws.cell(row, 5, f'=IF(C{row}>0,MIN(1,D{row}/C{row}),"")').number_format = "0.0%"
        ws.cell(row, 6, f"={q}!F{tr}")
        for j in range(1, 7):
            ws.cell(row, j).border = box
            ws.cell(row, j).alignment = center
        row += 1
    last = row - 1
    ws.cell(row, 2, "المجموع").font = bold
    ws.cell(row, 3, f"=SUM(C5:C{last})")
    ws.cell(row, 4, f"=SUM(D5:D{last})")
    ws.cell(row, 5, f'=IF(C{row}>0,D{row}/C{row},"")').number_format = "0.0%"
    ws.cell(row, 6, f"=SUM(F5:F{last})")
    for j in range(1, 7):
        c = ws.cell(row, j)
        c.font, c.border, c.fill = bold, box, head
    ws.conditional_formatting.add(f"E5:E{row}", ColorScaleRule(**scale))
    ws.column_dimensions["A"].width = 12
    ws.column_dimensions["B"].width = 34
    for col in "CDEF":
        ws.column_dimensions[col].width = 14
    # ترتيب الأوراق: الملخص، الأطوار، الأقسام
    wb._sheets = [ws] + lvl_sheets + sec_sheets
    wb.active = 0
    wb.save(path)
    return path
