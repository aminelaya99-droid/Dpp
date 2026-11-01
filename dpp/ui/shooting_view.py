"""تدريب الرمي والأسلحة: حصص الرمي، الأسلحة، الميادين، وملخص الذخيرة."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)
from sqlalchemy import select

from dpp.models import Section, ShootingRange, ShootingSession, Training, Weapon
from dpp.services import catalog, planner, shooting, structure
from dpp.services.timeutil import fmt, fmt_duration
from dpp.ui.data_view import CheckListDialog
from dpp.ui.widgets import Page, ask_form, button, confirm, info


def _table(headers, stretch=0) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    return t


def _fill(table: QTableWidget, rows: list[tuple[int, list[str]]]) -> None:
    table.setRowCount(0)
    for oid, vals in rows:
        r = table.rowCount()
        table.insertRow(r)
        for c, v in enumerate(vals):
            it = QTableWidgetItem(str(v))
            if c == 0:
                it.setData(Qt.UserRole, oid)
            table.setItem(r, c, it)


def _sel(table: QTableWidget):
    r = table.currentRow()
    return table.item(r, 0).data(Qt.UserRole) if r >= 0 else None


class ShootingPage(Page):
    title = "الرمي والأسلحة"
    subtitle = "حصص الرمي تُجدول في الجدول الأسبوعي (صبيحة أو بعض الساعات)؛ المتابعة على مستوى الأفواج"

    def __init__(self, main):
        super().__init__(main)
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        # حصص الرمي
        w = QWidget()
        v = QVBoxLayout(w)
        r = QHBoxLayout()
        self.training = QComboBox()
        self.week = QSpinBox()
        self.week.setRange(1, 200)
        self.week.setPrefix("الأسبوع ")
        r.addWidget(QLabel("جلب حصص الرمي من الجدول:"))
        r.addWidget(self.training)
        r.addWidget(self.week)
        r.addWidget(button("جلب", self.sync, primary=True))
        r.addStretch(1)
        r.addWidget(button("حصة رمي جديدة", self.add_session))
        r.addWidget(button("تعديل", self.edit_session))
        r.addWidget(button("الأفواج…", self.session_sections))
        r.addWidget(button("حذف", self.del_session, danger=True))
        v.addLayout(r)
        self.sessions = _table(["التاريخ", "الوقت", "التمرين", "السلاح", "الميدان", "المؤطر", "الأفواج",
                                "ذخيرة مبرمجة", "مستهلكة"], 2)
        self.sessions.doubleClicked.connect(self.edit_session)
        v.addWidget(self.sessions)
        self.tabs.addTab(w, "حصص الرمي")
        # الأسلحة
        w2 = QWidget()
        v2 = QVBoxLayout(w2)
        r2 = QHBoxLayout()
        r2.addStretch(1)
        r2.addWidget(button("سلاح جديد", self.add_weapon, primary=True))
        r2.addWidget(button("تعديل", self.edit_weapon))
        r2.addWidget(button("حذف", self.del_weapon, danger=True))
        v2.addLayout(r2)
        self.weapons = _table(["السلاح", "الصنف", "العيار", "العدد", "ملاحظات"], 4)
        self.weapons.doubleClicked.connect(self.edit_weapon)
        v2.addWidget(self.weapons)
        self.tabs.addTab(w2, "الأسلحة")
        # الميادين
        w3 = QWidget()
        v3 = QVBoxLayout(w3)
        r3 = QHBoxLayout()
        r3.addStretch(1)
        r3.addWidget(button("ميدان جديد", self.add_range, primary=True))
        r3.addWidget(button("تعديل", self.edit_range))
        r3.addWidget(button("حذف", self.del_range, danger=True))
        v3.addLayout(r3)
        self.ranges = _table(["الميدان", "عدد الممرات", "أقصى مسافة (م)"])
        self.ranges.doubleClicked.connect(self.edit_range)
        v3.addWidget(self.ranges)
        self.tabs.addTab(w3, "الميادين")
        # الذخيرة
        self.ammo = _table(["السلاح", "عدد الحصص", "الأفواج", "ذخيرة مبرمجة", "مستهلكة", "الفرق"])
        self.tabs.addTab(self.ammo, "ملخص الذخيرة")

    def refresh(self) -> None:
        s = self.s
        cur = self.training.currentData()
        self.training.clear()
        for t in structure.trainings(s):
            self.training.addItem(t.code, t.id)
        self.training.setCurrentIndex(max(0, self.training.findData(cur)))
        t = s.get(Training, self.training.currentData()) if self.training.currentData() else None
        if t and cur is None:
            self.week.setValue(structure.current_week_number(t))
        _fill(self.sessions, [(x.id, [x.date.strftime("%d/%m/%Y"), f"{fmt(x.start)} ({fmt_duration(x.duration)})",
                                      x.exercise, x.weapon.name if x.weapon else "", x.range.name if x.range else "",
                                      x.teacher.display_name if x.teacher else "",
                                      "، ".join(sec.name for sec in x.sections), x.ammo_planned, x.ammo_used])
                              for x in s.scalars(select(ShootingSession).order_by(ShootingSession.date.desc()))])
        _fill(self.weapons, [(x.id, [x.name, x.category, x.caliber, x.quantity, x.notes]) for x in shooting.weapons(s)])
        _fill(self.ranges, [(x.id, [x.name, x.lanes, x.max_distance])
                            for x in s.scalars(select(ShootingRange).order_by(ShootingRange.name))])
        _fill(self.ammo, [(0, [d["weapon"], d["sessions"], d["sections"], d["planned"], d["used"],
                               d["planned"] - d["used"]]) for d in shooting.ammo_summary(s)])

    # ---------------- حصص الرمي
    def sync(self) -> None:
        t = self.s.get(Training, self.training.currentData())
        w = planner.get_week(self.s, t, self.week.value(), create=False) if t else None
        if not w:
            info(self, "الأسبوع غير مبرمج")
            return
        n = shooting.sync_from_week(self.s, w)
        info(self, f"أُنشئت {n} حصة رمي من الجدول" if n else "لا توجد حصص رمي جديدة في هذا الأسبوع")
        self.refresh()

    def _session_form(self, x: ShootingSession | None):
        s = self.s
        return ask_form(self, "حصة رمي", [
            ("date", "التاريخ", "date", x.date if x else dt.date.today()),
            ("start", "البداية", "time", x.start if x else 480),
            ("duration", "المدة (د)", "int", x.duration if x else 240, (30, 600)),
            ("exercise", "التمرين", "text", x.exercise if x else ""),
            ("weapon", "السلاح", "combo", x.weapon_id if x else None, [(None, "—")] + [(w.id, w.name) for w in shooting.weapons(s)]),
            ("range", "الميدان", "combo", x.range_id if x else None,
             [(None, "—")] + [(r.id, r.name) for r in s.scalars(select(ShootingRange))]),
            ("teacher", "المؤطر", "combo", x.teacher_id if x else None,
             [(None, "—")] + [(t.id, t.display_name) for t in catalog.teachers(s)]),
            ("planned", "ذخيرة مبرمجة", "int", x.ammo_planned if x else 0, (0, 10 ** 6)),
            ("used", "ذخيرة مستهلكة", "int", x.ammo_used if x else 0, (0, 10 ** 6)),
            ("notes", "ملاحظات", "multiline", x.notes if x else "")])

    def _apply_session(self, x: ShootingSession, v) -> None:
        x.date, x.start, x.duration, x.exercise = v["date"], v["start"], v["duration"], v["exercise"]
        x.weapon_id, x.range_id, x.teacher_id = v["weapon"], v["range"], v["teacher"]
        x.ammo_planned, x.ammo_used, x.notes = v["planned"], v["used"], v["notes"]
        self.s.add(x)
        self.s.commit()

    def add_session(self) -> None:
        v = self._session_form(None)
        if v:
            self._apply_session(ShootingSession(), v)
            self.refresh()

    def edit_session(self, *_) -> None:
        x = self.s.get(ShootingSession, _sel(self.sessions)) if _sel(self.sessions) else None
        if x:
            v = self._session_form(x)
            if v:
                self._apply_session(x, v)
                self.refresh()

    def session_sections(self) -> None:
        x = self.s.get(ShootingSession, _sel(self.sessions)) if _sel(self.sessions) else None
        if not x:
            return
        items = [(sec.id, f"{sec.name} — {sec.level.code}") for sec in structure.all_sections(self.s)]
        d = CheckListDialog("الأفواج المشاركة", items, {sec.id for sec in x.sections}, self)
        if d.exec():
            x.sections = [self.s.get(Section, i) for i in d.checked()]
            self.s.commit()
            self.refresh()

    def del_session(self) -> None:
        x = self.s.get(ShootingSession, _sel(self.sessions)) if _sel(self.sessions) else None
        if x and confirm(self, "حذف حصة الرمي؟"):
            self.s.delete(x)
            self.s.commit()
            self.refresh()

    # ---------------- الأسلحة والميادين
    def _weapon_form(self, x):
        return ask_form(self, "سلاح", [("name", "الاسم", "text", x.name if x else ""),
                                       ("category", "الصنف", "text", x.category if x else ""),
                                       ("caliber", "العيار", "text", x.caliber if x else ""),
                                       ("quantity", "العدد", "int", x.quantity if x else 0, (0, 100000)),
                                       ("notes", "ملاحظات", "multiline", x.notes if x else "")])

    def add_weapon(self) -> None:
        v = self._weapon_form(None)
        if v and v["name"]:
            self.s.add(Weapon(**v))
            self.s.commit()
            self.refresh()

    def edit_weapon(self, *_) -> None:
        x = self.s.get(Weapon, _sel(self.weapons)) if _sel(self.weapons) else None
        if x:
            v = self._weapon_form(x)
            if v and v["name"]:
                for k, val in v.items():
                    setattr(x, k, val)
                self.s.commit()
                self.refresh()

    def del_weapon(self) -> None:
        x = self.s.get(Weapon, _sel(self.weapons)) if _sel(self.weapons) else None
        if x and confirm(self, f"حذف «{x.name}»؟"):
            self.s.delete(x)
            self.s.commit()
            self.refresh()

    def _range_form(self, x):
        return ask_form(self, "ميدان رمي", [("name", "الاسم", "text", x.name if x else ""),
                                            ("lanes", "عدد الممرات", "int", x.lanes if x else 10, (1, 500)),
                                            ("max_distance", "أقصى مسافة (م)", "int", x.max_distance if x else 100, (1, 5000))])

    def add_range(self) -> None:
        v = self._range_form(None)
        if v and v["name"]:
            self.s.add(ShootingRange(**v))
            self.s.commit()
            self.refresh()

    def edit_range(self, *_) -> None:
        x = self.s.get(ShootingRange, _sel(self.ranges)) if _sel(self.ranges) else None
        if x:
            v = self._range_form(x)
            if v and v["name"]:
                for k, val in v.items():
                    setattr(x, k, val)
                self.s.commit()
                self.refresh()

    def del_range(self) -> None:
        x = self.s.get(ShootingRange, _sel(self.ranges)) if _sel(self.ranges) else None
        if x and confirm(self, f"حذف «{x.name}»؟"):
            self.s.delete(x)
            self.s.commit()
            self.refresh()
