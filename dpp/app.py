"""نقطة تشغيل برنامج DPP."""
from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path


def _assets() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    p = base / "dpp" / "assets"
    return p if p.exists() else Path(__file__).resolve().parent / "assets"


def main(argv=None) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    from .db.database import Database, default_data_dir
    from .services import backup as B
    from .services.templates import ensure_defaults
    from .ui import theme
    from .ui.context import AppContext
    from .ui.main_window import LoginDialog, MainWindow

    data_dir = default_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=str(data_dir / "dpp.log"), level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("DPP")
    app.setOrganizationName("DPP")
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(theme.app_font())
    theme.install_ltr_filter(app)
    icon_path = _assets() / "logo.png"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    def excepthook(et, ev, tb):
        text = "".join(traceback.format_exception(et, ev, tb))
        logging.error(text)
        QMessageBox.critical(None, "خطأ غير متوقع",
                             f"حدث خطأ غير متوقع:\n{ev}\n\nسُجلت التفاصيل التقنية في:\n{data_dir / 'dpp.log'}")
    sys.excepthook = excepthook

    db_path = Path(os.environ.get("DPP_DB", data_dir / "dpp.sqlite"))
    db = Database(db_path)
    ensure_defaults(db)
    app.setFont(theme.app_font(db.get_setting("ui_font", "Almarai")))
    from .ui.shell import normalize_style
    app.setProperty("ui_style", normalize_style(db.get_setting("ui_style", "teal")))
    app.setProperty("accent_color", db.get_setting("accent_color", theme.ACCENT_DEFAULT) or theme.ACCENT_DEFAULT)
    theme.apply(app, db.get_setting("theme", "style") if db.get_setting("theme_v2") == "1" else "style")
    if os.environ.get("DPP_AUTOLOGIN") != "1":
        login = LoginDialog(db, first_run=not db.has_users())
        if login.exec() != QDialog.Accepted:
            db.close()
            return 0
    ctx = AppContext(db)
    try:
        B.auto_backup_if_due(db)
    except Exception as e:  # لا نمنع التشغيل بسبب النسخ
        logging.warning("auto backup failed: %s", e)
    win = MainWindow(ctx, app)
    win.show()
    # خطاف اختبار: لقطة شاشة ثم إغلاق تلقائي (لا يُستعمل في التشغيل العادي)
    shot, close_ms = os.environ.get("DPP_SHOT"), os.environ.get("DPP_AUTOCLOSE_MS")
    if close_ms:
        from PySide6.QtCore import QTimer

        def _finish():
            if shot:
                win.navigate("dashboard")
                app.processEvents()
                win.grab().save(shot.replace(".png", "_dashboard.png"))
                win.navigate("master")
                app.processEvents()
                win.grab().save(shot)
            win.close()
        QTimer.singleShot(int(close_ms), _finish)
    code = app.exec()
    if os.name == "nt":   # تجنب تعليق الإغلاق بسبب خيوط المكتبات الأصلية
        import ctypes
        ctypes.windll.kernel32.TerminateProcess(ctypes.windll.kernel32.GetCurrentProcess(), code)
    return code


if __name__ == "__main__":
    sys.exit(main())
