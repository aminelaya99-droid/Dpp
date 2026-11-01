"""المقرر: قالب Excel، استيراد، إدخال يدوي، مراجعة المطابقات، وتنبيهات النواقص."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QListWidget,
                               QListWidgetItem, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from sqlalchemy import select

from dpp.models import SUBJECT_KINDS, Alert, CurriculumItem, Level, Phase, Specialty, Subject, Training
from dpp.services import catalog, curriculum, structure
from dpp.ui.theme import T, subject_color
from dpp.ui.widgets import Page, ask_form, button, confirm, info, warn


class MatchReviewDialog(QDialog):
    """مراجعة المطابقات المشكوك فيها بين أسماء ملف المنهاج والمواد."""

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self.s = s
        self.setWindowTitle("مراجعة المطابقات")
        self.resize(760, 460)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("لكل اسم من ملف المنهاج: اقبل المطابقة المقترحة، أو اختر مادة أخرى، أو أنشئ مادة جديدة."))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["الاسم في الملف", "المادة المطابقة", "الإجراء"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button("تطبيق", self.apply, primary=True))
        row.addWidget(button("إغلاق", self.reject))
        lay.addLayout(row)
        self.alerts = curriculum.pending_matches(s)
        subjects = catalog.subjects(s)
        import json
        for a in self.alerts:
            data = json.loads(a.payload or "{}")
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(data.get("raw", "")))
            combo = QComboBox()
            for subj in subjects:
                combo.addItem(subj.name, subj.id)
            combo.setCurrentIndex(max(0, combo.findData(data.get("subject_id"))))
            self.table.setCellWidget(r, 1, combo)
            act = QComboBox()
            act.addItem("قبول / ربط بالمادة المختارة", "accept")
            act.addItem("إنشاء مادة جديدة بالاسم الأصلي", "new")
            act.addItem("لاحقاً", "skip")
            self.table.setCellWidget(r, 2, act)

    def apply(self) -> None:
        for r, a in enumerate(self.alerts):
            act = self.table.cellWidget(r, 2).currentData()
            if act == "accept":
                subj = self.s.get(Subject, self.table.cellWidget(r, 1).currentData())
                curriculum.resolve_match(self.s, a, subject=subj)
            elif act == "new":
                curriculum.resolve_match(self.s, a, create_new=True)
        self.accept()


class CurriculumPage(Page):
    title = "المقرر"
    subtitle = "الحجم الساعي لكل مادة في كل اختصاص — لكل مرحلة أو لكامل التكوين حسب الطور"

    def __init__(self, main):
        super().__init__(main)
        self.add_action("تحميل قالب Excel", self.save_template)
        self.add_action("استيراد Excel", self.import_xlsx, primary=True)
        self.review_btn = self.add_action("مراجعة المطابقات", self.review)
        self.add_action("تدقيق النواقص", self.run_audit)
        bar = QHBoxLayout()
        self.training = QComboBox()
        self.level = QComboBox()
        self.specialty = QComboBox()
        self.training.currentIndexChanged.connect(self._fill_levels)
        self.level.currentIndexChanged.connect(self._fill_specs)
        self.specialty.currentIndexChanged.connect(self.fill_items)
        for lbl, w in (("التكوين", self.training), ("الطور", self.level), ("الاختصاص", self.specialty)):
            bar.addWidget(QLabel(lbl))
            w.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(button("إضافة مادة للمقرر", self.add_item))
        bar.addWidget(button("تعديل", self.edit_item))
        bar.addWidget(button("حذف", self.del_item, danger=True))
        self.root.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["المادة", "النوع", "المرحلة", "الحجم الساعي", "الاسم في الملف"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_item)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(self.table)
        self.total = QLabel()
        self.total.setObjectName("Muted")
        lv.addWidget(self.total)
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        t = QLabel("التنبيهات")
        t.setStyleSheet("font-weight: 700;")
        rv.addWidget(t)
        self.alerts = QListWidget()
        self.alerts.setWordWrap(True)
        rv.addWidget(self.alerts, 1)
        r = QHBoxLayout()
        r.addWidget(button("تمت المعالجة", self.resolve_alert))
        r.addWidget(button("مسح المعالَجة", self.clear_resolved))
        rv.addLayout(r)
        split.addWidget(right)
        split.addWidget(left)
        split.setSizes([360, 900])
        self.root.addWidget(split, 1)

    # ------------------------------------------------------------ تعبئة
    def refresh(self) -> None:
        cur = self.training.currentData()
        self.training.blockSignals(True)
        self.training.clear()
        for t in structure.trainings(self.s):
            self.training.addItem(t.name, t.id)
        self.training.setCurrentIndex(max(0, self.training.findData(cur)))
        self.training.blockSignals(False)
        self._fill_levels()
        self.fill_alerts()

    def _fill_levels(self) -> None:
        t = self.s.get(Training, self.training.currentData()) if self.training.currentData() else None
        cur = self.level.currentData()
        self.level.blockSignals(True)
        self.level.clear()
        for lv in (t.levels if t else []):
            scope = "لكل مرحلة" if lv.curriculum_scope == "phase" else "لكامل التكوين"
            self.level.addItem(f"{lv.code} ({scope})", lv.id)
        self.level.setCurrentIndex(max(0, self.level.findData(cur)))
        self.level.blockSignals(False)
        self._fill_specs()

    def _fill_specs(self) -> None:
        lv = self.s.get(Level, self.level.currentData()) if self.level.currentData() else None
        cur = self.specialty.currentData()
        self.specialty.blockSignals(True)
        self.specialty.clear()
        for sp in (lv.specialties if lv else []):
            self.specialty.addItem(sp.name, sp.id)
        self.specialty.setCurrentIndex(max(0, self.specialty.findData(cur)))
        self.specialty.blockSignals(False)
        self.fill_items()

    def fill_items(self) -> None:
        self.table.setRowCount(0)
        sid = self.specialty.currentData()
        if not sid:
            self.total.setText("اختر اختصاصاً (أضف الاختصاصات من شاشة التكوينات)")
            return
        items = curriculum.items_for(self.s, sid)
        items.sort(key=lambda i: (i.phase.start_week if i.phase else 0, i.subject.kind, i.subject.name))
        total = 0.0
        missing = 0
        for it in items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            vals = [it.subject.name, SUBJECT_KINDS.get(it.subject.kind, ""), it.phase.name if it.phase else "كامل التكوين",
                    "—" if it.hours is None else f"{it.hours:g}", it.source_name]
            for c, v in enumerate(vals):
                cell = QTableWidgetItem(v)
                if c == 0:
                    cell.setData(Qt.UserRole, it.id)
                    cell.setBackground(subject_color(it.subject))
                if c == 3 and it.hours is None:
                    cell.setBackground(QColor(T["warning_soft"]))
                self.table.setItem(r, c, cell)
            total += it.hours or 0
            missing += it.hours is None
        self.total.setText(f"{len(items)} مادة — المجموع {total:g} ساعة" + (f" — {missing} بلا حجم ساعي" if missing else ""))
        n = len(curriculum.pending_matches(self.s))
        self.review_btn.setText(f"مراجعة المطابقات ({n})" if n else "مراجعة المطابقات")

    def fill_alerts(self) -> None:
        self.alerts.clear()
        q = select(Alert).where(Alert.category.in_(("curriculum", "audit", "match"))).order_by(Alert.resolved, Alert.id.desc())
        for a in self.s.scalars(q):
            it = QListWidgetItem(("✓ " if a.resolved else "") + a.message)
            it.setData(Qt.UserRole, a.id)
            color = {"error": T["danger"], "warning": "#92400E", "info": T["info"]}.get(a.severity, T["text"])
            it.setForeground(QColor(T["muted"] if a.resolved else color))
            self.alerts.addItem(it)
        if not self.alerts.count():
            self.alerts.addItem("لا توجد تنبيهات")

    # ------------------------------------------------------------ إجراءات
    def save_template(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "حفظ القالب", "قالب_المقرر.xlsx", "Excel (*.xlsx)")
        if path:
            curriculum.write_template(self.s, path)
            info(self, "حُفظ القالب. املأه ثم استورده.")

    def import_xlsx(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "استيراد المقرر", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            res = curriculum.import_excel(self.s, path)
        except Exception as e:  # noqa: BLE001
            self.s.rollback()
            warn(self, f"تعذر الاستيراد: {e}")
            return
        curriculum.audit(self.s)
        info(self, res.summary())
        self.refresh()
        if res.doubtful:
            self.review()

    def review(self) -> None:
        if not curriculum.pending_matches(self.s):
            info(self, "لا توجد مطابقات تنتظر المراجعة")
            return
        MatchReviewDialog(self.s, self).exec()
        self.refresh()

    def run_audit(self) -> None:
        msgs = curriculum.audit(self.s)
        self.fill_alerts()
        info(self, f"{len(msgs)} تنبيه نواقص" if msgs else "لا توجد نواقص")

    def resolve_alert(self) -> None:
        it = self.alerts.currentItem()
        if it and it.data(Qt.UserRole):
            a = self.s.get(Alert, it.data(Qt.UserRole))
            a.resolved = True
            self.s.commit()
            self.fill_alerts()

    def clear_resolved(self) -> None:
        for a in self.s.scalars(select(Alert).where(Alert.resolved.is_(True))):
            self.s.delete(a)
        self.s.commit()
        self.fill_alerts()

    def _item(self) -> CurriculumItem | None:
        r = self.table.currentRow()
        return self.s.get(CurriculumItem, self.table.item(r, 0).data(Qt.UserRole)) if r >= 0 else None

    def _form(self, it: CurriculumItem | None):
        sp = self.s.get(Specialty, self.specialty.currentData())
        t = sp.level.training
        subs = [(x.id, x.name) for x in catalog.subjects(self.s)
                if not x.specialty_id or x.specialty_id == sp.id]
        phases = [(None, "كامل التكوين")] + [(p.id, p.name) for p in t.phases]
        return ask_form(self, "بند المقرر", [
            ("subject", "المادة", "combo", it.subject_id if it else None, subs),
            ("phase", "المرحلة", "combo", it.phase_id if it else None, phases),
            ("hours", "الحجم الساعي", "float", it.hours if it and it.hours else 0),
            ("all", "تطبيق على كل اختصاصات الطور (للعسكرية والعامة)", "check", False)])

    def add_item(self) -> None:
        if not self.specialty.currentData():
            return
        v = self._form(None)
        if not v:
            return
        sp = self.s.get(Specialty, self.specialty.currentData())
        targets = sp.level.specialties if v["all"] else [sp]
        for x in targets:
            it = curriculum.find_item(self.s, x.id, v["subject"], v["phase"])
            if it is None:
                self.s.add(CurriculumItem(specialty_id=x.id, subject_id=v["subject"], phase_id=v["phase"],
                                          hours=v["hours"] or None))
            else:
                it.hours = v["hours"] or None
        self.s.commit()
        self.fill_items()

    def edit_item(self, *_) -> None:
        it = self._item()
        if not it:
            return
        v = self._form(it)
        if v:
            it.subject_id, it.phase_id, it.hours = v["subject"], v["phase"], v["hours"] or None
            self.s.commit()
            self.fill_items()

    def del_item(self) -> None:
        it = self._item()
        if it and confirm(self, f"حذف «{it.subject.name}» من المقرر؟"):
            self.s.delete(it)
            self.s.commit()
            self.fill_items()
