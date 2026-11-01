"""الصفحة الرئيسية: لمحة عامة."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import func, select
from PySide6.QtWidgets import QGridLayout, QLabel, QListWidget

from dpp.models import Alert, Lesson, Section, Teacher, Week
from dpp.services import structure
from dpp.ui.widgets import Page, card, stat_card


class DashboardPage(Page):
    title = "الرئيسية"
    subtitle = "لمحة عامة عن التكوينات والأسابيع"

    def __init__(self, main):
        super().__init__(main)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.vals = {}
        for i, (k, lbl) in enumerate([("sections", "فرع"), ("teachers", "أستاذ"),
                                      ("weeks", "أسبوع مجدول"), ("lessons", "حصة"),
                                      ("alerts", "تنبيه مفتوح")]):
            f, v = stat_card("0", lbl)
            self.vals[k] = v
            grid.addWidget(f, 0, i)
        self.root.addLayout(grid)
        f, lay = card()
        t = QLabel("التكوينات والأسبوع الحالي")
        t.setStyleSheet("font-weight: 700;")
        lay.addWidget(t)
        self.list = QListWidget()
        lay.addWidget(self.list)
        self.root.addWidget(f, 1)

    def refresh(self) -> None:
        s = self.s
        cnt = lambda m: s.scalar(select(func.count(m.id))) or 0  # noqa: E731
        self.vals["sections"].setText(str(cnt(Section)))
        self.vals["teachers"].setText(str(cnt(Teacher)))
        self.vals["weeks"].setText(str(cnt(Week)))
        self.vals["lessons"].setText(str(cnt(Lesson)))
        self.vals["alerts"].setText(str(s.scalar(select(func.count(Alert.id)).where(Alert.resolved.is_(False))) or 0))
        self.list.clear()
        today = dt.date.today()
        for t in structure.trainings(s):
            wn = structure.current_week_number(t, today)
            ph = structure.phase_for_week(t, wn)
            n, h = structure.training_stats(t)
            self.list.addItem(f"{t.name} ({t.code}) — الأسبوع {wn}/{t.weeks_count}"
                              f" — {ph.name if ph else 'خارج المخطط'} — {n} فرع، {h} طالب")
