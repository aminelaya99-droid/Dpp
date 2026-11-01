"""الإخراج: معاينة قبل الطباعة، الطباعة، وتصدير PDF (فرع واحد أو كل فروع الطور)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QPdfWriter
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

from dpp.printing import template as tpl
from dpp.printing.render import RenderContext, build_table_data, render_page

PAGE_IDS = {"A4": QPageSize.A4, "A3": QPageSize.A3, "Letter": QPageSize.Letter, "A5": QPageSize.A5}


@dataclass
class Sheet:
    """ورقة للطباعة: قالب + فرع + أسبوع."""
    layout: dict
    section: object
    week: object


def make_sheets(s, sections, week_for) -> list[Sheet]:
    out = []
    for sec in sections:
        lay, _src = tpl.effective(s, sec)
        out.append(Sheet(lay, sec, week_for(sec)))
    return out


def page_layout(layout: dict) -> QPageLayout:
    size = QPageSize(PAGE_IDS.get(layout["page"].get("size", "A4"), QPageSize.A4))
    orient = QPageLayout.Landscape if layout["page"].get("orientation") == "landscape" else QPageLayout.Portrait
    return QPageLayout(size, orient, QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)


def _paint_sheets(s, painter: QPainter, device, sheets: list[Sheet], new_page) -> list[str]:
    from dpp.ui.theme import subject_color
    missing: set[str] = set()
    n = len(sheets)
    for i, sh in enumerate(sheets):
        if i:
            new_page(sh.layout)
        values = tpl.field_values(s, sh.section, sh.week, i + 1, n)
        ctx = RenderContext(values, build_table_data(sh.section, sh.week, subject_color))
        pw_mm, ph_mm = tpl.page_mm(sh.layout)
        dev_w, dev_h = device.width(), device.height()
        k = min(dev_w / pw_mm, dev_h / ph_mm)  # ملاءمة الصفحة إن اختلف المقاس
        missing |= set(render_page(painter, sh.layout, ctx, k))
    return sorted(missing)


def export_pdf(s, sheets: list[Sheet], path: str | Path, resolution: int = 300) -> list[str]:
    if not sheets:
        raise ValueError("لا توجد أوراق للتصدير")
    w = QPdfWriter(str(path))
    w.setResolution(resolution)
    w.setTitle("DPP")
    w.setCreator("DPP")
    w.setPageLayout(page_layout(sheets[0].layout))
    painter = QPainter(w)

    def new_page(layout):
        w.setPageLayout(page_layout(layout))
        w.newPage()
    missing = _paint_sheets(s, painter, w, sheets, new_page)
    painter.end()
    return missing


def print_preview(parent, s, sheets: list[Sheet]) -> None:
    printer = QPrinter(QPrinter.HighResolution)
    printer.setFullPage(True)
    printer.setPageLayout(page_layout(sheets[0].layout))
    dlg = QPrintPreviewDialog(printer, parent)
    dlg.setWindowTitle("معاينة قبل الطباعة")
    dlg.resize(1100, 800)

    def paint(pr: QPrinter):
        painter = QPainter(pr)

        def new_page(layout):
            pr.setPageLayout(page_layout(layout))
            pr.newPage()
        _paint_sheets(s, painter, pr, sheets, new_page)
        painter.end()
    dlg.paintRequested.connect(paint)
    dlg.exec()
