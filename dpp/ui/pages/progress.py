"""تقدم الأقسام: قداش قرا كل قسم من كل مادة مقارنة بالمقرر، وقداش باقيلو باش ما يتأخرش (المرحلة الحالية)."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDateEdit, QFrame, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMenu, QScrollArea, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...services import progress as P
from .. import theme
from ..context import AppContext
from ..widgets import DonutChart, icon, page_title

COLS = ["القسم", "المادة", "المرحلة", "المقرر", "المنجز", "الباقي", "نسبة الإنجاز", "المتوقع حتى التاريخ",
        "نسبة التنفيذ", "التأخر / التقدم", "المطلوب أسبوعياً", "مبرمج قادم", "غير مسجّل", "أسابيع باقية"]


class _Num(QTableWidgetItem):
    """خانة رقمية تُرتَّب حسب القيمة، وتعرض «—» عند غياب القيمة."""

    def __init__(self, v, suffix=""):
        super().__init__("—" if v is None else f"{v:g}{suffix}")
        self.v = -1e18 if v is None else v
        self.setTextAlignment(Qt.AlignCenter)

    def __lt__(self, other):
        return self.v < getattr(other, "v", 0)


class ProgressPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.rows: list[dict] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title(
            "المقرر والتقدم",
            "المرجع لكل إحصائيات الساعات: المقرر لكل مادة حسب الاختصاص، والمنجز، والتحليلات، والتنبيهات. "
            "انقر مرتين على خانة «المقرر» لتعديله."))
        bar = QHBoxLayout()
        bar.addWidget(QLabel("القسم:"))
        self.section = QComboBox()
        self.section.setMinimumWidth(240)
        self.section.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.section)
        bar.addWidget(QLabel("حتى تاريخ:"))
        self.asof = QDateEdit()
        self.asof.setCalendarPopup(True)
        self.asof.setDisplayFormat("dd/MM/yyyy")
        self.asof.setDate(date.today())
        self.asof.dateChanged.connect(self.refresh)
        bar.addWidget(self.asof)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة…")
        self.search.textChanged.connect(self._apply_filter)
        bar.addWidget(self.search)
        self.only_late = QCheckBox("المتأخرة فقط")
        self.only_late.toggled.connect(self._apply_filter)
        bar.addWidget(self.only_late)
        self.only_missing = QCheckBox("بلا مقرر")
        self.only_missing.toggled.connect(self._apply_filter)
        bar.addWidget(self.only_missing)
        bar.addStretch()
        lay.addLayout(bar)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        lay.addWidget(self.summary)
        split = QSplitter(Qt.Vertical)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setMinimumHeight(170)
        self.donut_host = QWidget()
        self.donut_row = QHBoxLayout(self.donut_host)
        self.donut_row.setContentsMargins(0, 0, 0, 0)
        sc.setWidget(self.donut_host)
        split.addWidget(sc)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.cellDoubleClicked.connect(self._edit_hours)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        split.addWidget(self.table)
        split.setSizes([190, 600])
        from PySide6.QtWidgets import QTabWidget

        from .curriculum_page import CurriculumPage
        from .progress_views import AlertsView, AnalyticsView, SimpleView
        from .weekly_hours import WeeklyHoursView
        self.tabs = QTabWidget()
        self.simple = SimpleView(self)
        self.tabs.addTab(self.simple, icon("mdi6.chart-donut"), "المقرر والمنجز")
        self.legacy = split
        self.tabs.addTab(split, icon("mdi6.chart-timeline-variant"), "التقدم ونسبة التنفيذ")
        self.weekly = WeeklyHoursView(ctx, lambda: self.section.currentData())
        self.tabs.addTab(self.weekly, icon("mdi6.table-clock"), "الحجم الساعي الأسبوعي")
        self.curriculum = CurriculumPage(ctx)
        self.tabs.addTab(self.curriculum, icon("mdi6.book-clock-outline"), "المقرر")
        self.analytics = AnalyticsView(self)
        self.tabs.addTab(self.analytics, icon("mdi6.chart-box-outline"), "التحليلات")
        self.alerts = AlertsView(self)
        self.tabs.addTab(self.alerts, icon("mdi6.alert-circle-outline"), "التنبيهات")
        self.tabs.currentChanged.connect(lambda _i: self._refresh_current())
        lay.addWidget(self.tabs, 1)
        ctx.data_changed.connect(self._on_change)
        ctx.formation_changed.connect(lambda _: self._fill_sections())
        self._fill_sections()

    def _on_change(self, w):
        if w == "theme":
            return
        if w in ("*", "sections"):
            self._fill_sections()
        elif w in ("sessions", "sessions_grid", "curriculum", "timeline", "subjects", "alerts"):
            self.refresh()

    def _fill_sections(self):
        self.section.blockSignals(True)
        cur = self.section.currentData()
        self.section.clear()
        self.section.addItem("كل الأقسام", None)
        for r in self.ctx.q("""SELECT s.id, s.short, s.name FROM sections s LEFT JOIN levels l ON l.id=s.level_id
                               WHERE s.formation_id=? ORDER BY COALESCE(l.sort, 99), s.sort, s.id""",
                            (self.ctx.formation_id or -1,)):
            self.section.addItem(f"{r['short']} — {r['name']}", r["id"])
        i = self.section.findData(cur)
        self.section.setCurrentIndex(max(0, i))
        self.section.blockSignals(False)
        self.refresh()

    # ------------------------------------------------------------------ أدوات للتبويبات
    def today(self):
        return self.asof.date().toPython()

    def set_alert_count(self, n: int):
        i = self.tabs.indexOf(self.alerts)
        self.tabs.setTabText(i, f"التنبيهات ({n})" if n else "التنبيهات")

    def show_curriculum(self, issues=False):
        self.tabs.setCurrentWidget(self.curriculum)
        if issues and hasattr(self.curriculum, "tabs"):
            self.curriculum.tabs.setCurrentIndex(self.curriculum.tabs.count() - 1)

    def select_section(self, sid):
        i = self.section.findData(sid)
        if i >= 0:
            self.section.setCurrentIndex(i)
        self.tabs.setCurrentWidget(self.simple)

    def edit_total_hours(self, r):
        v, ok = QInputDialog.getDouble(self, "المقرر", f"الحجم الساعي المقرر لمادة «{r['subject']}»\n"
                                       f"للتكوين كاملاً — اختصاص القسم ({r['level']})", r["hours"] or 0, 0, 5000, 1)
        if ok:
            P.set_hours(self.ctx.db, r["level_id"], r["specialty_id"], r["subject_id"], "all", v)
            self.ctx.changed("curriculum")

    def _refresh_current(self):
        w = self.tabs.currentWidget()
        for x in (self.search, self.only_late, self.only_missing):
            x.setVisible(w is self.legacy)
        if w is self.simple:
            self.simple.refresh()
        elif w is self.weekly:
            self.weekly.refresh()
        elif w is self.analytics:
            self.analytics.refresh()
        elif w is self.alerts:
            self.alerts.refresh()
        elif w is self.legacy:
            self._refresh_legacy()

    def refresh(self):
        if getattr(self, "tabs", None) is None:
            return
        self._refresh_current()
        try:
            from ...services import alerts as AL
            n = AL.count_open(self.ctx.db) + (1 if self.ctx.db.scalar(
                "SELECT COUNT(*) FROM curriculum_issues WHERE resolved=0", (), 0) else 0)
            if self.tabs.currentWidget() is not self.alerts:
                self.set_alert_count(n)
        except Exception:
            pass

    def _refresh_legacy(self):
        today = self.asof.date().toPython()
        self.rows = P.section_progress(self.ctx.db, self.ctx.formation_ids(), today, self.section.currentData())
        s = P.summarize(self.rows)
        parts = [f"{len({r['section_id'] for r in self.rows})} قسماً · {len(self.rows)} مادة"]
        if s["pct_done"] is not None:
            parts.append(f"نسبة الإنجاز الكلية {s['pct_done']:g}% ({s['done']:g} من {s['hours']:g} سا)")
        if s["pct_exec"] is not None:
            parts.append(f"نسبة التنفيذ {s['pct_exec']:g}% من المتوقع ({s['expected']:g} سا)")
        if s["late"]:
            parts.append(f"<b style='color:{theme.CURRENT['bad']}'>{s['late']} مادة متأخرة</b>")
        if s["missing"]:
            parts.append(f"<span style='color:{theme.CURRENT['warn']}'>{s['missing']} مادة بلا مقرر — "
                         "استورد البرنامج الرسمي أو أدخل المقرر يدوياً (نقر مزدوج)</span>")
        self.summary.setText(" · ".join(parts))
        self._fill_donuts()
        self._fill_table()

    def _fill_donuts(self):
        while self.donut_row.count():
            w = self.donut_row.takeAt(0).widget()
            if w:
                w.deleteLater()
        by_sec: dict[int, list] = {}
        for r in self.rows:
            by_sec.setdefault(r["section_id"], []).append(r)
        shown = 0
        for sid, rs in by_sec.items():
            s = P.summarize(rs)
            if s["hours"] <= 0:
                continue
            card = QFrame()
            card.setObjectName("Card")
            v = QVBoxLayout(card)
            v.setContentsMargins(8, 6, 8, 6)
            late = s["late"] > 0
            dn = DonutChart(rs[0]["section"], s["pct_done"] or 0,
                            f"{s['done']:g} من {s['hours']:g} سا" + (f" · {s['late']} متأخرة" if late else ""),
                            color=theme.CURRENT["bad"] if late else None, size=112)
            v.addWidget(dn, 0, Qt.AlignCenter)
            self.donut_row.addWidget(card)
            shown += 1
            if shown >= 40:
                break
        if not shown:
            lab = QLabel("لا يوجد مقرر محدد بعد؛ النسب تظهر بمجرد إدخال الحجم الساعي المقرر للمواد.")
            lab.setObjectName("Muted")
            self.donut_row.addWidget(lab)
        self.donut_row.addStretch()

    def _fill_table(self):
        t = self.table
        bad, ok, warn = QColor(theme.CURRENT["bad"]), QColor(theme.CURRENT["ok"]), QColor(theme.CURRENT["warn"])
        t.setSortingEnabled(False)
        t.setUpdatesEnabled(False)
        t.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            items = [QTableWidgetItem(r["section"]), QTableWidgetItem(r["subject"]),
                     QTableWidgetItem(r["phase_label"] + ("" if r["from_timeline"] else " (بلا مخطط)")),
                     _Num(r["hours"]), _Num(r["done"]), _Num(r["remaining"]), _Num(r["pct_done"], "%"),
                     _Num(r["expected"]), _Num(r["pct_exec"], "%"),
                     _Num(r["delta"]), _Num(r["per_week"]), _Num(r["planned"]), _Num(r["unrecorded"] or None),
                     _Num(r["weeks_left"])]
            items[0].setToolTip(r["section_name"])
            items[0].setData(Qt.UserRole, i)
            items[3].setToolTip("انقر مرتين لتعديل المقرر")
            if r.get("adjusted"):
                items[4].setToolTip("فيه تصحيح يدوي للحجم الساعي الأسبوعي")
                items[4].setText(items[4].text() + " ✎")
            if not r["hours"]:
                items[3].setForeground(warn)
            if r["delta"] is not None:
                items[9].setForeground(bad if r["late"] else ok)
                items[9].setText(("تأخر " if r["late"] else "تقدم ") + f"{abs(r['delta']):g} سا"
                                 if abs(r["delta"]) >= 0.05 else "في الموعد")
            if r["late"]:
                for k in (1, 8):
                    items[k].setForeground(bad)
            if r["unrecorded"]:
                items[12].setForeground(warn)
                items[12].setToolTip("حصص سابقة ما زالت «مبرمجة»: سجّلها منجزة أو مؤجلة")
            for j, it in enumerate(items):
                t.setItem(i, j, it)
        t.setSortingEnabled(True)
        if not getattr(self, "_sized", False) and self.rows:
            t.resizeColumnsToContents()
            if t.columnWidth(1) > 320:
                t.setColumnWidth(1, 320)
            self._sized = True
        t.setUpdatesEnabled(True)
        self._apply_filter()

    def _apply_filter(self):
        txt = self.search.text().strip()
        for i in range(self.table.rowCount()):
            idx = self.table.item(i, 0).data(Qt.UserRole)
            r = self.rows[idx]
            hide = bool(txt and txt not in r["subject"]) or (self.only_late.isChecked() and not r["late"]) \
                or (self.only_missing.isChecked() and bool(r["hours"]))
            self.table.setRowHidden(i, bool(hide))

    def _row(self, table_row: int) -> dict | None:
        it = self.table.item(table_row, 0)
        return self.rows[it.data(Qt.UserRole)] if it else None

    def _edit_hours(self, row, col):
        if col != 3:
            return
        r = self._row(row)
        if not r or not r["level_id"]:
            return
        self._set_hours(r, per_specialty=True)

    def _set_hours(self, r, per_specialty: bool):
        scope = "هذا الاختصاص" if per_specialty else "كل اختصاصات الطور"
        v, ok = QInputDialog.getDouble(self, "المقرر", f"الحجم الساعي المقرر لمادة «{r['subject']}»\n"
                                       f"المرحلة: {r['phase_label']} — {scope} ({r['level']})",
                                       r["hours"] or 0, 0, 5000, 1)
        if ok:
            P.set_hours(self.ctx.db, r["level_id"], r["specialty_id"] if per_specialty else None, r["subject_id"],
                        r["phase"], v)
            self.ctx.changed("curriculum")

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        if not it:
            return
        r = self._row(it.row())
        if not r:
            return
        m = QMenu(self)
        m.addAction(icon("mdi6.pencil"), "تعديل المقرر لهذا الاختصاص", lambda: self._set_hours(r, True))
        m.addAction(icon("mdi6.pencil-box-multiple-outline"), "تعديل المقرر لكل اختصاصات الطور",
                    lambda: self._set_hours(r, False))
        m.addAction(icon("mdi6.table-clock"), "الحجم الساعي الأسبوعي لهذه المادة",
                    lambda: (self.tabs.setCurrentWidget(self.weekly), self.weekly.search.setText(r["subject"])))
        m.addAction(icon("mdi6.table-large"), "فتح القسم في الجدول العام",
                    lambda: self.ctx.navigate.emit("master", ("section", r["section_id"])))
        m.exec(self.table.viewport().mapToGlobal(pos))
