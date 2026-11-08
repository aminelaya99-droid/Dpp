"""تصدير حقيقي إلى DOCX وXLSX وPDF مع دعم العربية واتجاه RTL."""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from .model import Grid, Report, Table

ASSETS = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent)) / "assets"
if not ASSETS.exists():
    ASSETS = Path(__file__).resolve().parent.parent / "assets"


def _hex(c: str | None, default="FFFFFF") -> str:
    if not c:
        return default
    c = c.lstrip("#")
    return c.upper() if len(c) == 6 else default


def _light(c: str | None, f: float = 0.75) -> str:
    """لون فاتح من لون المادة لخلفية الخلية (حتى يبقى النص مقروءاً)."""
    h = _hex(c, "")
    if not h:
        return "FFFFFF"
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (int(x + (255 - x) * f) for x in (r, g, b))
    return f"{r:02X}{g:02X}{b:02X}"


def export(report: Report, tpl: dict, fmt: str, path: str | os.PathLike) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = fmt.lower()
    if fmt == "docx":
        to_docx(report, tpl, path)
    elif fmt == "xlsx":
        to_xlsx(report, tpl, path)
    elif fmt == "pdf":
        to_pdf(report, tpl, path)
    else:
        raise ValueError("صيغة غير مدعومة")
    return path


# =================================================================== DOCX
def to_docx(rep: Report, tpl: dict, path: Path):
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    doc = Document()
    sec = doc.sections[0]
    w, h = (297, 420) if tpl["paper"] == "A3" else (210, 297)
    if tpl["orientation"] == "landscape":
        w, h = h, w
        sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Mm(w), Mm(h)
    top, right, bottom, left = tpl["margins_mm"]
    sec.top_margin, sec.right_margin, sec.bottom_margin, sec.left_margin = Mm(top), Mm(right), Mm(bottom), Mm(left)
    fs = tpl["font_size"]

    style = doc.styles["Normal"]
    style.font.name = "Arial"
    style.font.size = Pt(fs)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    rfonts.set(qn("w:cs"), "Arial")
    szcs = OxmlElement("w:szCs")
    szcs.set(qn("w:val"), str(fs * 2))
    rpr.append(szcs)

    def rtl_par(p, align=WD_ALIGN_PARAGRAPH.RIGHT):
        ppr = p._p.get_or_add_pPr()
        bidi = OxmlElement("w:bidi")
        ppr.append(bidi)
        p.alignment = align
        return p

    def add_text(container, text, size=None, bold=False, align=WD_ALIGN_PARAGRAPH.RIGHT, color=None):
        p = container.add_paragraph()
        rtl_par(p, align)
        run = p.add_run(text)
        run.bold = bold
        r = run._r.get_or_add_rPr()
        rtl = OxmlElement("w:rtl")
        r.append(rtl)
        if size:
            run.font.size = Pt(size)
            szc = OxmlElement("w:szCs")
            szc.set(qn("w:val"), str(int(size * 2)))
            r.append(szc)
        if bold:
            bcs = OxmlElement("w:bCs")
            r.append(bcs)
        if color:
            run.font.color.rgb = RGBColor.from_string(color)
        p.paragraph_format.space_after = Pt(1)
        return p

    # رأس الصفحة
    hdr = sec.header
    hp = hdr.paragraphs[0]
    rtl_par(hp)
    if rep.institution:
        hp.add_run(rep.institution).bold = True
    if rep.logo and os.path.isfile(rep.logo):
        try:
            hp.add_run().add_picture(rep.logo, height=Mm(12))
        except Exception:
            pass
    # تذييل: النص + التاريخ + رقم الصفحة
    fp = sec.footer.paragraphs[0]
    rtl_par(fp, WD_ALIGN_PARAGRAPH.CENTER)
    bits = []
    if tpl.get("footer_text"):
        bits.append(tpl["footer_text"])
    if tpl["show"].get("print_date"):
        bits.append("تاريخ الطباعة: " + datetime.now().strftime("%d/%m/%Y"))
    fp.add_run("  —  ".join(bits) + ("  —  صفحة " if tpl["show"].get("page_number") else ""))
    if tpl["show"].get("page_number"):
        run = fp.add_run()
        for t, txt in (("begin", None), (None, "PAGE"), ("end", None)):
            if t:
                el = OxmlElement("w:fldChar")
                el.set(qn("w:fldCharType"), t)
            else:
                el = OxmlElement("w:instrText")
                el.text = txt
            run._r.append(el)

    add_text(doc, rep.title, tpl["title_size"], True, WD_ALIGN_PARAGRAPH.CENTER)
    for line in rep.info_lines:
        add_text(doc, line, fs, False, WD_ALIGN_PARAGRAPH.CENTER)

    def set_cell_bg(cell, hexcolor):
        tcPr = cell._tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), hexcolor)
        tcPr.append(shd)

    def cell_text(cell, text, bold=False, size=None):
        cell.text = ""
        lines = str(text).split("\n")
        p = cell.paragraphs[0]
        rtl_par(p, WD_ALIGN_PARAGRAPH.CENTER)
        for i, line in enumerate(lines):
            run = p.add_run(line)
            run.bold = bold
            run.font.size = Pt(size or fs)
            rr = run._r.get_or_add_rPr()
            rr.append(OxmlElement("w:rtl"))
            if i < len(lines) - 1:
                run.add_break()

    def bidi_table(table):
        tblPr = table._tbl.tblPr
        bv = OxmlElement("w:bidiVisual")
        tblPr.append(bv)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        table.style = "Table Grid"

    for b in rep.blocks:
        if isinstance(b, Grid):
            t = doc.add_table(rows=len(b.row_labels) + 1, cols=len(b.col_labels) + 1)
            bidi_table(t)
            cell_text(t.cell(0, 0), "التوقيت", True)
            set_cell_bg(t.cell(0, 0), _hex(tpl["header_bg"]))
            for j, lab in enumerate(b.col_labels):
                c = t.cell(0, j + 1)
                cell_text(c, lab, True)
                set_cell_bg(c, _hex(tpl["header_bg"]))
            for i, lab in enumerate(b.row_labels):
                c = t.cell(i + 1, 0)
                cell_text(c, lab, True, fs - 1)
                set_cell_bg(c, _hex(tpl["header_bg"]))
            for cell in b.cells:
                top_c = t.cell(cell.row + 1, cell.col + 1)
                if cell.rowspan > 1:
                    top_c = top_c.merge(t.cell(cell.row + cell.rowspan, cell.col + 1))
                cell_text(top_c, cell.text, False, fs - 1)
                if cell.color:
                    set_cell_bg(top_c, _light(cell.color))
        elif isinstance(b, Table):
            t = doc.add_table(rows=len(b.rows) + 1, cols=len(b.headers))
            bidi_table(t)
            for j, hd in enumerate(b.headers):
                cell_text(t.cell(0, j), hd, True)
                set_cell_bg(t.cell(0, j), _hex(tpl["header_bg"]))
            # تكرار صف العناوين في كل صفحة
            trPr = t.rows[0]._tr.get_or_add_trPr()
            th = OxmlElement("w:tblHeader")
            th.set(qn("w:val"), "true")
            trPr.append(th)
            for i, row in enumerate(b.rows):
                for j, v in enumerate(row):
                    cell_text(t.cell(i + 1, j), "" if v is None else v, False, fs - 1)
            if not b.rows:
                add_text(doc, "لا توجد بيانات.", fs)
        else:
            add_text(doc, str(b), fs)

    if tpl.get("signatures"):
        doc.add_paragraph()
        st = doc.add_table(rows=2, cols=len(tpl["signatures"]))
        tblPr = st._tbl.tblPr
        tblPr.append(OxmlElement("w:bidiVisual"))
        for j, s in enumerate(tpl["signatures"]):
            cell_text(st.cell(0, j), s, True)
            cell_text(st.cell(1, j), "\n\n")
    doc.core_properties.title = rep.title
    doc.save(str(path))


