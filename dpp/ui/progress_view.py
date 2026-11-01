"""التقدم: المنجز مقابل المقرر لكل فرع × مادة، التأخر على المرحلة الحالية، والوضع المبسط بالحلقات."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar,
                               QScrollArea, QStackedWidget, QTableWidget, QTableWidgetItem, QTabWidget,
                               QWidget)

from dpp.models import SUBJECT_KINDS, Section, Training
from dpp.services import progress, structure
from dpp.ui.theme import KIND_BASE, T
from dpp.ui.widgets import Page, stat_card


class Donut(QWidget):
    """حلقة: نسبة الإنجاز في الوسط، والساعات المتبقية تحتها."""

    def __init__(self, title: str, percent: float, remaining: float, planned: float | None, color: str):
        super().__init__()
        self.title, self.percent, self.remaining, self.planned, self.color = title, percent, remaining, planned, color
        self.setFixedSize(QSize(180, 215))
        self.setToolTip(f"{title}\nالمقرر: {planned if planned is not None else '—'} سا\nالمتبقي: {remaining:g} سا")

    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        side = min(self.width(), self.height() - 60) - 16
        r = QRectF((self.width() - side) / 2, 8, side, side)
        p.setPen(QPen(QColor("#E2E8F0"), 14, Qt.SolidLine, Qt.FlatCap))
        p.drawArc(r, 0, 360 * 16)
        p.setPen(QPen(QColor(self.color), 14, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(r, 90 * 16, int(-360 * 16 * self.percent / 100))
        p.setPen(QColor(T["text"]))
        f = QFont(self.font())
        f.setPointSize(15)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, "—" if self.planned is None else f"{self.percent:.0f}%")
        f.setPointSize(9)
        p.setFont(f)
        tr = QRectF(0, r.bottom() + 6, self.width(), 34)
        p.drawText(tr, Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap, self.title)
        f.setBold(False)
        f.setPointSizeF(8.5)
        p.setFont(f)
        p.setPen(QColor(T["muted"]))
        p.drawText(QRectF(0, tr.bottom(), self.width(), 18), Qt.AlignCenter,
                   "حجم ساعي ناقص" if self.planned is None else f"متبقٍ {self.remaining:g} سا من {self.planned:g}")
        p.end()


class ProgressPage(Page):
    title = "التقدم"
    subtitle = "الساعات المنجزة لكل فرع × مادة مقابل المقرر، بغض النظر عن الأستاذ"

    def __init__(self, main):
        super().__init__(main)
        bar = QHBoxLayout()
        self.training = QComboBox()
        self.section = QComboBox()
        self.mode = QComboBox()
        self.mode.addItem("الوضع المفصل", "detail")
        self.mode.addItem("الوضع المبسط (حلقات)", "simple")
        self.training.currentIndexChanged.connect(self._fill_sections)
        self.section.currentIndexChanged.connect(self.reload)
        self.mode.currentIndexChanged.connect(self.reload)
        for lbl, w in (("التكوين", self.training), ("الفرع", self.section), ("العرض", self.mode)):
            bar.addWidget(QLabel(lbl))
            w.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            bar.addWidget(w)
        bar.addStretch(1)
        from dpp.ui.widgets import button
        bar.addWidget(button("طباعة تقرير التقدم", self.print_report))
        self.root.addLayout(bar)
        cards = QHBoxLayout()
        self.st = {}
        for k, lbl in (("percent", "نسبة الإنجاز"), ("done", "ساعات منجزة / المقرر"),
                       ("delay", "التأخر (المرحلة الحالية)"), ("weeks", "أسابيع متبقية"), ("phase", "المرحلة الحالية")):
            f, v = stat_card("—", lbl)
            self.st[k] = v
            cards.addWidget(f)
        self.root.addLayout(cards)
        self.tabs = QTabWidget()
        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["المادة", "النوع", "المقرر", "المنجز", "النسبة",
                                              "المتوقع حتى اليوم", "التأخر", "المتبقي"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.stack.addWidget(self.table)
        self.donuts_host = QWidget()
        self.donuts = QGridLayout(self.donuts_host)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.donuts_host)
        self.stack.addWidget(sc)
        self.tabs.addTab(self.stack, "الفرع")
        self.summary = QTableWidget(0, 6)
        self.summary.setHorizontalHeaderLabels(["الفرع", "الطور / الاختصاص", "المرحلة", "النسبة", "التأخر (سا)",
                                                "أسابيع متبقية"])
        self.summary.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.summary.setEditTriggers(QTableWidget.NoEditTriggers)
        self.summary.cellDoubleClicked.connect(self._open_summary_row)
        self.tabs.addTab(self.summary, "ملخص كل الفروع")
        self.root.addWidget(self.tabs, 1)
        self._pending = None

    def focus_on(self, section_id: int | None = None, **_):
        sec = self.s.get(Section, section_id) if section_id else None
        if sec:
            self._pending = sec
            self.refresh()
            self.training.setCurrentIndex(max(0, self.training.findData(sec.training.id)))
            self.section.setCurrentIndex(max(0, self.section.findData(sec.id)))
            self.tabs.setCurrentIndex(0)
            self._pending = None

    def refresh(self) -> None:
        cur = self.training.currentData()
        self.training.blockSignals(True)
        self.training.clear()
        for t in structure.trainings(self.s):
            self.training.addItem(t.name, t.id)
        self.training.setCurrentIndex(max(0, self.training.findData(cur)))
        self.training.blockSignals(False)
        self._fill_sections()

    def _fill_sections(self) -> None:
        cur = self.section.currentData()
        self.section.blockSignals(True)
        self.section.clear()
        tid = self.training.currentData()
        for sec in structure.all_sections(self.s, training_id=tid) if tid else []:
            self.section.addItem(f"{sec.name} — {sec.level.code} / {sec.specialty.name}", sec.id)
        self.section.setCurrentIndex(max(0, self.section.findData(cur)))
        self.section.blockSignals(False)
        self.reload()

    def reload(self) -> None:
        self._fill_summary()
        sid = self.section.currentData()
        self.table.setRowCount(0)
        while self.donuts.count():
            w = self.donuts.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        for v in self.st.values():
            v.setText("—")
        if not sid:
            return
        sec = self.s.get(Section, sid)
        p = progress.section_progress(self.s, sec, dt.date.today())
        self.st["percent"].setText(f"{p.percent:.0f}%" if p.rows else "—")
        self.st["done"].setText(f"{p.done:g} / {p.planned:g}" if p.rows else "لا مقرر")
        self.st["delay"].setText(f"{p.delay:+.1f} سا" if p.rows else "—")
        self.st["delay"].setStyleSheet(f"color: {T['danger'] if p.delay > 0.5 else T['accent']};")
        self.st["weeks"].setText(str(p.remaining_weeks))
        self.st["phase"].setText(p.phase.name if p.phase else "—")
        self.stack.setCurrentIndex(0 if self.mode.currentData() == "detail" else 1)
        for r in p.rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            vals = [r.subject.name, SUBJECT_KINDS.get(r.subject.kind, ""),
                    "—" if r.planned is None else f"{r.planned:g}", f"{r.done:g}", None,
                    f"{r.expected:.1f}", f"{r.delay:+.1f}", f"{r.remaining:g}"]
            for c, v in enumerate(vals):
                if v is None:
                    bar = QProgressBar()
                    bar.setRange(0, 100)
                    bar.setValue(int(r.percent))
                    bar.setFormat(f"{r.percent:.0f}%")
                    bar.setStyleSheet(f"QProgressBar::chunk {{ background: {KIND_BASE.get(r.subject.kind, T['accent'])}; }}")
                    self.table.setCellWidget(row, c, bar)
                    continue
                it = QTableWidgetItem(v)
                if c == 6 and r.delay > 0.5:
                    it.setForeground(QColor(T["danger"]))
                if c == 2 and r.planned is None:
                    it.setBackground(QColor(T["warning_soft"]))
                self.table.setItem(row, c, it)
        cols = max(1, (self.width() - 60) // 190)
        for i, r in enumerate(p.rows):
            d = Donut(r.subject.name, r.percent, r.remaining, r.planned, KIND_BASE.get(r.subject.kind, T["accent"]))
            self.donuts.addWidget(d, i // cols, i % cols, Qt.AlignTop)
        self.donuts.setRowStretch(len(p.rows) // cols + 1, 1)
        self.donuts.setColumnStretch(cols, 1)

    def print_report(self) -> None:
        sid = self.section.currentData()
        if not sid:
            return
        from dpp.printing.reports import preview_report, progress_report
        sec = self.s.get(Section, sid)
        preview_report(self, self.s, progress_report(self.s, sec, progress.section_progress(self.s, sec)))

    def _fill_summary(self) -> None:
        self.summary.setRowCount(0)
        tid = self.training.currentData()
        if not tid:
            return
        for sec in structure.all_sections(self.s, training_id=tid):
            p = progress.section_progress(self.s, sec)
            r = self.summary.rowCount()
            self.summary.insertRow(r)
            vals = [sec.name, f"{sec.level.code} / {sec.specialty.name}", p.phase.name if p.phase else "—",
                    f"{p.percent:.0f}%" if p.rows else "لا مقرر", f"{p.delay:+.1f}" if p.rows else "—",
                    str(p.remaining_weeks)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, sec.id)
                if c == 4 and p.rows and p.delay > 0.5:
                    it.setForeground(QColor(T["danger"]))
                self.summary.setItem(r, c, it)

    def _open_summary_row(self, row: int, _col: int) -> None:
        sid = self.summary.item(row, 0).data(Qt.UserRole)
        self.section.setCurrentIndex(max(0, self.section.findData(sid)))
        self.tabs.setCurrentIndex(0)
