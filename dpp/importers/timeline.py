"""استيراد المخطط الزمني (Excel) — الأسابيع ومراحلها لكل طور، حسب ألوان الخلايا.

الملف المرجعي: ورقة «مخطط زمني 2026-2027»، الصفوف 16–24، الأسابيع في الأعمدة من M،
الأسبوع الأول يبدأ الأحد 13/09/2026. المخطط هو المرجع إذا اختلف مع الرزنامة.
"""
from __future__ import annotations

from datetime import date, timedelta

from ..db.database import Database

KINDS = {
    "reception": ("استقبال", "#F616DB"),
    "basic": ("تكوين قاعدي مشترك", "#B4C7E7"),
    "specialized": ("تكوين تخصصي", "#A3FFCD"),
    "leave": ("إجازة", "#00B0F0"),
    "partial_exam": ("امتحان جزئي", "#92D050"),
    "final_exam": ("امتحان نهائي", "#FF0000"),
    "other": ("أخرى", "#D9D9D9"),
}
RGB_KIND = {"F616DB": "reception", "A3FFCD": "specialized", "0066FF": "leave", "00B0F0": "leave",
            "92D050": "partial_exam", "FF0000": "final_exam"}

# صف الملف -> (التسمية، رموز الأطوار، تقييد الاختصاص)
ROWS = {
    16: ("BMP2", ["BMP2"], None), 17: ("BMP2 كتابة الضبط", ["BMP2"], "كتابة الضبط"),
    18: ("BMP1", ["BMP1"], None), 19: ("ESOC2", ["ESOC2"], None),
    20: ("ESOC2 كتابة الضبط", ["ESOC2"], "كتابة الضبط"),
    21: ("ESOC1 المدنيون", ["ESOC1"], None), 22: ("ESOC1 من الصفوف", ["ESOC1"], "من الصفوف"),
    23: ("ضباط الاحتياط", ["OF-R"], None), 24: ("ضباط الصف الاحتياط", ["ESO-R", "I-ESO-R", "I-HDT-R"], None),
}


def _kind(cell) -> str | None:
    f = cell.fill
    if f is None or not f.fill_type:
        return None
    c = f.fgColor
    if c is None:
        return None
    if c.type == "rgb" and c.rgb:
        return RGB_KIND.get(str(c.rgb)[-6:].upper(), "other")
    if c.type == "theme":
        return "basic" if c.theme == 9 else "other"
    return "other"


def import_timeline(db: Database, path: str, sheet: str | None = None, week1: date = date(2026, 9, 13),
                    first_col: int = 13, max_weeks: int = 55) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True)
    if not sheet:
        cands = [n for n in wb.sheetnames if "مخطط زمني" in n]
        sheet = next((n for n in cands if str(week1.year) in n), cands[-1] if cands else wb.sheetnames[0])
    ws = wb[sheet]
    rows = {r_i: list(row) for r_i, row in enumerate(ws.iter_rows(min_row=16, max_row=24), start=16)}
    out = {"rows": 0, "weeks": 0}
    with db.tx():
        db.execute("DELETE FROM timeline")
        for r_i, (label, codes, spec) in ROWS.items():
            cells = rows.get(r_i, [])
            got = 0
            for k in range(max_weeks):
                ci = first_col - 1 + k
                if ci >= len(cells):
                    break
                kind = _kind(cells[ci])
                if not kind:
                    continue
                wsd = (week1 + timedelta(days=7 * k)).isoformat()
                for code in codes:
                    db.execute("INSERT INTO timeline(row_label, level_code, specialty_like, week_no, week_start, kind)"
                               " VALUES (?,?,?,?,?,?)", (label, code, spec, k + 1, wsd, kind))
                got += 1
            if got:
                out["rows"] += 1
                out["weeks"] += got
    wb.close()
    return out


def phase_of(db: Database, level_code: str, week_start: str, specialty: str | None = None) -> str | None:
    rows = db.q("SELECT kind, specialty_like FROM timeline WHERE level_code=? AND week_start=?", (level_code, week_start))
    if specialty:
        for r in rows:
            if r["specialty_like"] and r["specialty_like"] in specialty:
                return r["kind"]
    for r in rows:
        if not r["specialty_like"]:
            return r["kind"]
    return rows[0]["kind"] if rows else None
