"""التقارير كأوراق في محرر الطباعة الواحد (نفس المعاينة، والتصميم، والقوالب، والطباعة وPDF).

التقرير (ReportDoc) = عنوان + أسطر معلومات + كتل (جداول، فقرات، عناوين، فواصل صفحات).
يُقسَّم على صفحات حسب التصميم الفعلي (الورق، الاتجاه، الهوامش، أحجام الخطوط، عروض الأعمدة)،
وكل صفحة ورقة (Sheet) تشترك مع باقي صفحات التقرير في نفس التصميم، فأي تعديل في المحرر يُعيد التوزيع.
لا يعتمد على Qt.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

from ..db.database import Database
from . import layout as L
from . import official as O


@dataclass
class ReportDoc:
    key: str                                  # يحدد قالب التقرير: report_<key>
    title: str
    info: list[str] = field(default_factory=list)
    blocks: list[dict] = field(default_factory=list)
    name: str = ""

    def table(self, headers, rows, fills=None, widths=None, align=None, bold_rows=None, spans=None, caption=""):
        self.blocks.append({"type": "table", "headers": [str(h) for h in headers],
                            "rows": [["" if c is None else str(c) for c in r] for r in rows],
                            "fills": dict(fills or {}), "widths": widths, "align": align,
                            "bold_rows": set(bold_rows or ()), "spans": dict(spans or {}), "caption": caption})
        return self.blocks[-1]

    def para(self, text, bold=False, size=None):
        self.blocks.append({"type": "para", "text": str(text), "bold": bold, "size": size})

    def heading(self, text):
        self.blocks.append({"type": "para", "text": str(text), "bold": True, "size": 11.5, "heading": True})

    def image(self, png: bytes, w: float, h: float):
        self.blocks.append({"type": "image", "png": png, "w": w, "h": h})

    def page_break(self):
        self.blocks.append({"type": "break"})


# ------------------------------------------------------------------ القياس (تقريبي، بلا Qt)
CHAR_W = 0.62        # عرض الحرف العربي التقريبي نسبة إلى حجم الخط (تقدير محافظ حتى لا يُقص النص)


def lines_for(text: str, width: float, pt: float) -> int:
    if width <= 4:
        return 1
    per = max(1, int(width / (pt * CHAR_W)))
    n = 0
    for para in (text or "").split("\n"):
        n += max(1, math.ceil(len(para) / per))
    return max(1, n)


def col_widths(block: dict, avail: float, layout: dict) -> list[tuple[int, float]]:
    """[(فهرس العمود، العرض)] للأعمدة الظاهرة."""
    tb = layout["table"]
    hidden = {int(x) for x in tb.get("hidden_cols", [])}
    n = len(block["headers"])
    base = block.get("widths")
    if not base:
        base = []
        for j in range(n):
            lens = [len(block["headers"][j])] + [len(r[j]) for r in block["rows"][:200] if j < len(r)]
            lens.sort()
            typical = lens[int(len(lens) * 0.85)] if lens else 4
            base.append(max(3.0, min(32.0, float(typical))))
    cw = {j: float(base[j]) * float(tb.get("col_weights", {}).get(str(j), 1.0)) for j in range(n) if j not in hidden}
    if not cw:
        cw = {0: 1.0}
    tot = sum(cw.values()) or 1.0
    return [(j, avail * w / tot) for j, w in cw.items()]


def _sizes(layout: dict) -> tuple[float, float]:
    tb = layout["table"]
    return float(tb.get("head_pt") or 8.5), float(tb.get("title_pt") or 8.0)


def row_height(cells: list[str], widths: list[tuple[int, float]], pt: float, min_h: float = 0.0) -> float:
    n = max((lines_for(cells[j] if j < len(cells) else "", w - 6, pt) for j, w in widths), default=1)
    return max(min_h, n * pt * 1.32 + 6)


def page_area(layout: dict) -> tuple[float, float, float, float, float, float]:
    """(W, H, أعلى منطقة الجدول في الصفحة الأولى، أعلاها في الصفحات التالية، أسفلها، العرض المتاح)."""
    W, H = L.paper_size(layout)
    mt, mr, mb, ml = (float(x) for x in layout["page"].get("margins", [22, 22, 22, 22]))
    tb = layout["table"]
    top1 = max(mt + 90, float(tb.get("top") or 150.0))
    top2 = mt + 34
    bottom = H - max(mb + 30, float(tb.get("bottom_gap") or 70.0))
    return W, H, top1, top2, bottom, W - ml - mr


def paginate(doc: ReportDoc, layout: dict) -> list[dict]:
    """يوزع الكتل على صفحات. كل صفحة: {"first": bool, "items": [...]} وكل عنصر بموضعه الرأسي y وارتفاعه."""
    W, H, top1, top2, bottom, avail = page_area(layout)
    hp, cp = _sizes(layout)
    min_row = float(layout["table"].get("row_h") or 0)
    pages = [{"first": True, "items": []}]
    y = top1

    def new_page():
        nonlocal y
        pages.append({"first": False, "items": []})
        y = top2

    for bi, b in enumerate(doc.blocks):
        if b["type"] == "break":
            if pages[-1]["items"]:
                new_page()
            continue
        if b["type"] == "image":
            iw, ih = float(b.get("w") or 800), float(b.get("h") or 300)
            h = min(bottom - top2 - 10, avail * ih / max(1.0, iw), 260.0)
            if y + h > bottom and pages[-1]["items"]:
                new_page()
            pages[-1]["items"].append({"type": "image", "block": bi, "y": y, "h": h})
            y += h + 6
            continue
        if b["type"] == "para":
            pt = float(b.get("size") or (cp + 1.5))
            h = lines_for(b["text"], avail - 8, pt * (1.12 if b.get("bold") else 1.0)) * pt * 1.45 + \
                (10 if b.get("heading") else 6)
            if y + h > bottom and pages[-1]["items"]:
                new_page()
            pages[-1]["items"].append({"type": "para", "block": bi, "y": y, "h": h})
            y += h
            continue
        widths = col_widths(b, avail, layout)
        head_h = row_height(b["headers"], widths, hp, 20)
        cap_h = (cp + 5) * 1.4 if b.get("caption") else 0
        rows = b["rows"]
        heights = [row_height(r, widths, cp, min_row) for r in rows]
        i = 0
        first_part = True
        while i < len(rows) or (first_part and not rows):
            need = cap_h + head_h + (heights[i] if i < len(rows) else 0)
            if y + need > bottom and pages[-1]["items"]:
                new_page()
            item = {"type": "table", "block": bi, "y": y, "rows": [], "heights": [], "head_h": head_h,
                    "caption": b.get("caption", "") if first_part else (b.get("caption", "") + " (تابع)" if b.get("caption") else ""),
                    "cap_h": cap_h}
            y += cap_h + head_h
            while i < len(rows) and (y + heights[i] <= bottom or not item["rows"]):
                item["rows"].append(i)
                item["heights"].append(heights[i])
                y += heights[i]
                i += 1
            pages[-1]["items"].append(item)
            y += 8
            first_part = False
            if i < len(rows):
                new_page()
            if not rows:
                break
    return pages


def sheets(db: Database, doc: ReportDoc, layout: dict | None = None, used=None) -> list[O.Sheet]:
    """صفحات التقرير كأوراق للمعاينة والمحرر. كل الصفحات تشترك في نفس قاموس التصميم."""
    kind = f"report_{doc.key}"
    if layout is None:
        layout, used = L.effective(db, kind)
    raw = O.template_fields(db, "report")
    today = date.today()
    values = O._common_values(db, today) | {"title": doc.title, "info": "\n".join(doc.info),
                                            "institution": db.get_setting("institution_name", ""),
                                            "target": doc.title}
    fields = {k: O.fill(v, values) for k, v in raw.items()}
    pages = paginate(doc, layout)
    first_table = next((b for b in doc.blocks if b["type"] == "table"), None)
    periods = [(h, "") for h in first_table["headers"]] if first_table else []
    out = []
    for i, pg in enumerate(pages):
        sh = O.Sheet(kind=kind, target_id=0, ws=today, scope="report", level_id=None, raw=raw, values=values,
                     fields=fields, days=[], periods=periods, cells=[], style=O.template_style(db),
                     name=doc.name or doc.title, layout=layout, layout_scopes=list(used or []))
        sh.report = pg
        sh.doc = doc
        sh.page_index = i
        sh.page_count = len(pages)
        out.append(sh)
    return out


# ------------------------------------------------------------------ من نموذج التقارير القديم
def from_model(rep, key: str) -> ReportDoc:
    """يحوّل تقرير exporters.model (Table / Grid / فقرات) إلى ReportDoc."""
    from .model import Grid, Table
    doc = ReportDoc(key, rep.title, list(rep.info_lines))
    for b in rep.blocks:
        if isinstance(b, Table):
            doc.table(b.headers, b.rows, widths=b.widths)
        elif isinstance(b, Grid):
            rows = [[lab] + [""] * len(b.col_labels) for lab in b.row_labels]
            spans, fills = {}, {}
            for c in b.cells:
                if 0 <= c.row < len(rows):
                    rows[c.row][c.col + 1] = c.text
                    if c.rowspan > 1:
                        spans[f"{c.row}:{c.col + 1}"] = c.rowspan
                    if c.color:
                        fills[f"{c.row}:{c.col + 1}"] = c.color
            doc.table(["التوقيت"] + list(b.col_labels), rows, fills=fills, spans=spans)
        elif isinstance(b, str):
            if b.strip():
                doc.para(b)
    return doc


# ------------------------------------------------------------------ Excel عام
def to_xlsx(doc: ReportDoc, path, layout: dict | None = None):
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = O.safe_filename(doc.title)[:28] or "تقرير"
    ws.sheet_view.rightToLeft = True
    thin = Side(style="thin", color="000000")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    head_fill = PatternFill("solid", fgColor=((layout or {}).get("table", {}).get("head_fill") or "#DCE6F1")[1:])
    r = 1
    ws.cell(r, 1, doc.title).font = Font(bold=True, size=14)
    r += 1
    for line in doc.info:
        ws.cell(r, 1, line)
        r += 1
    r += 1
    maxc = 1
    for b in doc.blocks:
        if b["type"] == "para":
            ws.cell(r, 1, b["text"]).font = Font(bold=bool(b.get("bold")), size=12 if b.get("heading") else 10)
            r += 1
            continue
        if b["type"] != "table":
            continue
        if b.get("caption"):
            ws.cell(r, 1, b["caption"]).font = Font(bold=True)
            r += 1
        for j, h in enumerate(b["headers"]):
            c = ws.cell(r, j + 1, h)
            c.font, c.alignment, c.border, c.fill = Font(bold=True), center, box, head_fill
        maxc = max(maxc, len(b["headers"]))
        r += 1
        for ri, row in enumerate(b["rows"]):
            for j, v in enumerate(row):
                c = ws.cell(r, j + 1, _num(v))
                c.alignment, c.border = center, box
                if ri in b.get("bold_rows", ()):
                    c.font = Font(bold=True)
                col = b["fills"].get(f"{ri}:{j}")
                if col and col.startswith("#") and len(col) == 7:
                    c.fill = PatternFill("solid", fgColor=col[1:])
            r += 1
        r += 1
    for j in range(1, maxc + 1):
        ws.column_dimensions[get_column_letter(j)].width = 16 if j > 1 else 26
    wb.save(path)
    return path


def _num(v):
    """الأرقام تُكتب أرقاماً في Excel (والنسب تبقى نصاً كما في التقرير)."""
    s = str(v).strip()
    try:
        return float(s) if s and s.replace(".", "", 1).lstrip("-").isdigit() else v
    except ValueError:
        return v
