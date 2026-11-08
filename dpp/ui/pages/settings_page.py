"""الإعدادات: المؤسسة، ساعات العمل، الجدولة، المظهر، النسخ الاحتياطي، الحساب، سجل العمليات."""
from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import QTime, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTimeEdit, QVBoxLayout, QWidget)

from ...db.database import default_data_dir
from ...services import backup as B
from ..context import AppContext
from ..widgets import confirm, error, icon, info, page_title


def _t(m: int) -> QTime:
    return QTime(m // 60, m % 60)


def _m(t: QTimeEdit) -> int:
    return t.time().hour() * 60 + t.time().minute()


class SettingsPage(QWidget):
    theme_changed = Signal(str)
    style_changed = Signal(str)
    database_replaced = Signal(object)

    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("الإعدادات"))
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general(), icon("mdi6.domain"), "المؤسسة والوقت")
        self.tabs.addTab(self._backup(), icon("mdi6.backup-restore"), "النسخ الاحتياطي")
        from .settings_more import GridSettings, PrintSettings, SchedulingSettings, SoundSettings, _scroll
        self.tabs.addTab(PrintSettings(ctx), icon("mdi6.printer-settings"), "الطباعة ومحرر الأوراق")
        self.tabs.addTab(SchedulingSettings(ctx), icon("mdi6.calendar-cursor"), "البرمجة والتعارضات")
        self.grid_settings = GridSettings(ctx)
        self.tabs.addTab(_scroll(self.grid_settings), icon("mdi6.table-cog"), "الجدول العام")
        self.tabs.addTab(SoundSettings(ctx), icon("mdi6.volume-high"), "الأصوات")
        self.tabs.addTab(self._account(), icon("mdi6.account-lock-outline"), "الحساب")
        self.tabs.addTab(self._audit(), icon("mdi6.history"), "سجل العمليات")
        lay.addWidget(self.tabs, 1)

    # ------------------------------------------------------------------
    def _general(self):
        db = self.ctx.db
        w = QWidget()
        v = QVBoxLayout(w)
        g1 = QGroupBox("معلومات المؤسسة (نصوص ورقة البرنامج الرسمية في تبويب «الطباعة والقالب الرسمي»)")
        f = QFormLayout(g1)
        self.inst = QLineEdit(db.get_setting("institution_name"))
        self.inst_short = QLineEdit(db.get_setting("institution_short"))
        self.inst_addr = QLineEdit(db.get_setting("institution_address"))
        lr = QHBoxLayout()
        self.logo_lbl = QLabel()
        self._show_logo()
        lb = QPushButton("اختيار الشعار…")
        lb.clicked.connect(self.pick_logo)
        lr.addWidget(self.logo_lbl)
        lr.addWidget(lb)
        lr.addStretch()
        lw = QWidget()
        lw.setLayout(lr)
        f.addRow("اسم المؤسسة", self.inst)
        f.addRow("الاختصار", self.inst_short)
        f.addRow("العنوان / المعلومات الرسمية", self.inst_addr)
        f.addRow("الشعار", lw)
        v.addWidget(g1)
        g2 = QGroupBox("اليوم الدراسي (يبدأ الأسبوع يوم الأحد)")
        f2 = QFormLayout(g2)
        self.ds = QTimeEdit(_t(db.get_int("day_start")))
        self.de = QTimeEdit(_t(db.get_int("day_end")))
        self.ls = QTimeEdit(_t(db.get_int("lunch_start")))
        self.le = QTimeEdit(_t(db.get_int("lunch_end")))
        for t in (self.ds, self.de, self.ls, self.le):
            t.setDisplayFormat("HH:mm")
        self.slot = QComboBox()
        for m in (15, 30, 60):
            self.slot.addItem(f"{m} دقيقة", m)
        self.slot.setCurrentIndex(self.slot.findData(db.get_int("slot_minutes")))
        f2.addRow("بداية اليوم", self.ds)
        f2.addRow("نهاية اليوم", self.de)
        f2.addRow("بداية استراحة الغداء", self.ls)
        f2.addRow("نهاية استراحة الغداء", self.le)
        f2.addRow("دقة الشبكة الزمنية", self.slot)
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import QDateEdit
        self.y_start = QDateEdit()
        self.y_start.setCalendarPopup(True)
        self.y_start.setDisplayFormat("dd/MM/yyyy")
        self.y_start.setDate(QDate.fromString(db.get_setting("week1_start", "2026-09-13") or "2026-09-13", "yyyy-MM-dd"))
        self.y_start.setToolTip("الأسبوع الأول من السنة الدراسية: منه تُحسب أرقام الأسابيع («الأسبوع الثامن» في الطباعة)")
        f2.addRow("بداية السنة الدراسية (الأسبوع الأول)", self.y_start)
        v.addWidget(g2)
        g3 = QGroupBox("المظهر")
        f3 = QFormLayout(g3)
        self.theme = QComboBox()
        from .. import theme as TH
        for k, lab in TH.THEME_MODES:
            self.theme.addItem(lab, k)
        self.theme.setCurrentIndex(max(0, self.theme.findData(db.get_setting("theme", "style"))))
        self.theme.currentIndexChanged.connect(lambda _: (db.set_setting("theme", self.theme.currentData()),
                                                          self.theme_changed.emit(self.theme.currentData())))
        f3.addRow("وضع الألوان", self.theme)
        from ..shell import STYLES, normalize_style
        self.ui_style = QComboBox()
        for k, lab in STYLES:
            self.ui_style.addItem(lab, k)
        self.ui_style.setCurrentIndex(max(0, self.ui_style.findData(normalize_style(db.get_setting("ui_style", "ops")))))
        self.ui_style.currentIndexChanged.connect(lambda _: self.style_changed.emit(self.ui_style.currentData()))
        f3.addRow("الواجهة (أ / ب / ج)", self.ui_style)
        self.ui_font = QComboBox()
        for k, lab in TH.FONTS:
            self.ui_font.addItem(lab, k)
        self.ui_font.setCurrentIndex(max(0, self.ui_font.findData(db.get_setting("ui_font", "Almarai"))))

        def _font(_=None):
            db.set_setting("ui_font", self.ui_font.currentData())
            from PySide6.QtWidgets import QApplication
            QApplication.instance().setFont(TH.app_font(self.ui_font.currentData()))
            self.theme_changed.emit(db.get_setting("theme", "style"))
        self.ui_font.currentIndexChanged.connect(_font)
        f3.addRow("خط الواجهة", self.ui_font)
        f3.addRow("اللغة", QLabel("العربية (مع عرض الأسماء والاختصارات الفرنسية)"))
        v.addWidget(g3)
        save = QPushButton(icon("mdi6.content-save"), "حفظ الإعدادات")
        save.setObjectName("Primary")
        save.clicked.connect(self.save_general)
        v.addWidget(save)
        v.addStretch()
        return w

    def _show_logo(self):
        p = self.ctx.db.get_setting("institution_logo")
        if p and Path(p).is_file():
            self.logo_lbl.setPixmap(QPixmap(p).scaledToHeight(48))
        else:
            self.logo_lbl.setText("لا يوجد شعار")

    def pick_logo(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختيار الشعار", "", "صور (*.png *.jpg *.jpeg *.bmp)")
        if not path:
            return
        dst = default_data_dir() / "files"
        dst.mkdir(parents=True, exist_ok=True)
        target = dst / ("logo" + Path(path).suffix.lower())
        shutil.copyfile(path, target)
        self.ctx.db.set_setting("institution_logo", str(target))
        self._show_logo()

    def save_general(self):
        db = self.ctx.db
        ds, de, ls, le = _m(self.ds), _m(self.de), _m(self.ls), _m(self.le)
        if de <= ds:
            error(self, "نهاية اليوم يجب أن تكون بعد بدايته.")
            return
        if ls and le and not (ds <= ls < le <= de):
            error(self, "استراحة الغداء يجب أن تقع داخل اليوم الدراسي.")
            return
        for k, val in [("institution_name", self.inst.text()), ("institution_short", self.inst_short.text()),
                       ("institution_address", self.inst_addr.text()), ("day_start", ds), ("day_end", de),
                       ("lunch_start", ls), ("lunch_end", le), ("slot_minutes", self.slot.currentData()),
                       ("week1_start", self.y_start.date().toString("yyyy-MM-dd"))]:
            db.set_setting(k, val)
        db.log("تعديل الإعدادات", "settings")
        self.ctx.changed("*")
        info(self, "تم حفظ الإعدادات.")

    # ------------------------------------------------------------------
    def _backup(self):
        db = self.ctx.db
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("إعدادات النسخ")
        f = QFormLayout(g)
        dr = QHBoxLayout()
        self.bdir = QLineEdit(str(B.backup_dir(db)))
        bb = QPushButton("تغيير…")
        bb.clicked.connect(self.pick_dir)
        dr.addWidget(self.bdir)
        dr.addWidget(bb)
        dw = QWidget()
        dw.setLayout(dr)
        self.keep = QSpinBox()
        self.keep.setRange(1, 200)
        self.keep.setValue(db.get_int("backup_keep"))
        self.auto = QComboBox()
        self.auto.addItem("نسخة تلقائية يومية عند التشغيل والإغلاق", "1")
        self.auto.addItem("معطل", "0")
        self.auto.setCurrentIndex(self.auto.findData(db.get_setting("backup_auto")))
        f.addRow("مجلد النسخ (مستقل عن البرنامج)", dw)
        f.addRow("عدد النسخ المحتفظ بها", self.keep)
        f.addRow("النسخ التلقائي", self.auto)
        sv = QPushButton("حفظ")
        sv.clicked.connect(self.save_backup_settings)
        f.addRow("", sv)
        v.addWidget(g)
        row = QHBoxLayout()
        now = QPushButton(icon("mdi6.content-save-move-outline"), "نسخة احتياطية الآن")
        now.setObjectName("Primary")
        now.clicked.connect(self.backup_now)
        rest = QPushButton(icon("mdi6.backup-restore"), "استعادة النسخة المحددة")
        rest.clicked.connect(self.restore_selected)
        other = QPushButton(icon("mdi6.folder-open-outline"), "استعادة من ملف…")
        other.clicked.connect(self.restore_file)
        for b in (now, rest, other):
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        self.btable = QTableWidget(0, 4)
        self.btable.setHorizontalHeaderLabels(["التاريخ", "الوصف", "الحالة", "الملف"])
        self.btable.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.btable.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.btable.verticalHeader().setVisible(False)
        self.btable.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.btable.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.btable, 1)
        self.refresh_backups()
        return w

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "مجلد النسخ الاحتياطية", self.bdir.text())
        if d:
            self.bdir.setText(d)

    def save_backup_settings(self):
        db = self.ctx.db
        db.set_setting("backup_dir", self.bdir.text())
        db.set_setting("backup_keep", self.keep.value())
        db.set_setting("backup_auto", self.auto.currentData())
        self.refresh_backups()
        info(self, "تم الحفظ.")

    def refresh_backups(self):
        items = B.list_backups(self.ctx.db)
        self.btable.setRowCount(len(items))
        for i, b in enumerate(items):
            vals = [b.get("created", ""), b.get("label", ""), "سليمة ✓" if b["valid"] else "تالفة ✗", b["path"]]
            for j, val in enumerate(vals):
                self.btable.setItem(i, j, QTableWidgetItem(str(val)))

    def backup_now(self):
        try:
            p = B.create_backup(self.ctx.db, "يدوي")
        except Exception as e:
            error(self, f"فشل النسخ: {e}")
            return
        self.refresh_backups()
        info(self, f"تم إنشاء النسخة:\n{p}")

    def restore_selected(self):
        r = self.btable.currentRow()
        if r < 0:
            info(self, "اختر نسخة من الجدول.")
            return
        self._restore(self.btable.item(r, 3).text())

    def restore_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختيار نسخة احتياطية", str(B.backup_dir(self.ctx.db)), "DPP (*.dppbak)")
        if path:
            self._restore(path)

    def _restore(self, path):
        meta = B.inspect_backup(path)
        if not meta["valid"]:
            error(self, "هذه النسخة تالفة أو غير صالحة؛ لن تُستعمل.\n" + meta.get("check", ""))
            return
        counts = meta.get("counts", {})
        if not confirm(self, f"استعادة النسخة المؤرخة {meta.get('created')}؟\n"
                             f"تحتوي: {counts.get('sessions', '?')} حصة، {counts.get('teachers', '?')} أستاذ، "
                             f"{counts.get('formations', '?')} تكوين.\n\n"
                             "ستُنشأ نسخة من البيانات الحالية أولاً، ثم تُستبدل بالبيانات المستعادة.", danger=True):
            return
        try:
            new_db = B.restore_backup(self.ctx.db, path)
        except Exception as e:
            error(self, str(e))
            return
        self.database_replaced.emit(new_db)
        info(self, "تمت الاستعادة بنجاح وفُحصت سلامة قاعدة البيانات.")

    # ------------------------------------------------------------------
    def _account(self):
        w = QWidget()
        f = QFormLayout(w)
        self.user = QLabel(self.ctx.db.current_user)
        self.old = QLineEdit()
        self.new1 = QLineEdit()
        self.new2 = QLineEdit()
        for e in (self.old, self.new1, self.new2):
            e.setEchoMode(QLineEdit.Password)
        f.addRow("اسم المستخدم (المدير)", self.user)
        f.addRow("كلمة المرور الحالية", self.old)
        f.addRow("كلمة المرور الجديدة", self.new1)
        f.addRow("تأكيد كلمة المرور", self.new2)
        b = QPushButton("تغيير كلمة المرور")
        b.clicked.connect(self.change_pw)
        f.addRow("", b)
        f.addRow("", QLabel(f"مكان البيانات: {self.ctx.db.path}"))
        danger = QPushButton("مسح جميع البيانات والعودة إلى الصفر…")
        danger.setObjectName("Danger")
        danger.setToolTip("يحذف كل البيانات وحساب الدخول، ويُفتح البرنامج كأنه جديد (يتطلب كلمة المرور)")
        danger.clicked.connect(self.wipe_all)
        f.addRow("منطقة الخطر", danger)
        return w

    def wipe_all(self):
        from PySide6.QtWidgets import QCheckBox, QDialog, QDialogButtonBox, QVBoxLayout
        dlg = QDialog(self)
        dlg.setWindowTitle("مسح جميع البيانات")
        v = QVBoxLayout(dlg)
        warn_lbl = QLabel("<b>سيُحذف كل شيء نهائياً:</b> التكوينات والأقسام والأساتذة والمواد والجداول والحصص والمقرر "
                          "والغيابات والأحداث والإعدادات وحساب الدخول. لا تُؤخذ نسخة احتياطية، ولا يمكن الاسترجاع.<br>"
                          "بعد المسح يُعاد تشغيل البرنامج كأنه جديد وتُنشئ حساب المدير من جديد.")
        warn_lbl.setWordWrap(True)
        v.addWidget(warn_lbl)
        form = QFormLayout()
        pw = QLineEdit()
        pw.setEchoMode(QLineEdit.Password)
        form.addRow("كلمة المرور", pw)
        word = QLineEdit()
        word.setPlaceholderText("اكتب: مسح نهائي")
        form.addRow("للتأكيد اكتب «مسح نهائي»", word)
        v.addLayout(form)
        del_b = QCheckBox("حذف النسخ الاحتياطية القديمة أيضاً")
        v.addWidget(del_b)
        bb = QDialogButtonBox()
        ok = bb.addButton("مسح كل البيانات", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Danger")
        ok.setEnabled(False)
        bb.addButton("إلغاء", QDialogButtonBox.RejectRole)
        word.textChanged.connect(lambda t: ok.setEnabled(" ".join(t.split()) == "مسح نهائي" and bool(pw.text())))
        pw.textChanged.connect(lambda _t: ok.setEnabled(" ".join(word.text().split()) == "مسح نهائي" and bool(pw.text())))
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        if not self.ctx.db.check_login(self.ctx.db.current_user, pw.text()):
            error(self, "كلمة المرور غير صحيحة. لم يُمسح شيء.")
            return
        from ...services import backup as B
        try:
            B.wipe_all(self.ctx.db, pw.text(), del_b.isChecked())
        except Exception as e:
            error(self, f"تعذر المسح: {e}")
            return
        import sys
        from PySide6.QtCore import QProcess
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        app.setProperty("dpp_wiped", True)
        info(self, "مُسحت كل البيانات. سيُعاد تشغيل البرنامج الآن.")
        if getattr(sys, "frozen", False):
            QProcess.startDetached(sys.executable, sys.argv[1:])
        else:
            QProcess.startDetached(sys.executable, sys.argv)
        app.quit()

    def change_pw(self):
        if self.new1.text() != self.new2.text():
            error(self, "كلمتا المرور غير متطابقتين.")
            return
        try:
            self.ctx.db.change_password(self.ctx.db.current_user, self.old.text(), self.new1.text())
        except ValueError as e:
            error(self, str(e))
            return
        for e in (self.old, self.new1, self.new2):
            e.clear()
        info(self, "تم تغيير كلمة المرور.")

    # ------------------------------------------------------------------
    def _audit(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.audit_q = QLineEdit()
        self.audit_q.setPlaceholderText("بحث في السجل…")
        self.audit_q.textChanged.connect(self.refresh_audit)
        r = QPushButton(icon("mdi6.refresh"), "تحديث")
        r.clicked.connect(self.refresh_audit)
        row.addWidget(self.audit_q)
        row.addWidget(r)
        v.addLayout(row)
        self.audit = QTableWidget(0, 5)
        self.audit.setHorizontalHeaderLabels(["الوقت", "المستخدم", "العملية", "العنصر", "التفاصيل"])
        self.audit.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.audit.verticalHeader().setVisible(False)
        self.audit.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.audit.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.audit, 1)
        self.refresh_audit()
        return w

    def refresh_audit(self):
        q = f"%{self.audit_q.text().strip()}%"
        rows = self.ctx.db.q("""SELECT * FROM audit_log WHERE action LIKE ? OR COALESCE(details,'') LIKE ?
                                OR COALESCE(entity,'') LIKE ? ORDER BY id DESC LIMIT 1000""", (q, q, q))
        self.audit.setUpdatesEnabled(False)
        self.audit.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, val in enumerate([r["ts"], r["username"], r["action"], f"{r['entity'] or ''} {r['entity_id'] or ''}",
                                     r["details"] or ""]):
                self.audit.setItem(i, j, QTableWidgetItem(str(val)))
        if not getattr(self, "_audit_sized", False) and rows:
            for j in range(4):
                self.audit.resizeColumnToContents(j)
            self._audit_sized = True
        self.audit.setUpdatesEnabled(True)
