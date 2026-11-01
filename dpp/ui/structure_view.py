"""شاشة التكوينات: شجرة تكوين → طور → اختصاص → فروع."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QMenu, QSpinBox, QTableWidget, QTableWidgetItem,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from dpp.models import (PHASE_KINDS, Level, Phase, Section, Specialty, Training)
from dpp.services import structure
from dpp.services.timeutil import fmt
from dpp.ui.widgets import Page, ask_form, button, confirm, warn

KIND_TRAINING, KIND_LEVEL, KIND_SPECIALTY, KIND_SECTION = "training", "level", "specialty", "section"
MODELS = {KIND_TRAINING: Training, KIND_LEVEL: Level, KIND_SPECIALTY: Specialty, KIND_SECTION: Section}


def section_progress_text(s, section) -> str:
    try:
        from dpp.services import progress
        r = progress.section_overall(s, section)
        if r is None:
            return "—"
        return f"{r['percent']:.0f}%"
    except Exception:  # noqa: BLE001
        return "—"


class StructurePage(Page):
    title = "التكوينات"
    subtitle = "شجرة التكوينات والأطوار والاختصاصات والفروع، مع الأعداد والتقدم"

    def __init__(self, main):
        super().__init__(main)
        self.add_action("إضافة", self.add_child, primary=True)
        self.add_action("تعديل", self.edit_item)
        self.add_action("حذف", self.delete_item, danger=True)
        self.add_action("المخطط الزمني", self.edit_phases)
        self.add_action("طباعة الشجرة", self.print_tree)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["الاسم", "الرمز", "الفروع", "التعداد", "التقدم", "تفاصيل"])
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit_item())
        # سحب الفروع لتغيير انتمائها
        self.tree.setDragDropMode(QAbstractItemView.InternalMove)
        self.tree.dropEvent = self._drop_event
        self.root.addWidget(self.tree, 1)

    # ---------- البناء ----------
    def refresh(self) -> None:
        expanded = self._expanded_keys()
        self.tree.clear()
        s = self.s
        s.expire_all()
        for t in structure.trainings(s):
            n, h = structure.training_stats(t)
            ti = self._item(None, KIND_TRAINING, t, t.name, t.code, n, h,
                            f"البداية {t.start_date:%d/%m/%Y} — {t.weeks_count} أسبوعاً")
            for lv in t.levels:
                a, b = structure.level_stats(lv)
                li = self._item(ti, KIND_LEVEL, lv, lv.name, lv.code, a, b,
                                f"من {fmt(lv.day_start)} إلى {fmt(lv.day_end)}، الغداء {fmt(lv.lunch_start)}"
                                + ("، توقيت ليلي" if lv.has_night else ""))
                for sp in lv.specialties:
                    secs = sp.sections
                    si = self._item(li, KIND_SPECIALTY, sp, sp.name, sp.code, len(secs),
                                    sum(x.headcount for x in secs), f"{len(sp.teachers)} أستاذ")
                    for sec in secs:
                        it = self._item(si, KIND_SECTION, sec, sec.name, sec.code, "", sec.headcount, "")
                        it.setText(4, section_progress_text(s, sec))
                        it.setFlags(it.flags() | Qt.ItemIsDragEnabled)
        self._restore(expanded)

    def _item(self, parent, kind, obj, name, code, n, h, details) -> QTreeWidgetItem:
        it = QTreeWidgetItem([name, code or "", str(n), str(h), "", details])
        it.setData(0, Qt.UserRole, (kind, obj.id))
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if kind == KIND_SPECIALTY:
            flags |= Qt.ItemIsDropEnabled
        it.setFlags(flags)
        if kind in (KIND_TRAINING, KIND_LEVEL):
            f = it.font(0)
            f.setBold(True)
            it.setFont(0, f)
        if parent is None:
            self.tree.addTopLevelItem(it)
        else:
            parent.addChild(it)
        return it

    def _expanded_keys(self) -> set:
        keys = set()

        def walk(it):
            if it.isExpanded():
                keys.add(it.data(0, Qt.UserRole))
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return keys

    def _restore(self, keys: set) -> None:
        def walk(it):
            k = it.data(0, Qt.UserRole)
            it.setExpanded(not keys or k in keys)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def selected(self):
        it = self.tree.currentItem()
        if not it:
            return None, None
        kind, oid = it.data(0, Qt.UserRole)
        return kind, self.s.get(MODELS[kind], oid)

    # ---------- العمليات ----------
    def add_child(self) -> None:
        kind, obj = self.selected()
        s = self.s
        if kind is None:
            v = ask_form(self, "تكوين جديد", [("code", "الرمز", "text"), ("name", "الاسم", "text"),
                                              ("start", "تاريخ البداية", "date", None),
                                              ("weeks", "عدد الأسابيع", "int", 36, (1, 200))])
            if v and v["code"]:
                t = Training(code=v["code"], name=v["name"] or v["code"], start_date=v["start"],
                             weeks_count=v["weeks"], order=len(structure.trainings(s)))
                t.weekend_days = [5, 6]
                s.add(t)
                s.commit()
        elif kind == KIND_TRAINING:
            v = ask_form(self, "طور/سنة جديد", [("code", "الرمز", "text"), ("name", "الاسم", "text")])
            if v and v["code"]:
                structure.add_level(s, obj, v["code"], v["name"])
        elif kind == KIND_LEVEL:
            v = ask_form(self, "اختصاص جديد", [("name", "الاسم", "text"), ("code", "الرمز", "text")])
            if v and v["name"]:
                structure.add_specialty(s, obj, v["name"], v["code"])
        elif kind in (KIND_SPECIALTY, KIND_SECTION):
            sp = obj if kind == KIND_SPECIALTY else obj.specialty
            v = ask_form(self, "فرع جديد", [("name", "الاسم", "text"), ("code", "الرمز", "text"),
                                            ("headcount", "التعداد", "int", 0, (0, 1000))])
            if v and v["name"]:
                structure.add_section(s, sp, v["name"], v["headcount"], v["code"])
        self.refresh()

    def edit_item(self) -> None:
        kind, obj = self.selected()
        if obj is None:
            return
        s = self.s
        if kind == KIND_TRAINING:
            v = ask_form(self, "تعديل التكوين", [
                ("code", "الرمز", "text", obj.code), ("name", "الاسم", "text", obj.name),
                ("cert", "اسم الشهادة", "text", obj.certificate_name),
                ("start", "تاريخ بداية الأسبوع 1 (الأحد)", "date", obj.start_date),
                ("weeks", "عدد الأسابيع", "int", obj.weeks_count, (1, 200)),
                ("weekend", "أيام العطلة الأسبوعية", "days", obj.weekend_days)])
            if v:
                obj.code, obj.name, obj.certificate_name = v["code"], v["name"], v["cert"]
                obj.start_date, obj.weeks_count = v["start"], v["weeks"]
                obj.weekend_days = v["weekend"]
        elif kind == KIND_LEVEL:
            v = ask_form(self, "تعديل الطور", [
                ("code", "الرمز", "text", obj.code), ("name", "الاسم", "text", obj.name),
                ("day_start", "بداية اليوم", "time", obj.day_start),
                ("day_end", "نهاية اليوم", "time", obj.day_end),
                ("lunch", "بداية الغداء", "time", obj.lunch_start),
                ("lunch_min", "مدة الغداء (د)", "int", obj.lunch_minutes, (0, 180)),
                ("study", "ساعات الدراسة اليومية (د)", "int", obj.study_minutes, (0, 900)),
                ("night", "توقيت ليلي", "check", obj.has_night),
                ("scope", "نطاق المقرر", "combo", obj.curriculum_scope,
                 [("phase", "لكل مرحلة"), ("training", "لكامل التكوين")])])
            if v:
                obj.code, obj.name = v["code"], v["name"]
                obj.day_start, obj.day_end, obj.lunch_start = v["day_start"], v["day_end"], v["lunch"]
                obj.lunch_minutes, obj.study_minutes = v["lunch_min"], v["study"]
                obj.has_night, obj.curriculum_scope = v["night"], v["scope"]
        elif kind == KIND_SPECIALTY:
            v = ask_form(self, "تعديل الاختصاص", [
                ("name", "الاسم", "text", obj.name), ("code", "الرمز", "text", obj.code),
                ("weeks", "مدة التكوين التخصصي (أسابيع، 0 = حسب المخطط)", "int",
                 obj.specialized_weeks or 0, (0, 100))])
            if v:
                obj.name, obj.code = v["name"], v["code"]
                obj.specialized_weeks = v["weeks"] or None
        elif kind == KIND_SECTION:
            specs = [(sp.id, f"{sp.level.code} / {sp.name}") for sp in s.query(Specialty).all()]
            v = ask_form(self, "تعديل الفرع", [
                ("name", "الاسم", "text", obj.name), ("code", "الرمز", "text", obj.code),
                ("headcount", "التعداد", "int", obj.headcount, (0, 1000)),
                ("specialty", "الاختصاص", "combo", obj.specialty_id, specs),
                ("lunch_override", "وقت غداء خاص بالفرع", "check", obj.lunch_start is not None),
                ("lunch", "بداية الغداء", "time", obj.effective_lunch_start)])
            if v:
                obj.name, obj.code, obj.headcount = v["name"], v["code"], v["headcount"]
                obj.specialty_id = v["specialty"]
                obj.lunch_start = v["lunch"] if v["lunch_override"] else None
        s.commit()
        self.refresh()

    def delete_item(self) -> None:
        kind, obj = self.selected()
        if obj is None:
            return
        if confirm(self, f"حذف «{getattr(obj, 'name', '')}» وكل ما يتبعه؟"):
            self.s.delete(obj)
            self.s.commit()
            self.refresh()

    def _drop_event(self, ev) -> None:
        target = self.tree.itemAt(ev.position().toPoint())
        src = self.tree.currentItem()
        ev.ignore()
        if not target or not src:
            return
        sk, sid = src.data(0, Qt.UserRole)
        tk, tid = target.data(0, Qt.UserRole)
        if sk != KIND_SECTION:
            return
        if tk == KIND_SECTION:
            tid = self.s.get(Section, tid).specialty_id
        elif tk != KIND_SPECIALTY:
            return
        structure.move_section(self.s, self.s.get(Section, sid), self.s.get(Specialty, tid))
        self.refresh()

    def context_menu(self, pos) -> None:
        kind, obj = self.selected()
        m = QMenu(self)
        m.addAction("إضافة", self.add_child)
        if obj is not None:
            m.addAction("تعديل", self.edit_item)
            m.addAction("حذف", self.delete_item)
        if kind == KIND_TRAINING:
            m.addAction("المخطط الزمني (المراحل)", self.edit_phases)
        if kind == KIND_SECTION and self.main:
            m.addSeparator()
            m.addAction("فتح الجدول الأسبوعي", lambda: self.main.open_page("planner", section_id=obj.id))
            m.addAction("فتح التقدم", lambda: self.main.open_page("progress", section_id=obj.id))
            m.addAction("نقل إلى اختصاص آخر…", self.move_dialog)
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def move_dialog(self) -> None:
        kind, obj = self.selected()
        if kind != KIND_SECTION:
            return
        specs = [(sp.id, f"{sp.level.training.code} / {sp.level.code} / {sp.name}")
                 for sp in self.s.query(Specialty).all()]
        v = ask_form(self, "نقل الفرع", [("sp", "الاختصاص", "combo", obj.specialty_id, specs)])
        if v:
            structure.move_section(self.s, obj, self.s.get(Specialty, v["sp"]))
            self.refresh()

    def edit_phases(self) -> None:
        kind, obj = self.selected()
        if kind == KIND_LEVEL:
            obj = obj.training
        elif kind == KIND_SPECIALTY:
            obj = obj.level.training
        elif kind == KIND_SECTION:
            obj = obj.specialty.level.training
        if not isinstance(obj, Training):
            ts = structure.trainings(self.s)
            if not ts:
                return
            obj = ts[0]
        PhasesDialog(self.s, obj, self).exec()
        self.refresh()

    def print_tree(self) -> None:
        try:
            from dpp.printing.reports import print_structure_tree
        except ImportError:
            warn(self, "وحدة الطباعة غير متاحة بعد")
            return
        print_structure_tree(self, self.s)


class PhasesDialog(QDialog):
    """تحرير المخطط الزمني (مراحل التكوين)."""

    COLS = ["الاسم", "النوع", "أسبوع البداية", "عدد الأسابيع", "الطور", "الاختصاص"]

    def __init__(self, s, training: Training, parent=None):
        super().__init__(parent)
        self.s, self.t = s, training
        self.setWindowTitle(f"المخطط الزمني — {training.name}")
        self.resize(820, 420)
        lay = QVBoxLayout(self)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(button("إضافة مرحلة", self.add_row))
        row.addWidget(button("حذف المرحلة", self.del_row, danger=True))
        row.addStretch(1)
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Save).setText("حفظ")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for p in training.phases:
            self.add_row(p)

    def _combo(self, items, value):
        c = QComboBox()
        for d, t in items:
            c.addItem(t, d)
        i = c.findData(value)
        c.setCurrentIndex(max(0, i))
        return c

    def add_row(self, p: Phase | None = None) -> None:
        if not isinstance(p, Phase):
            p = None
        r = self.table.rowCount()
        self.table.insertRow(r)
        it = QTableWidgetItem(p.name if p else "مرحلة جديدة")
        it.setData(Qt.UserRole, p.id if p else None)
        self.table.setItem(r, 0, it)
        self.table.setCellWidget(r, 1, self._combo(list(PHASE_KINDS.items()), p.kind if p else "normal"))
        for col, val in ((2, p.start_week if p else 1), (3, p.weeks_count if p else 1)):
            sp = QSpinBox()
            sp.setRange(1, 200)
            sp.setValue(val)
            self.table.setCellWidget(r, col, sp)
        lvls = [(None, "الكل")] + [(lv.id, lv.code) for lv in self.t.levels]
        self.table.setCellWidget(r, 4, self._combo(lvls, p.level_id if p else None))
        specs = [(None, "الكل")] + [(sp.id, f"{lv.code}/{sp.name}") for lv in self.t.levels
                                    for sp in lv.specialties]
        self.table.setCellWidget(r, 5, self._combo(specs, p.specialty_id if p else None))

    def del_row(self) -> None:
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)

    def save(self) -> None:
        keep = set()
        for r in range(self.table.rowCount()):
            pid = self.table.item(r, 0).data(Qt.UserRole)
            p = self.s.get(Phase, pid) if pid else Phase(training=self.t)
            p.name = self.table.item(r, 0).text()
            p.kind = self.table.cellWidget(r, 1).currentData()
            p.start_week = self.table.cellWidget(r, 2).value()
            p.weeks_count = self.table.cellWidget(r, 3).value()
            p.level_id = self.table.cellWidget(r, 4).currentData()
            p.specialty_id = self.table.cellWidget(r, 5).currentData()
            self.s.add(p)
            self.s.flush()
            keep.add(p.id)
        for p in list(self.t.phases):
            if p.id not in keep:
                self.s.delete(p)
        self.s.commit()
        self.s.refresh(self.t)
        self.accept()
