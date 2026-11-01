"""الإعدادات: المؤسسة، المدة الافتراضية، كلمة السر، النسخ الاحتياطي، ومسح كل البيانات."""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QVBoxLayout)

from dpp.config import backups_dir, data_dir
from dpp.services import auth, backup, reset
from dpp.services import settings as cfg
from dpp.services.timeutil import duration_choices, fmt_duration
from dpp.ui.widgets import Page, ask_form, button, card, confirm, info, warn


class SettingsPage(Page):
    title = "الإعدادات"
    subtitle = "إعدادات عامة، الأمان، النسخ الاحتياطي"

    def __init__(self, main):
        super().__init__(main)
        row = QHBoxLayout()
        # عام
        f1, l1 = card()
        l1.addWidget(self._h("عام"))
        form = QFormLayout()
        self.inst = QLineEdit()
        self.inst.setPlaceholderText("يظهر في رأس الأوراق المطبوعة")
        self.dur = QComboBox()
        for m in duration_choices():
            self.dur.addItem(fmt_duration(m), m)
        self.auto = QCheckBox("نسخة احتياطية تلقائية عند الخروج (آخر 20)")
        form.addRow("اسم المؤسسة", self.inst)
        form.addRow("المدة الافتراضية للحصة عند وضعها", self.dur)
        form.addRow(self.auto)
        l1.addLayout(form)
        l1.addWidget(button("حفظ الإعدادات", self.save_general, primary=True))
        l1.addSpacing(10)
        l1.addWidget(self._h("الأمان"))
        l1.addWidget(button("تغيير كلمة السر", self.change_password))
        l1.addStretch(1)
        row.addWidget(f1, 1)
        # النسخ الاحتياطي
        f2, l2 = card()
        l2.addWidget(self._h("النسخ الاحتياطي"))
        self.path_lbl = QLabel()
        self.path_lbl.setObjectName("Muted")
        self.path_lbl.setWordWrap(True)
        l2.addWidget(self.path_lbl)
        self.backups = QListWidget()
        l2.addWidget(self.backups, 1)
        r = QHBoxLayout()
        r.addWidget(button("نسخة الآن", self.backup_now, primary=True))
        r.addWidget(button("استعادة المحددة", self.restore_selected))
        r.addWidget(button("استعادة من ملف…", self.restore_file))
        r.addWidget(button("فتح المجلد", self.open_folder))
        l2.addLayout(r)
        row.addWidget(f2, 1)
        self.root.addLayout(row, 1)
        # منطقة الخطر
        f3, l3 = card()
        l3.addWidget(self._h("منطقة الخطر", "#DC2626"))
        t = QLabel("«مسح كل البيانات» يحذف قاعدة البيانات والنسخ الاحتياطية نهائياً ويعيد البرنامج جديداً تماماً "
                   "(لا يُحفظ شيء). يتطلب كلمة سر المسؤول.")
        t.setWordWrap(True)
        l3.addWidget(t)
        l3.addWidget(button("مسح كل البيانات…", self.wipe, danger=True))
        self.root.addWidget(f3)

    def _h(self, text, color=None) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-weight: 700; font-size: 12pt; {'color:' + color if color else ''}")
        return lbl

    def refresh(self) -> None:
        s = self.s
        self.inst.setText(cfg.get(s, "institution_name", ""))
        self.dur.setCurrentIndex(max(0, self.dur.findData(cfg.get_int(s, "default_lesson_minutes", 60))))
        self.auto.setChecked(cfg.get(s, "auto_backup", "1") == "1")
        self.path_lbl.setText(f"مجلد البيانات: {data_dir()}")
        self.backups.clear()
        for p in backup.list_backups():
            it = QListWidgetItem(f"{p.name}  ({p.stat().st_size // 1024} ك.ب)")
            it.setData(Qt.UserRole, str(p))
            self.backups.addItem(it)

    def save_general(self) -> None:
        s = self.s
        cfg.put(s, "institution_name", self.inst.text().strip())
        cfg.put(s, "default_lesson_minutes", self.dur.currentData())
        cfg.put(s, "auto_backup", "1" if self.auto.isChecked() else "0")
        self.main and self.main.status("حُفظت الإعدادات")

    def change_password(self) -> None:
        v = ask_form(self, "تغيير كلمة السر", [("old", "كلمة السر الحالية", "password"),
                                                ("new", "الجديدة", "password"), ("new2", "تأكيد الجديدة", "password")])
        if not v:
            return
        if v["new"] != v["new2"]:
            warn(self, "كلمتا السر غير متطابقتين")
            return
        try:
            auth.change_password(self.s, v["old"], v["new"])
            info(self, "تم تغيير كلمة السر")
        except ValueError as e:
            warn(self, str(e))

    def backup_now(self) -> None:
        try:
            p = backup.create_backup()
            info(self, f"حُفظت النسخة:\n{p}")
        except ValueError as e:
            warn(self, str(e))
        self.refresh()

    def _restore(self, path: str) -> None:
        if not confirm(self, "استبدال كل البيانات الحالية بهذه النسخة؟ (تُحفظ نسخة أمان من الحالية أولاً)"):
            return
        try:
            backup.restore_backup(path)
        except Exception as e:  # noqa: BLE001
            warn(self, f"تعذرت الاستعادة: {e}")
            return
        info(self, "تمت الاستعادة. سجّل الدخول من جديد.")
        if self.main:
            self.main.restart()

    def restore_selected(self) -> None:
        it = self.backups.currentItem()
        if it:
            self._restore(it.data(Qt.UserRole))

    def restore_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "نسخة احتياطية", str(backups_dir()), "SQLite (*.sqlite3 *.db)")
        if path:
            self._restore(path)

    def open_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(backups_dir())))

    def wipe(self) -> None:
        pw, ok = QInputDialog.getText(self, "مسح كل البيانات", "كلمة سر المسؤول:", QLineEdit.Password)
        if not ok:
            return
        if not auth.check_admin_password(self.s, pw):
            warn(self, "كلمة السر غير صحيحة")
            return
        word, ok = QInputDialog.getText(self, "تأكيد نهائي", "اكتب كلمة «مسح» للتأكيد. لا يمكن التراجع:")
        if not ok or word.strip() != "مسح":
            return
        reset.wipe_all(self.s, pw)
        info(self, "مُسحت كل البيانات. البرنامج الآن جديد تماماً: أنشئ حساب المسؤول.")
        if self.main:
            self.main.restart()
