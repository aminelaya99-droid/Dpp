"""تشغيل المساعد الذكي وحده في نافذة مستقلة:  python -m dpp.ai

يفتح نفس قاعدة بيانات البرنامج (قراءة فقط عبر الأدوات) وبنفس الإعدادات.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main(argv=None) -> int:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    from ..db.database import Database, default_data_dir
    from ..ui import theme
    from ..ui.context import AppContext
    from ..ui.pages.assistant import AssistantWindow

    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName("DPP — المساعد")
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(theme.app_font())
    theme.install_ltr_filter(app)

    path = Path(os.environ.get("DPP_DB", default_data_dir() / "dpp.sqlite"))
    if not path.exists():
        QMessageBox.critical(None, "DPP — المساعد",
                             f"لم أجد قاعدة بيانات البرنامج في:\n{path}\nشغّل DPP مرة واحدة أولاً.")
        return 2
    db = Database(path)
    theme.apply(app, db.get_setting("theme", "style") if db.get_setting("theme_v2") == "1" else "style")
    ctx = AppContext(db)
    win = AssistantWindow(ctx)
    win.show()
    code = app.exec()
    db.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
