"""المجدول الآلي: معاينة ثم تنفيذ ملء الأسبوع."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from dpp.models import DAY_NAMES, Section, Training
from dpp.services import scheduler, structure
from dpp.services.timeutil import fmt, fmt_duration
from dpp.ui.theme import T, subject_color
from dpp.ui.widgets import Page, button, card, confirm, info


class SchedulerPage(Page):
    title = "المجدول الآلي"
    subtitle = "ملء الأسبوع من المقرر المتبقي مع الحفاظ على أساتذة الأسابيع السابقة واحترام كل القواعد"

    def __init__(self, main):
        super().__init__(main)
        f, lay = card(QHBoxLayout)
        self.training = QComboBox()
        self.training.currentIndexChanged.connect(self._fill)
        self.week = QSpinBox()
        self.week.setRange(1, 200)
        self.week.setPrefix("الأسبوع ")
        self.block = QComboBox()
        for m in (60, 90, 120, 180, 240):
            self.block.addItem(f"كتلة {fmt_duration(m)}", m)
        self.block.setCurrentIndex(2)
        self.replace = QCheckBox("استبدال الحصص الآلية السابقة")
        self.replace.setChecked(True)
        for w in (QLabel("التكوين"), self.training, self.week, self.block, self.replace):
            lay.addWidget(w)
        lay.addStretch(1)
        lay.addWidget(button("معاينة", self.preview))
        lay.addWidget(button("تنفيذ", self.apply, primary=True))
        lay.addWidget(button("فتح في المخطط", self.open_planner))
        self.root.addWidget(f)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("الفروع المعنية"))
        self.sections = QListWidget()
        lv.addWidget(self.sections, 1)
        r = QHBoxLayout()
        r.addWidget(button("الكل", lambda: self._check_all(True)))
        r.addWidget(button("لا شيء", lambda: self._check_all(False)))
        lv.addLayout(r)
        mid = QWidget()
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(0, 0, 0, 0)
        self.summary = QLabel("")
        self.summary.setStyleSheet("font-weight: 700;")
        mv.addWidget(self.summary)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["الفرع", "المادة", "الأستاذ", "اليوم", "الوقت", "المدة"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        mv.addWidget(self.table, 1)
        self.warn_list = QListWidget()
        self.warn_list.setWordWrap(True)
        self.warn_list.setMaximumHeight(150)
        mv.addWidget(self.warn_list)
        split.addWidget(left)
        split.addWidget(mid)
        split.setSizes([260, 1000])
        self.root.addWidget(split, 1)

    def refresh(self) -> None:
        cur = self.training.currentData()
        self.training.blockSignals(True)
        self.training.clear()
        for t in structure.trainings(self.s):
            self.training.addItem(t.name, t.id)
        self.training.setCurrentIndex(max(0, self.training.findData(cur)))
        self.training.blockSignals(False)
        self._fill()

    def _training(self) -> Training | None:
        return self.s.get(Training, self.training.currentData()) if self.training.currentData() else None

    def _fill(self) -> None:
        t = self._training()
        self.sections.clear()
        if not t:
            return
        self.week.setRange(1, t.weeks_count)
        self.week.setValue(min(t.weeks_count, structure.current_week_number(t) + 1))
        for sec in structure.all_sections(self.s, training_id=t.id):
            it = QListWidgetItem(f"{sec.name} — {sec.level.code} / {sec.specialty.name}")
            it.setData(Qt.UserRole, sec.id)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.sections.addItem(it)

    def _check_all(self, on: bool) -> None:
        for i in range(self.sections.count()):
            self.sections.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

    def _chosen(self) -> list[Section]:
        return [self.s.get(Section, self.sections.item(i).data(Qt.UserRole)) for i in range(self.sections.count())
                if self.sections.item(i).checkState() == Qt.Checked]

    def _run(self, dry: bool) -> scheduler.ScheduleResult | None:
        t = self._training()
        secs = self._chosen()
        if not t or not secs:
            info(self, "اختر التكوين وفرعاً واحداً على الأقل")
            return None
        res = scheduler.schedule_week(self.s, t, self.week.value(), secs, block=self.block.currentData(),
                                      replace_auto=self.replace.isChecked(), dry_run=dry)
        self._show(res, dry)
        return res

    def _show(self, res: scheduler.ScheduleResult, dry: bool) -> None:
        self.summary.setText(("معاينة: " if dry else "نُفذ: ") + res.summary())
        self.table.setRowCount(0)
        for p in sorted(res.proposals, key=lambda p: (p.section.name, p.day, p.start)):
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [p.section.name, p.subject.name, p.teacher.display_name if p.teacher else "—",
                    DAY_NAMES[p.day], f"{fmt(p.start)} – {fmt(p.start + p.duration)}", fmt_duration(p.duration)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 1:
                    it.setBackground(subject_color(p.subject))
                self.table.setItem(r, c, it)
        self.warn_list.clear()
        for w in res.warnings:
            it = QListWidgetItem(w)
            it.setForeground(QColor("#92400E"))
            self.warn_list.addItem(it)

    def preview(self) -> None:
        self._run(True)

    def apply(self) -> None:
        if confirm(self, f"ملء الأسبوع {self.week.value()} آلياً للفروع المختارة؟"):
            res = self._run(False)
            if res and self.main:
                self.main.status(f"المجدول الآلي: {res.summary()}")

    def open_planner(self) -> None:
        if self.main:
            self.main.open_page("planner", training_id=self.training.currentData(), week=self.week.value())
