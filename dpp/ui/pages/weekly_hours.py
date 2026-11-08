"""الحجم الساعي الأسبوعي: سطر لكل قسم × مادة، عمود لكل أسبوع — لكشف أخطاء الاستيراد وتصحيحها."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...services import progress as P
from ...services.grid import week_number
from ...utils import to_date
from .. import theme
from ..widgets import error, icon

FIXED = ["القسم", "المادة", "المقرر"]


class _Num(QTableWidgetItem):
    def __init__(self, v, text=None):
        super().__init__(text if text is not None else ("" if v in (None, 0) else f"{v:g}"))
        self.v = -1e18 if v is None else v
        self.setTextAlignment(Qt.AlignCenter)

    def __lt__(self, other):
        return self.v < getattr(other, "v", 0)


class AdjustDialog(QDialog):
    def __init__(self, parent, title: str, actual: float, current: float | None, note: str = ""):
        super().__init__(parent)
        self.setWindowTitle("تصحيح الحجم الساعي")
        f = QFormLayout(self)
        f.addRow(QLabel(title))
        f.addRow("المسجّل من الحصص:", QLabel(f"{actual:g} سا"))
        self.val = QDoubleSpinBox()
        self.val.setRange(0, 80)
        self.val.setDecimals(1)
        self.val.setSingleStep(0.5)
        self.val.setSuffix(" سا")
        self.val.setValue(current if current is not None else actual)
        f.addRow("الساعات الصحيحة:", self.val)
        self.note = QLineEdit(note)
        self.note.setPlaceholderText("سبب التصحيح (اختياري)")
        f.addRow("ملاحظة:", self.note)
        f.addRow(QLabel("التصحيح يُحتسب في التقدم ونسبة التنفيذ، والحصص لا تتغير."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.val.selectAll()


class WeeklyHoursView(QWidget):
    def __init__(self, ctx, section_getter):
        super().__init__()
        self.ctx = ctx
        self.section_getter = section_getter
        self.data = {"weeks": [], "rows": []}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة أو قسم…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search)
        self.chk_planned = QCheckBox("مع الحصص المبرمجة القادمة")
        self.chk_planned.setChecked(True)
        self.chk_planned.setToolTip("بدون هذا الخيار: المنجزة فقط")
        self.chk_planned.toggled.connect(self.refresh)
        bar.addWidget(self.chk_planned)
        self.chk_adj = QCheckBox("المصحّحة فقط")
        self.chk_adj.toggled.connect(self._filter)
        bar.addWidget(self.chk_adj)
        bar.addStretch()
        b = QPushButton(icon("mdi6.file-excel-outline"), "Excel")
        b.clicked.connect(self.export_xlsx)
        bar.addWidget(b)
        lay.addLayout(bar)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._double)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        self.hint = QLabel("نقر مزدوج على خانة أسبوع: يفتح ذلك الأسبوع في الجدول العام على القسم لتصلّح الحصة. "
                           "الزر الأيمن ← «تصحيح الرقم» لكتابة الساعات الصحيحة مباشرة (الخانة المصحّحة بخط عريض ولون).")
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)

    # ------------------------------------------------------------------
    def refresh(self):
        self.data = P.weekly_hours(self.ctx.db, self.ctx.formation_ids(), self.section_getter(),
                                   self.chk_planned.isChecked())
        weeks = self.data["weeks"]
        t = self.table
        t.setUpdatesEnabled(False)
        t.setSortingEnabled(False)
        t.clear()
        t.setColumnCount(len(FIXED) + len(weeks) + 1)
        heads = FIXED + [f"أ{week_number(self.ctx.db, to_date(w))}\n{to_date(w).strftime('%d/%m')}" for w in weeks] \
            + ["المجموع"]
        t.setHorizontalHeaderLabels(heads)
        t.setRowCount(len(self.data["rows"]))
        adj_bg = QColor(theme.CURRENT.get("accent", "#0EA5A4"))
        adj_bg.setAlpha(55)
        bold = QFont()
        bold.setBold(True)
        today = date.today().isoformat()
        for i, r in enumerate(self.data["rows"]):
            a = QTableWidgetItem(r["section"])
            a.setData(Qt.UserRole, i)
            t.setItem(i, 0, a)
            t.setItem(i, 1, QTableWidgetItem(r["subject"]))
            t.setItem(i, 2, _Num(r["hours"], "—" if not r["hours"] else None))
            for j, w in enumerate(weeks):
                v = r["effective"].get(w)
                it = _Num(v or 0)
                if w in r["adjust"]:
                    it.setBackground(adj_bg)
                    it.setFont(bold)
                    it.setToolTip(f"مصحّح: {r['adjust'][w]:g} سا (المسجّل {r['actual'].get(w, 0):g} سا)"
                                  + (f"\n{r['notes'][w]}" if r["notes"].get(w) else ""))
                elif w > today:
                    it.setForeground(QColor(theme.CURRENT.get("muted", "#888888")))
                    it.setToolTip("مبرمج (لم يُنجز بعد)")
                t.setItem(i, 3 + j, it)
            tot = _Num(r["total"])
            tot.setFont(bold)
            t.setItem(i, 3 + len(weeks), tot)
        t.setSortingEnabled(True)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        t.resizeColumnsToContents()
        for c in range(3, t.columnCount()):
            t.setColumnWidth(c, max(46, min(64, t.columnWidth(c))))
        t.setUpdatesEnabled(True)
        self._filter()

    def _filter(self):
        txt = self.search.text().strip()
        only = self.chk_adj.isChecked()
        for i in range(self.table.rowCount()):
            r = self._row(i)
            if r is None:
                continue
            hide = bool(txt) and txt not in r["subject"] and txt not in r["section"]
            hide = hide or (only and not r["adjust"])
            self.table.setRowHidden(i, bool(hide))

    def _row(self, table_row: int):
        it = self.table.item(table_row, 0)
        if it is None:
            return None
        idx = it.data(Qt.UserRole)
        return self.data["rows"][idx] if idx is not None else None

    def _week_of(self, col: int):
        j = col - 3
        weeks = self.data["weeks"]
        return weeks[j] if 0 <= j < len(weeks) else None

    def _double(self, row, col):
        r, w = self._row(row), self._week_of(col)
        if r and w:
            self.ctx.navigate.emit("master", ("week_section", w, r["section_id"]))

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        if it is None:
            return
        r, w = self._row(it.row()), self._week_of(it.column())
        if not r:
            return
        m = QMenu(self)
        if w:
            m.addAction(icon("mdi6.pencil-outline"), "تصحيح الرقم…", lambda: self.adjust(r, w))
            if w in r["adjust"]:
                m.addAction(icon("mdi6.undo"), "إلغاء التصحيح", lambda: self.clear(r, w))
            m.addAction(icon("mdi6.table-eye"), "فتح الأسبوع في الجدول العام",
                        lambda: self.ctx.navigate.emit("master", ("week_section", w, r["section_id"])))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def adjust(self, r, w):
        n = week_number(self.ctx.db, to_date(w))
        dlg = AdjustDialog(self, f"{r['section']} — {r['subject']} — الأسبوع {n}", r["actual"].get(w, 0),
                           r["adjust"].get(w), r["notes"].get(w, ""))
        if dlg.exec() != QDialog.Accepted:
            return
        try:
            P.set_adjust(self.ctx.db, r["section_id"], r["subject_id"], w, dlg.val.value(), dlg.note.text().strip())
        except Exception as e:
            error(self, f"تعذر الحفظ: {e}")
            return
        self.ctx.changed("curriculum")

    def clear(self, r, w):
        P.clear_adjust(self.ctx.db, r["section_id"], r["subject_id"], w)
        self.ctx.changed("curriculum")

    def export_xlsx(self):
        from pathlib import Path

        import openpyxl
        from openpyxl.styles import Font, PatternFill
        path, _ = QFileDialog.getSaveFileName(self, "تصدير Excel", str(Path.home() / "الحجم_الساعي_الأسبوعي.xlsx"),
                                              "*.xlsx")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "الحجم الساعي"
        ws.sheet_view.rightToLeft = True
        weeks = self.data["weeks"]
        ws.append(FIXED + [f"الأسبوع {week_number(self.ctx.db, to_date(w))}" for w in weeks] + ["المجموع"])
        for c in ws[1]:
            c.font = Font(bold=True)
        fill = PatternFill("solid", fgColor="CCEFEF")
        for r in self.data["rows"]:
            ws.append([r["section"], r["subject"], r["hours"] or ""] + [r["effective"].get(w) or "" for w in weeks]
                      + [r["total"]])
            for j, w in enumerate(weeks):
                if w in r["adjust"]:
                    ws.cell(ws.max_row, 4 + j).fill = fill
        ws.column_dimensions["A"].width = 28
        ws.column_dimensions["B"].width = 34
        try:
            wb.save(path)
        except Exception as e:
            error(self, f"تعذر الحفظ: {e}")
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