# =================================================================== XLSX
def to_xlsx(rep: Report, tpl: dict, path: Path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = rep.title[:30].replace("/", "-").replace(":", "") or "DPP"
    ws.sheet_view.rightToLeft = True
    ws.page_setup.orientation = tpl["orientation"]
    ws.page_setup.paperSize = ws.PAPERSIZE_A3 if tpl["paper"] == "A3" else ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    top, right, bottom, left = (m / 25.4 for m in tpl["margins_mm"])
    ws.page_margins.top, ws.page_margins.right, ws.page_margins.bottom, ws.page_margins.left = top, right, bottom, left
    if tpl["show"].get("page_number"):
        ws.oddFooter.center.text = "صفحة &P / &N"
    if tpl["show"].get("print_date"):
        ws.oddFooter.right.text = "&D"
    if rep.institution:
        ws.oddHeader.right.text = rep.institution

    side = Side(style="thin", color=_hex(tpl["border_color"], "555555"))
    border = Border(left=side, right=side, top=side, bottom=side)
    center = Alignment(horizontal="center", vertical="center", wrap_text=True, readingOrder=2)
    hfill = PatternFill("solid", fgColor=_hex(tpl["header_bg"]))
    fs = tpl["font_size"]
    row = 1
    if rep.institution:
        ws.cell(row, 1, rep.institution).font = Font(bold=True, size=fs + 1)
        row += 1
    width = 2
    for b in rep.blocks:
        if isinstance(b, Grid):
            width = max(width, len(b.col_labels) + 1)
        elif isinstance(b, Table):
            width = max(width, len(b.headers))
    c = ws.cell(row, 1, rep.title)
    c.font = Font(bold=True, size=tpl["title_size"])
    c.alignment = center
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
    row += 1
    for line in rep.info_lines:
        ws.cell(row, 1, line).alignment = center
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=width)
        row += 1
    row += 1

    for b in rep.blocks:
        if isinstance(b, Grid):
            hdr = ["التوقيت"] + b.col_labels
            for j, v in enumerate(hdr, 1):
                c = ws.cell(row, j, v)
                c.font, c.fill, c.alignment, c.border = Font(bold=True, size=fs), hfill, center, border
            base = row + 1
            for i, lab in enumerate(b.row_labels):
                c = ws.cell(base + i, 1, lab)
                c.font, c.fill, c.alignment, c.border = Font(bold=True, size=fs - 1), hfill, center, border
                for j in range(len(b.col_labels)):
                    ws.cell(base + i, j + 2).border = border
                ws.row_dimensions[base + i].height = tpl.get("row_height") or 42
            for cell in b.cells:
                r0, col = base + cell.row, cell.col + 2
                c = ws.cell(r0, col, cell.text)
                c.alignment, c.font = center, Font(size=fs - 1)
                if cell.color:
                    c.fill = PatternFill("solid", fgColor=_light(cell.color))
                if cell.rowspan > 1:
                    ws.merge_cells(start_row=r0, start_column=col, end_row=r0 + cell.rowspan - 1, end_column=col)
            ws.column_dimensions["A"].width = 14
            for j in range(len(b.col_labels)):
                ws.column_dimensions[get_column_letter(j + 2)].width = tpl.get("col_width") or 26
            ws.print_title_rows = f"{row}:{row}"
            row = base + len(b.row_labels) + 1
        elif isinstance(b, Table):
            for j, v in enumerate(b.headers, 1):
                c = ws.cell(row, j, v)
                c.font, c.fill, c.alignment, c.border = Font(bold=True, size=fs), hfill, center, border
            ws.print_title_rows = f"{row}:{row}"
            for i, r in enumerate(b.rows, 1):
                for j, v in enumerate(r, 1):
                    c = ws.cell(row + i, j, v)
                    c.border, c.font = border, Font(size=fs)
                    c.alignment = Alignment(horizontal="right" if isinstance(v, str) else "center",
                                            vertical="center", wrap_text=True, readingOrder=2)
            for j, hd in enumerate(b.headers, 1):
                vals = [len(str(hd))] + [len(str(r[j - 1])) for r in b.rows if j - 1 < len(r)]
                ws.column_dimensions[get_column_letter(j)].width = min(45, max(8, max(vals) + 2))
            ws.auto_filter.ref = f"A{row}:{get_column_letter(len(b.headers))}{row + len(b.rows)}"
            row += len(b.rows) + 2
        else:
            ws.cell(row, 1, str(b))
            row += 1
    if tpl.get("signatures"):
        row += 1
        for j, s in enumerate(tpl["signatures"]):
            ws.cell(row, 1 + j * 2, s).font = Font(bold=True)
    wb.properties.title = rep.title
    wb.save(str(path))


