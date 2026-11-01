"""تقارير جدولية بسيطة (شجرة التكوينات، التقدم) مع ترقيم الصفحات وتكرار رأس الجدول."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from PySide6.QtCore import QMarginsF, QRectF, Qt
from PySide6.QtGui import QColor, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

from dpp.printing.render import Renderer
from dpp.services import settings as cfg
from dpp.services import structure


@dataclass
class TableReport:
    title: str
    headers: list[str]
    widths: list[float]           # نسب العرض
    rows: list[tuple[list[str], int]]  # (الخلايا، مستوى الإزاحة/التمييز)
    subtitle: str = ""
    landscape: bool = False


ROW_H, HEAD_H, TOP = 7.0, 8.0, 30.0


def paginate(rep: TableReport, page_h: float, margin: float = 12.0) -> list[list[tuple[list[str], int]]]:
    per_page = max(1, int((page_h - TOP - margin - 10 - HEAD_H) // ROW_H))
    return [rep.rows[i:i + per_page] for i in range(0, len(rep.rows), per_page)] or [[]]


def _page_layout(rep: TableReport) -> QPageLayout:
    return QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape if rep.landscape else QPageLayout.Portrait,
                       QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)


def paint_report(painter: QPainter, device, rep: TableReport, institution: str, new_page) -> int:
    pw, ph = (297.0, 210.0) if rep.landscape else (210.0, 297.0)
    k = min(device.width() / pw, device.height() / ph)
    r = Renderer(painter, k)
    pages = paginate(rep, ph)
    margin = 12.0
    tw = pw - 2 * margin
    tot = sum(rep.widths) or 1
    for pi, rows in enumerate(pages):
        if pi:
            new_page()
        painter.setPen(QColor("#000"))
        painter.setFont(r.font("Tahoma", 10, True))
        painter.drawText(r.R(margin, 8, tw, 6), Qt.AlignRight | Qt.AlignVCenter, institution)
        painter.setFont(r.font("Tahoma", 15, True))
        painter.drawText(r.R(margin, 14, tw, 9), Qt.AlignCenter, rep.title)
        painter.setFont(r.font("Tahoma", 9))
        painter.drawText(r.R(margin, 22, tw, 6), Qt.AlignCenter, rep.subtitle)
        y = TOP
        # الرأس (يتكرر في كل صفحة)
        x = pw - margin
        painter.setPen(r.pen("#333", 0.25))
        for h, w in zip(rep.headers, rep.widths):
            cw = tw * w / tot
            rect = r.R(x - cw, y, cw, HEAD_H)
            painter.fillRect(rect, QColor("#E8EEF4"))
            painter.drawRect(rect)
            painter.setFont(r.font("Tahoma", 9, True))
            painter.drawText(rect, Qt.AlignCenter, h)
            x -= cw
        y += HEAD_H
        for cells, level in rows:
            x = pw - margin
            for ci, (c, w) in enumerate(zip(cells, rep.widths)):
                cw = tw * w / tot
                rect = r.R(x - cw, y, cw, ROW_H)
                if level == 0:
                    painter.fillRect(rect, QColor("#F1F5F9"))
                painter.setPen(r.pen("#333", 0.2))
                painter.drawRect(rect)
                painter.setFont(r.font("Tahoma", 8.5, level <= 1 and ci == 0))
                inner = rect.adjusted(3 + (level * 4 * k if ci == 0 else 0), 0, -3 - (level * 4 * k if ci == 0 else 0), 0)
                painter.drawText(inner, (Qt.AlignRight if ci == 0 else Qt.AlignCenter) | Qt.AlignVCenter, c)
                x -= cw
            y += ROW_H
        painter.setFont(r.font("Tahoma", 8))
        painter.setPen(QColor("#555"))
        painter.drawText(r.R(margin, ph - 9, tw, 5), Qt.AlignCenter,
                         f"صفحة {pi + 1}/{len(pages)} — {dt.date.today():%d/%m/%Y}")
    return len(pages)


def export_report_pdf(s, rep: TableReport, path) -> int:
    w = QPdfWriter(str(path))
    w.setResolution(200)
    w.setPageLayout(_page_layout(rep))
    p = QPainter(w)
    n = paint_report(p, w, rep, cfg.get(s, "institution_name", ""), w.newPage)
    p.end()
    return n


def preview_report(parent, s, rep: TableReport) -> None:
    pr = QPrinter(QPrinter.HighResolution)
    pr.setFullPage(True)
    pr.setPageLayout(_page_layout(rep))
    dlg = QPrintPreviewDialog(pr, parent)
    dlg.setWindowTitle("معاينة قبل الطباعة")
    dlg.resize(1000, 800)

    def paint(printer):
        p = QPainter(printer)
        paint_report(p, printer, rep, cfg.get(s, "institution_name", ""), printer.newPage)
        p.end()
    dlg.paintRequested.connect(paint)
    dlg.exec()


def structure_report(s) -> TableReport:
    from dpp.ui.structure_view import section_progress_text
    rows: list[tuple[list[str], int]] = []
    for t in structure.trainings(s):
        n, h = structure.training_stats(t)
        rows.append(([t.name, t.code, str(n), str(h), ""], 0))
        for lv in t.levels:
            a, b = structure.level_stats(lv)
            rows.append(([lv.name, lv.code, str(a), str(b), ""], 1))
            for sp in lv.specialties:
                rows.append(([sp.name, sp.code, str(len(sp.sections)), str(sum(x.headcount for x in sp.sections)), ""], 2))
                for sec in sp.sections:
                    rows.append(([sec.name, sec.code, "", str(sec.headcount), section_progress_text(s, sec)], 3))
    return TableReport("شجرة التكوينات", ["الاسم", "الرمز", "الفروع", "التعداد", "التقدم"], [5, 2, 1.2, 1.2, 1.2], rows,
                       subtitle="التكوينات ← الأطوار ← الاختصاصات ← الفروع")


def print_structure_tree(parent, s) -> None:
    preview_report(parent, s, structure_report(s))


def progress_report(s, section, prog) -> TableReport:
    rows = [([r.subject.name, "—" if r.planned is None else f"{r.planned:g}", f"{r.done:g}", f"{r.percent:.0f}%",
              f"{r.delay:+.1f}", f"{r.remaining:g}"], 2) for r in prog.rows]
    sub = f"{section.level.name} — {section.specialty.name} — المرحلة: {prog.phase.name if prog.phase else '—'}"
    return TableReport(f"تقدم الفرع {section.name}", ["المادة", "المقرر", "المنجز", "النسبة", "التأخر", "المتبقي"],
                       [5, 1.3, 1.3, 1.3, 1.3, 1.3], rows, subtitle=sub)
