"""الأساتذة والمواد: إدارة القوائم وربط الأساتذة بالاختصاصات."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QColorDialog, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLineEdit,
                               QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QTabWidget,
                               QVBoxLayout, QWidget)

from dpp.models import SUBJECT_KINDS, Specialty, Subject, Teacher
from dpp.services import catalog, structure
from dpp.services.textnorm import normalize
from dpp.ui.theme import subject_color
from dpp.ui.widgets import Page, ask_form, button, confirm


class CheckListDialog(QDialog):
    def __init__(self, title, items: list[tuple[int, str]], checked: set[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(420, 500)
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث…")
        lay.addWidget(self.search)
        self.list = QListWidget()
        for i, text in items:
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, i)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if i in checked else Qt.Unchecked)
            self.list.addItem(it)
        self.search.textChanged.connect(self._filter)
        lay.addWidget(self.list)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _filter(self, q) -> None:
        q = normalize(q)
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(q) and q not in normalize(it.text()))

    def checked(self) -> set[int]:
        return {self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked}


def _specialty_items(s):
    return [(sp.id, f"{sp.level.training.code} / {sp.level.code} / {sp.name}") for sp in s.query(Specialty).all()]


class DataPage(Page):
    title = "الأساتذة والمواد"
    subtitle = "اللقب هو ما يظهر على بطاقات الحصص؛ نوع المادة يحدد لونها"

    def __init__(self, main):
        super().__init__(main)
        self.tabs = QTabWidget()
        self.root.addWidget(self.tabs, 1)
        # المواد
        w1 = QWidget()
        l1 = QVBoxLayout(w1)
        r1 = QHBoxLayout()
        self.subj_search = QLineEdit()
        self.subj_search.setPlaceholderText("بحث…")
        self.subj_search.textChanged.connect(self.fill_subjects)
        r1.addWidget(self.subj_search)
        r1.addWidget(button("مادة جديدة", self.add_subject, primary=True))
        r1.addWidget(button("تعديل", self.edit_subject))
        r1.addWidget(button("لون…", self.color_subject))
        r1.addWidget(button("حذف", self.del_subject, danger=True))
        l1.addLayout(r1)
        self.subj = QTableWidget(0, 6)
        self.subj.setHorizontalHeaderLabels(["المادة", "الاختصار", "النوع", "النطاق", "حصص مشتركة", "رمي/ليلي"])
        self.subj.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.subj.setSelectionBehavior(QTableWidget.SelectRows)
        self.subj.setEditTriggers(QTableWidget.NoEditTriggers)
        self.subj.doubleClicked.connect(self.edit_subject)
        l1.addWidget(self.subj)
        self.tabs.addTab(w1, "المواد")
        # الأساتذة
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        r2 = QHBoxLayout()
        self.t_search = QLineEdit()
        self.t_search.setPlaceholderText("بحث…")
        self.t_search.textChanged.connect(self.fill_teachers)
        r2.addWidget(self.t_search)
        r2.addWidget(button("أستاذ جديد", self.add_teacher, primary=True))
        r2.addWidget(button("تعديل", self.edit_teacher))
        r2.addWidget(button("الاختصاصات…", self.teacher_specialties))
        r2.addWidget(button("المواد…", self.teacher_subjects))
        r2.addWidget(button("حذف", self.del_teacher, danger=True))
        l2.addLayout(r2)
        self.tt = QTableWidget(0, 5)
        self.tt.setHorizontalHeaderLabels(["اللقب", "الاسم", "الرتبة", "الاختصاصات", "المواد"])
        self.tt.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tt.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.tt.setSelectionBehavior(QTableWidget.SelectRows)
        self.tt.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tt.doubleClicked.connect(self.edit_teacher)
        l2.addWidget(self.tt)
        self.tabs.addTab(w2, "الأساتذة")

    def refresh(self) -> None:
        self.fill_subjects()
        self.fill_teachers()

    # ---------------- المواد
    def fill_subjects(self) -> None:
        q = normalize(self.subj_search.text())
        self.subj.setRowCount(0)
        for subj in catalog.subjects(self.s):
            if q and q not in normalize(subj.name):
                continue
            r = self.subj.rowCount()
            self.subj.insertRow(r)
            scope = "عامة للكل"
            if subj.specialty_id:
                sp = self.s.get(Specialty, subj.specialty_id)
                scope = f"اختصاص: {sp.name}" if sp else scope
            elif subj.level_id:
                from dpp.models import Level
                lv = self.s.get(Level, subj.level_id)
                scope = f"طور: {lv.code}" if lv else scope
            vals = [subj.name, subj.short_name, SUBJECT_KINDS.get(subj.kind, subj.kind), scope,
                    "نعم" if subj.allow_shared else "", " / ".join(x for x in (
                        "رمي" if subj.is_shooting else "", "ليلي" if subj.is_night else "") if x)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, subj.id)
                    it.setBackground(subject_color(subj))
                self.subj.setItem(r, c, it)

    def _subject(self) -> Subject | None:
        r = self.subj.currentRow()
        return self.s.get(Subject, self.subj.item(r, 0).data(Qt.UserRole)) if r >= 0 else None

    def _subject_form(self, subj: Subject | None):
        s = self.s
        levels = [(None, "— الكل —")] + [(lv.id, f"{t.code} / {lv.code}") for t in structure.trainings(s)
                                          for lv in t.levels]
        specs = [(None, "— الكل —")] + _specialty_items(s)
        return ask_form(self, "مادة", [
            ("name", "الاسم الكامل", "text", subj.name if subj else ""),
            ("short", "الاختصار", "text", subj.short_name if subj else ""),
            ("kind", "النوع", "combo", subj.kind if subj else "specialized", list(SUBJECT_KINDS.items())),
            ("level", "خاصة بطور", "combo", subj.level_id if subj else None, levels),
            ("specialty", "خاصة باختصاص (للتخصصية)", "combo", subj.specialty_id if subj else None, specs),
            ("shared", "تسمح بالحصص المشتركة (رمي/تربية بدنية/نظام منظم/محاضرات)", "check",
             subj.allow_shared if subj else False),
            ("shooting", "حصة رمي", "check", subj.is_shooting if subj else False),
            ("night", "تدريب ليلي", "check", subj.is_night if subj else False)])

    def _apply_subject(self, subj: Subject, v) -> None:
        subj.name, subj.short_name, subj.kind = v["name"], v["short"], v["kind"]
        subj.level_id, subj.specialty_id = v["level"], v["specialty"]
        subj.allow_shared, subj.is_shooting, subj.is_night = v["shared"], v["shooting"], v["night"]

    def add_subject(self) -> None:
        v = self._subject_form(None)
        if v and v["name"]:
            subj = Subject(name=v["name"])
            self._apply_subject(subj, v)
            self.s.add(subj)
            self.s.commit()
            self.fill_subjects()

    def edit_subject(self, *_) -> None:
        subj = self._subject()
        if subj:
            v = self._subject_form(subj)
            if v and v["name"]:
                self._apply_subject(subj, v)
                self.s.commit()
                self.fill_subjects()

    def color_subject(self) -> None:
        subj = self._subject()
        if subj:
            c = QColorDialog.getColor(subject_color(subj), self, "لون المادة")
            if c.isValid():
                subj.color = c.name()
                self.s.commit()
                self.fill_subjects()

    def del_subject(self) -> None:
        subj = self._subject()
        if subj and confirm(self, f"حذف المادة «{subj.name}»؟ تبقى حصصها بلا مادة."):
            self.s.delete(subj)
            self.s.commit()
            self.fill_subjects()

    # ---------------- الأساتذة
    def fill_teachers(self) -> None:
        q = normalize(self.t_search.text())
        self.tt.setRowCount(0)
        for t in catalog.teachers(self.s):
            if q and q not in normalize(f"{t.last_name} {t.first_name}"):
                continue
            r = self.tt.rowCount()
            self.tt.insertRow(r)
            vals = [t.last_name, t.first_name, t.rank, "، ".join(sp.name for sp in t.specialties),
                    "، ".join(x.name for x in t.subjects)]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c == 0:
                    it.setData(Qt.UserRole, t.id)
                self.tt.setItem(r, c, it)

    def _teacher(self) -> Teacher | None:
        r = self.tt.currentRow()
        return self.s.get(Teacher, self.tt.item(r, 0).data(Qt.UserRole)) if r >= 0 else None

    def _teacher_form(self, t: Teacher | None):
        return ask_form(self, "أستاذ", [
            ("last", "اللقب (يظهر على البطاقة)", "text", t.last_name if t else ""),
            ("first", "الاسم", "text", t.first_name if t else ""),
            ("rank", "الرتبة", "text", t.rank if t else ""),
            ("phone", "الهاتف", "text", t.phone if t else "")])

    def add_teacher(self) -> None:
        v = self._teacher_form(None)
        if v and v["last"]:
            self.s.add(Teacher(last_name=v["last"], first_name=v["first"], rank=v["rank"], phone=v["phone"]))
            self.s.commit()
            self.fill_teachers()

    def edit_teacher(self, *_) -> None:
        t = self._teacher()
        if t:
            v = self._teacher_form(t)
            if v and v["last"]:
                t.last_name, t.first_name, t.rank, t.phone = v["last"], v["first"], v["rank"], v["phone"]
                self.s.commit()
                self.fill_teachers()

    def teacher_specialties(self) -> None:
        t = self._teacher()
        if not t:
            return
        d = CheckListDialog("اختصاصات الأستاذ", _specialty_items(self.s), {sp.id for sp in t.specialties}, self)
        if d.exec():
            t.specialties = [self.s.get(Specialty, i) for i in d.checked()]
            self.s.commit()
            self.fill_teachers()

    def teacher_subjects(self) -> None:
        t = self._teacher()
        if not t:
            return
        items = [(x.id, x.name) for x in catalog.subjects(self.s)]
        d = CheckListDialog("مواد الأستاذ", items, {x.id for x in t.subjects}, self)
        if d.exec():
            t.subjects = [self.s.get(Subject, i) for i in d.checked()]
            self.s.commit()
            self.fill_teachers()

    def del_teacher(self) -> None:
        t = self._teacher()
        if t and confirm(self, f"حذف الأستاذ «{t.last_name}»؟ تبقى حصصه بلا أستاذ."):
            self.s.delete(t)
            self.s.commit()
            self.fill_teachers()
