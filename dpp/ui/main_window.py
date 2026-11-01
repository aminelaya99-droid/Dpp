"""النافذة الرئيسية: قائمة جانبية + صفحات."""
from __future__ import annotations

import importlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QStackedWidget, QVBoxLayout, QWidget)

from dpp import APP_TITLE, __version__
from dpp.ui.widgets import Page

# (المفتاح، العنوان، الوحدة، الصنف)
PAGES = [
    ("dashboard", "الرئيسية", "dpp.ui.dashboard_view", "DashboardPage"),
    ("structure", "التكوينات", "dpp.ui.structure_view", "StructurePage"),
    ("planner", "المخطط الأسبوعي", "dpp.ui.planner.planner_page", "PlannerPage"),
    ("scheduler", "المجدول الآلي", "dpp.ui.scheduler_view", "SchedulerPage"),
    ("data", "الأساتذة والمواد", "dpp.ui.data_view", "DataPage"),
    ("curriculum", "المقرر", "dpp.ui.curriculum_view", "CurriculumPage"),
    ("progress", "التقدم", "dpp.ui.progress_view", "ProgressPage"),
    ("events", "الأحداث", "dpp.ui.events_view", "EventsPage"),
    ("shooting", "الرمي والأسلحة", "dpp.ui.shooting_view", "ShootingPage"),
    ("printing", "الطباعة", "dpp.ui.print_view", "PrintPage"),
    ("import", "استيراد aSc", "dpp.ui.import_view", "ImportPage"),
    ("settings", "الإعدادات", "dpp.ui.settings_view", "SettingsPage"),
]


class PlaceholderPage(Page):
    def __init__(self, main, label: str, err: str = ""):
        self.title = label
        self.subtitle = "هذه الوحدة قيد الإنجاز"
        super().__init__(main)
        if err:
            lbl = QLabel(err)
            lbl.setObjectName("Muted")
            lbl.setWordWrap(True)
            self.root.addWidget(lbl)
        self.root.addStretch(1)


class MainWindow(QMainWindow):
    def __init__(self, user=None):
        super().__init__()
        self.user = user
        self.setWindowTitle(APP_TITLE)
        self.resize(1400, 860)
        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(210)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 10)
        brand = QLabel("DPP")
        brand.setObjectName("Brand")
        sub = QLabel("تسيير الجداول الزمنية والتكوين")
        sub.setObjectName("BrandSub")
        sv.addWidget(brand)
        sv.addWidget(sub)
        self.nav = QListWidget()
        self.nav.setObjectName("Nav")
        self.nav.setCursor(Qt.PointingHandCursor)
        sv.addWidget(self.nav, 1)
        ver = QLabel(f"الإصدار {__version__}" + (f" — {user.username}" if user else ""))
        ver.setObjectName("BrandSub")
        sv.addWidget(ver)
        h.addWidget(side)

        self.stack = QStackedWidget()
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.pages: dict[str, Page] = {}
        self.keys: list[str] = []
        for key, label, mod, cls in PAGES:
            QListWidgetItem(label, self.nav)
            self.keys.append(key)
            self.stack.addWidget(QWidget())  # يُنشأ عند أول فتح
        self.nav.currentRowChanged.connect(self._on_nav)
        self.statusBar().showMessage("جاهز")
        self.nav.setCurrentRow(0)

    def _build(self, idx: int) -> Page:
        key, label, mod, cls = PAGES[idx]
        try:
            page = getattr(importlib.import_module(mod), cls)(self)
        except ModuleNotFoundError as e:
            if e.name and e.name.startswith("dpp.ui"):
                page = PlaceholderPage(self, label)
            else:
                raise
        old = self.stack.widget(idx)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(idx, page)
        self.pages[key] = page
        return page

    def _on_nav(self, idx: int) -> None:
        if idx < 0:
            return
        key = self.keys[idx]
        page = self.pages.get(key) or self._build(idx)
        self.stack.setCurrentIndex(idx)
        page.refresh()

    def open_page(self, key: str, **kwargs) -> Page:
        idx = self.keys.index(key)
        page = self.pages.get(key) or self._build(idx)
        if kwargs and hasattr(page, "focus_on"):
            page.focus_on(**kwargs)
        if self.nav.currentRow() == idx:
            page.refresh()
        else:
            self.nav.setCurrentRow(idx)
        return page

    def status(self, text: str) -> None:
        self.statusBar().showMessage(text, 6000)