# =================================================================== PDF
_FONT_READY = None


def _register_fonts():
    global _FONT_READY
    if _FONT_READY:
        return _FONT_READY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    candidates = []
    if os.name == "nt":
        wf = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
        candidates += [(wf / "arial.ttf", wf / "arialbd.ttf"), (wf / "tahoma.ttf", wf / "tahomabd.ttf")]
    candidates.append((ASSETS / "fonts" / "DejaVuSans.ttf", ASSETS / "fonts" / "DejaVuSans-Bold.ttf"))
    for reg, bold in candidates:
        if reg.exists():
            pdfmetrics.registerFont(TTFont("DPPAr", str(reg)))
            pdfmetrics.registerFont(TTFont("DPPAr-B", str(bold if bold.exists() else reg)))
            _FONT_READY = ("DPPAr", "DPPAr-B")
            return _FONT_READY
    raise RuntimeError("لم يتم العثور على خط عربي لملف PDF.")


def shape(text: str) -> str:
    """تشكيل الحروف العربية وترتيبها بصرياً لـ reportlab."""
    import arabic_reshaper
    from bidi.algorithm import get_display
    return "\n".join(get_display(arabic_reshaper.reshape(line)) for line in str(text).split("\n"))


def to_pdf(rep: Report, tpl: dict, path: Path):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A3, A4, landscape, portrait
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table as RLTable, TableStyle

    reg, bold = _register_fonts()
    size = A3 if tpl["paper"] == "A3" else A4
    size = landscape(size) if tpl["orientation"] == "landscape" else portrait(size)
    top, right, bottom, left = (m * mm for m in tpl["margins_mm"])
    fs = tpl["font_size"]
    p_center = ParagraphStyle("c", fontName=reg, fontSize=fs - 1, leading=(fs - 1) * 1.3, alignment=TA_CENTER)
    p_head = ParagraphStyle("h", parent=p_center, fontName=bold, fontSize=fs)
    p_title = ParagraphStyle("t", parent=p_center, fontName=bold, fontSize=tpl["title_size"],
                             leading=tpl["title_size"] * 1.4)
    p_right = ParagraphStyle("r", parent=p_center, alignment=TA_RIGHT)

    def para(text, style=p_center):
        t = shape(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        return Paragraph(t, style)

    def on_page(canv, doc):
        canv.saveState()
        canv.setFont(reg, 8)
        w, h = size
        bits = []
        if tpl["show"].get("page_number"):
            bits.append(f"{doc.page}")
        if tpl["show"].get("print_date"):
            bits.append(datetime.now().strftime("%d/%m/%Y"))
        if tpl.get("footer_text"):
            bits.append(shape(tpl["footer_text"]))
        canv.drawCentredString(w / 2, bottom / 2, "  —  ".join(bits))
        if rep.institution:
            canv.setFont(bold, 9)
            canv.drawRightString(w - right, h - top / 2, shape(rep.institution))
        canv.restoreState()

    story = []
    if rep.logo and os.path.isfile(rep.logo):
        try:
            story.append(Image(rep.logo, width=18 * mm, height=18 * mm, kind="proportional"))
        except Exception:
            pass
    story.append(para(rep.title, p_title))
    for line in rep.info_lines:
        story.append(para(line))
    story.append(Spacer(1, 4 * mm))
    avail = size[0] - left - right
    border = colors.HexColor(tpl["border_color"])
    hbg = colors.HexColor(tpl["header_bg"])

    for b in rep.blocks:
        if isinstance(b, Grid):
            ncol = len(b.col_labels)
            # RTL بصري: عمود التوقيت يميناً والأيام من اليمين إلى اليسار
            data = [[para(l, p_head) for l in reversed(b.col_labels)] + [para("التوقيت", p_head)]]
            for lab in b.row_labels:
                data.append([""] * ncol + [para(lab, p_head)])
            style = [("GRID", (0, 0), (-1, -1), 0.5, border), ("BACKGROUND", (0, 0), (-1, 0), hbg),
                     ("BACKGROUND", (-1, 0), (-1, -1), hbg), ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]
            for c in b.cells:
                col = ncol - 1 - c.col
                r0 = c.row + 1
                data[r0][col] = para(c.text)
                if c.rowspan > 1:
                    style.append(("SPAN", (col, r0), (col, r0 + c.rowspan - 1)))
                if c.color:
                    style.append(("BACKGROUND", (col, r0), (col, r0 + c.rowspan - 1),
                                  colors.HexColor("#" + _light(c.color))))
            tw = 30 * mm
            cw = (avail - tw) / max(1, ncol)
            t = RLTable(data, colWidths=[cw] * ncol + [tw], repeatRows=1)
            t.setStyle(TableStyle(style))
            story.append(t)
        elif isinstance(b, Table):
            n = len(b.headers)
            data = [[para(h, p_head) for h in reversed(b.headers)]]
            for r in b.rows:
                data.append([para("" if v is None else str(v), p_right if isinstance(v, str) else p_center)
                             for v in reversed(list(r) + [""] * (n - len(r)))])
            if not b.rows:
                data.append([para("لا توجد بيانات.")] + [""] * (n - 1))
            lens = [max([len(str(h))] + [len(str(r[i])) for r in b.rows if i < len(r)]) for i, h in enumerate(b.headers)]
            lens = [min(max(x, 4), 40) for x in reversed(lens)]
            tot = sum(lens)
            t = LongTable(data, colWidths=[avail * x / tot for x in lens], repeatRows=1)
            t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, border), ("BACKGROUND", (0, 0), (-1, 0), hbg),
                                   ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            story.append(t)
        else:
            story.append(para(str(b), p_right))
        story.append(Spacer(1, 4 * mm))
    if tpl.get("signatures"):
        sig = RLTable([[para(s, p_head) for s in reversed(tpl["signatures"])]],
                      colWidths=[avail / len(tpl["signatures"])] * len(tpl["signatures"]))
        story += [Spacer(1, 8 * mm), sig]
    doc = SimpleDocTemplate(str(path), pagesize=size, topMargin=top, bottomMargin=bottom, leftMargin=left,
                            rightMargin=right, title=rep.title, author="DPP")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
