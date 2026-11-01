"""نافذة الدخول، أو إنشاء حساب المسؤول عند أول تشغيل."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QLineEdit, QVBoxLayout

from dpp import APP_TITLE
from dpp.services import auth
from dpp.ui.widgets import button


class LoginDialog(QDialog):
    def __init__(self, session, parent=None):
        super().__init__(parent)
        self.s = session
        self.first_run = not auth.has_admin(session)
        self.user = None
        self.setWindowTitle(APP_TITLE)
        self.setMinimumWidth(380)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(10)
        brand = QLabel("DPP")
        brand.setAlignment(Qt.AlignCenter)
        brand.setStyleSheet("font-size: 26pt; font-weight: 800; color: #15803D;")
        lay.addWidget(brand)
        sub = QLabel("إنشاء حساب المسؤول (أول تشغيل)" if self.first_run else "تسجيل الدخول")
        sub.setAlignment(Qt.AlignCenter)
        sub.setObjectName("PageSubtitle")
        lay.addWidget(sub)
        form = QFormLayout()
        self.user_edit = QLineEdit("admin" if self.first_run else "")
        self.pass_edit = QLineEdit()
        self.pass_edit.setEchoMode(QLineEdit.Password)
        form.addRow("اسم المستخدم", self.user_edit)
        form.addRow("كلمة السر", self.pass_edit)
        self.pass2_edit = None
        if self.first_run:
            self.pass2_edit = QLineEdit()
            self.pass2_edit.setEchoMode(QLineEdit.Password)
            form.addRow("تأكيد كلمة السر", self.pass2_edit)
        else:
            u = auth.admin(session)
            if u:
                self.user_edit.setText(u.username)
                self.pass_edit.setFocus()
        lay.addLayout(form)
        self.err = QLabel("")
        self.err.setStyleSheet("color: #DC2626;")
        lay.addWidget(self.err)
        b = button("إنشاء الحساب والدخول" if self.first_run else "دخول", self.submit, primary=True)
        b.setDefault(True)
        lay.addWidget(b)
        self.pass_edit.returnPressed.connect(self.submit)

    def submit(self) -> None:
        name, pw = self.user_edit.text(), self.pass_edit.text()
        try:
            if self.first_run:
                if pw != self.pass2_edit.text():
                    raise ValueError("كلمتا السر غير متطابقتين")
                self.user = auth.create_admin(self.s, name, pw)
            else:
                self.user = auth.authenticate(self.s, name, pw)
                if not self.user:
                    raise ValueError("اسم المستخدم أو كلمة السر غير صحيحة")
        except ValueError as e:
            self.err.setText(str(e))
            return
        self.accept()
