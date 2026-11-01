"""نقطة الدخول: python -m dpp"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from dpp import APP_NAME


def create_app(argv=None) -> QApplication:
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName(APP_NAME)
    app.setLayoutDirection(Qt.RightToLeft)
    from dpp.ui.theme import app_font, stylesheet
    app.setFont(app_font(10))
    app.setStyleSheet(stylesheet())
    return app


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    smoke = "--smoke" in argv or os.environ.get("DPP_SMOKE") == "1"
    app = create_app(argv)
    from dpp.db import init_db
    s = init_db()
    from dpp.services import auth
    from dpp.ui.main_window import MainWindow

    user = None
    if smoke:
        user = auth.admin(s)
    else:
        from dpp.ui.login import LoginDialog
        dlg = LoginDialog(s)
        if dlg.exec() != QDialog.Accepted:
            return 0
        user = dlg.user
    win = MainWindow(user)
    win.show()
    if smoke:
        # إقلاع تجريبي: فتح كل الصفحات ثم الخروج
        def visit():
            for i in range(win.nav.count()):
                win.nav.setCurrentRow(i)
                app.processEvents()
            print("SMOKE-OK", flush=True)
            app.quit()
        QTimer.singleShot(50, visit)
    code = app.exec()
    try:
        from dpp.services import backup
        backup.auto_backup_on_exit(s)
    except Exception:  # noqa: BLE001 - النسخ الاحتياطي لا يجب أن يمنع الخروج
        pass
    return code
