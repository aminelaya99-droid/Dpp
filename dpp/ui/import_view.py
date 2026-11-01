"""شاشة استيراد ملفات aSc (.roz) والرجوع للنسخة الأصلية."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QPlainTextEdit, QSpinBox, QTableWidget, QTableWidgetItem)

from dpp.importers.roz import week_number_from_filename
from dpp.models import Level, Training, Week
from dpp.services import roz_import, structure
from dpp.ui.widgets import Page, button, card, confirm, info, warn


class ImportPage(Page):
    title = "استيراد aSc"
    subtitle = "استيراد الأسابيع الفعلية من ملفات .roz مع حفظ النسخة الأصلية للرجوع إليها"

    def __init__(self, main):
        super().__init__(main)
        f, lay = card()
        form = QFormLayout()
        self.training = QComboBox()
        self.level = QComboBox()
        self.training.currentIndexChanged.connect(self._fill_levels)
        form.addRow("التكوين", self.training)
        form.addRow("الطور للفروع الجديدة", self.level)
        lay.addLayout(form)
        self.files = QTableWidget(0, 2)
        self.files.setHorizontalHeaderLabels(["الملف", "رقم الأسبوع"])
        self.files.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.files.setMaximumHeight(180)
        lay.addWidget(self.files)
        row = QHBoxLayout()
        row.addWidget(button("اختيار ملفات .roz…", self.pick))
        row.addWidget(button("استيراد", self.run, primary=True))
        row.addStretch(1)
        lay.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)
        lay.addWidget(self.log)
        self.root.addWidget(f)

        f2, lay2 = card()
        self.weeks = QTableWidget(0, 4)
        self.weeks.setHorizontalHeaderLabels(["التكوين", "الأسبوع", "الملف", "عدد الحصص"])
        self.weeks.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.weeks.setSelectionBehavior(QTableWidget.SelectRows)
        lay2.addWidget(self.weeks)
        r2 = QHBoxLayout()
        r2.addWidget(button("الرجوع للنسخة المستوردة الأصلية", self.revert, danger=True))
        r2.addStretch(1)
        lay2.addLayout(r2)
        self.root.addWidget(f2, 1)

    def refresh(self) -> None:
        cur = self.training.currentData()
        self.training.blockSignals(True)
        self.training.clear()
        for t in structure.trainings(self.s):
            self.training.addItem(f"{t.name} ({t.code})", t.id)
        i = self.training.findData(cur)
        self.training.setCurrentIndex(max(0, i))
        self.training.blockSignals(False)
        self._fill_levels()
        self.weeks.setRowCount(0)
        for w in roz_import.imported_weeks(self.s):
            r = self.weeks.rowCount()
            self.weeks.insertRow(r)
            it = QTableWidgetItem(w.training.code)
            it.setData(Qt.UserRole, w.id)
            self.weeks.setItem(r, 0, it)
            self.weeks.setItem(r, 1, QTableWidgetItem(str(w.number)))
            self.weeks.setItem(r, 2, QTableWidgetItem(w.source_file))
            self.weeks.setItem(r, 3, QTableWidgetItem(str(len(w.lessons))))

    def _fill_levels(self) -> None:
        self.level.clear()
        t = self.s.get(Training, self.training.currentData()) if self.training.currentData() else None
        for lv in (t.levels if t else []):
            self.level.addItem(lv.name, lv.id)

    def pick(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "ملفات aSc", "", "aSc (*.roz *.xml);;كل الملفات (*)")
        for p in paths:
            r = self.files.rowCount()
            self.files.insertRow(r)
            self.files.setItem(r, 0, QTableWidgetItem(p))
            sp = QSpinBox()
            sp.setRange(1, 200)
            sp.setValue(week_number_from_filename(p) or 1)
            self.files.setCellWidget(r, 1, sp)

    def run(self) -> None:
        t = self.s.get(Training, self.training.currentData())
        lv = self.s.get(Level, self.level.currentData()) if self.level.currentData() else None
        if t is None or self.files.rowCount() == 0:
            warn(self, "اختر التكوين والملفات أولاً")
            return
        for r in range(self.files.rowCount()):
            path = self.files.item(r, 0).text()
            num = self.files.cellWidget(r, 1).value()
            try:
                rep = roz_import.import_roz(self.s, t, path, num, lv)
                self.log.appendPlainText(f"✔ {Path(path).name}: {rep.summary()}")
                for w in rep.warnings[:20]:
                    self.log.appendPlainText(f"   ⚠ {w}")
            except Exception as e:  # noqa: BLE001
                self.s.rollback()
                self.log.appendPlainText(f"✘ {Path(path).name}: {e}")
        self.files.setRowCount(0)
        self.refresh()
        if self.main:
            self.main.status("اكتمل الاستيراد")

    def revert(self) -> None:
        r = self.weeks.currentRow()
        if r < 0:
            return
        w = self.s.get(Week, self.weeks.item(r, 0).data(Qt.UserRole))
        if confirm(self, f"الرجوع للنسخة الأصلية للأسبوع {w.number}؟ ستضيع كل التعديلات عليه."):
            n = roz_import.revert_week(self.s, w)
            info(self, f"أُعيدت {n} حصة من النسخة الأصلية")
            self.refresh()
