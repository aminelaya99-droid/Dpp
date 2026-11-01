"""الأحداث: قائمة الأحداث مع اختيار الفروع الحاضرة."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (QCheckBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHeaderView,
                               QLineEdit, QPlainTextEdit, QTableWidget, QTableWidgetItem, QTimeEdit, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)
from sqlalchemy import select

from dpp.models import DAY_NAMES, Event, Section
from dpp.services import structure
from dpp.services.timeutil import fmt
from dpp.ui.widgets import Page, confirm


class EventDialog(QDialog):
    def __init__(self, s, ev: Event | None, parent=None):
        super().__init__(parent)
        self.s, self.ev = s, ev
        self.setWindowTitle("حدث")
        self.resize(520, 640)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.title = QLineEdit(ev.title if ev else "")
        self.date = QDateEdit()
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        d = ev.date if ev else dt.date.today()
        self.date.setDate(QDate(d.year, d.month, d.day))
        self.start, self.end = QTimeEdit(), QTimeEdit()
        for w, m in ((self.start, ev.start if ev else 480), (self.end, ev.end if ev else 960)):
            w.setDisplayFormat("HH:mm")
            w.setTime(QTime(m // 60, m % 60))
        self.location = QLineEdit(ev.location if ev else "")
        self.desc = QPlainTextEdit(ev.description if ev else "")
        self.desc.setFixedHeight(60)
        self.blocks = QCheckBox("يمنع الحصص في وقته للفروع الحاضرة (يظهر كتعارض)")
        self.blocks.setChecked(ev.blocks_lessons if ev else True)
        f.addRow("العنوان", self.title)
        f.addRow("التاريخ", self.date)
        f.addRow("من", self.start)
        f.addRow("إلى", self.end)
        f.addRow("المكان", self.location)
        f.addRow("وصف", self.desc)
        f.addRow(self.blocks)
        lay.addLayout(f)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("الفروع الحاضرة")
        chosen = {x.id for x in ev.sections} if ev else set()
        for t in structure.trainings(s):
            ti = QTreeWidgetItem([t.name])
            ti.setFlags(ti.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
            for lv in t.levels:
                li = QTreeWidgetItem([lv.code])
                li.setFlags(li.flags() | Qt.ItemIsAutoTristate | Qt.ItemIsUserCheckable)
                for sp in lv.specialties:
                    for sec in sp.sections:
                        si = QTreeWidgetItem([f"{sec.name} — {sp.name}"])
                        si.setData(0, Qt.UserRole, sec.id)
                        si.setFlags(si.flags() | Qt.ItemIsUserCheckable)
                        si.setCheckState(0, Qt.Checked if sec.id in chosen else Qt.Unchecked)
                        li.addChild(si)
                if li.childCount():
                    ti.addChild(li)
            if ti.childCount():
                self.tree.addTopLevelItem(ti)
        self.tree.expandAll()
        lay.addWidget(self.tree, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def section_ids(self) -> list[int]:
        out = []

        def walk(it):
            sid = it.data(0, Qt.UserRole)
            if sid and it.checkState(0) == Qt.Checked:
                out.append(sid)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    def apply(self) -> Event:
        ev = self.ev or Event(title="")
        ev.title = self.title.text().strip() or "حدث"
        q = self.date.date()
        ev.date = dt.date(q.year(), q.month(), q.day())
        ev.start = self.start.time().hour() * 60 + self.start.time().minute()
        ev.end = self.end.time().hour() * 60 + self.end.time().minute()
        ev.location, ev.description = self.location.text().strip(), self.desc.toPlainText().strip()
        ev.blocks_lessons = self.blocks.isChecked()
        ev.sections = [self.s.get(Section, i) for i in self.section_ids()]
        self.s.add(ev)
        self.s.commit()
        return ev


class EventsPage(Page):
    title = "الأحداث"
    subtitle = "الأحداث المحفوظة مع الفروع الحاضرة؛ تظهر في المخطط الأسبوعي"

    def __init__(self, main):
        super().__init__(main)
        self.add_action("حدث جديد", self.add, primary=True)
        self.add_action("تعديل", self.edit)
        self.add_action("حذف", self.delete, danger=True)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["التاريخ", "اليوم", "الوقت", "العنوان", "المكان", "الفروع"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit)
        self.root.addWidget(self.table, 1)

    def refresh(self) -> None:
        self.table.setRowCount(0)
        for ev in self.s.scalars(select(Event).order_by(Event.date.desc(), Event.start)):
            r = self.table.rowCount()
            self.table.insertRow(r)
            day = DAY_NAMES[(ev.date.weekday() + 1) % 7]
            vals = [ev.date.strftime("%d/%m/%Y"), day, f"{fmt(ev.start)} – {fmt(ev.end)}", ev.title, ev.location,
                    "، ".join(x.name for x in ev.sections[:6]) + (f" (+{len(ev.sections) - 6})" if len(ev.sections) > 6 else "")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, ev.id)
                self.table.setItem(r, c, it)

    def _ev(self) -> Event | None:
        r = self.table.currentRow()
        return self.s.get(Event, self.table.item(r, 0).data(Qt.UserRole)) if r >= 0 else None

    def add(self) -> None:
        d = EventDialog(self.s, None, self)
        if d.exec():
            d.apply()
            self.refresh()

    def edit(self, *_) -> None:
        ev = self._ev()
        if ev:
            d = EventDialog(self.s, ev, self)
            if d.exec():
                d.apply()
                self.refresh()

    def delete(self) -> None:
        ev = self._ev()
        if ev and confirm(self, f"حذف الحدث «{ev.title}»؟"):
            self.s.delete(ev)
            self.s.commit()
            self.refresh()
