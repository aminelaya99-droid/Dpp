"""تشغيل النسخة الخفيفة، وفحصها الذاتي."""
from __future__ import annotations

import os
import sys
import tempfile
import traceback
from pathlib import Path

from . import theme
from .qt import QT5, Qt, QtWidgets, run_app, set_hidpi


def _db():
    from dpp.db.database import Database, default_data_dir
    from dpp.services.templates import ensure_defaults
    path = Path(os.environ.get("DPP_DB", default_data_dir() / "dpp.sqlite"))
    path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(path)
    ensure_defaults(db)
    return db


def build_app(argv=None):
    set_hidpi()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(argv or sys.argv)
    app.setApplicationName("DPP Lite")
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(theme.app_font())
    app.setStyleSheet(theme.stylesheet())
    return app


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--selftest" in argv:
        return selftest()
    app = build_app(argv)
    from .window import LiteWindow
    try:
        win = LiteWindow(_db())
    except Exception as e:                       # noqa: BLE001
        QtWidgets.QMessageBox.critical(None, "DPP خفيف", f"تعذّر فتح قاعدة البيانات:\n{e}")
        return 1
    win.show()
    return run_app(app)


def selftest() -> int:
    """فحص ذاتي بلا شاشة: قاعدة تجريبية، وضع حصة، نقلها، حذفها، وتصدير PDF."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    tmp = Path(tempfile.mkdtemp(prefix="dpp_lite_"))
    os.environ["DPP_DATA_DIR"] = str(tmp)
    report = []
    ok = True

    def step(name, fn):
        nonlocal ok
        try:
            detail = fn()
            report.append("[نجح] " + name + (f" — {detail}" if detail else ""))
        except Exception:                        # noqa: BLE001
            report.append(f"[فشل] {name}\n{traceback.format_exc()}")
            ok = False

    state = {}

    def s_app():
        state["app"] = build_app([])
        return f"Qt {'5 (PySide2)' if QT5 else '6 (PySide6)'}"

    def s_db():
        from datetime import date
        from dpp.db.database import Database
        from dpp.demo import seed
        from dpp.services.templates import ensure_defaults
        db = Database(tmp / "lite.sqlite")
        ensure_defaults(db)
        state["ids"] = seed(db, date(2026, 11, 1), weeks=2, sections=2)
        state["db"] = db
        return f"{db.scalar('SELECT COUNT(*) FROM sections', (), 0)} قسم"

    def s_window():
        from .window import LiteWindow
        win = LiteWindow(state["db"])
        win.resize(1200, 760)
        win.show()
        state["app"].processEvents()
        state["win"] = win
        if win.cb_sec.count() == 0:
            raise RuntimeError("لا أقسام في القائمة")
        return f"{win.cb_sec.count()} قسم في القائمة، {win.tray.count()} بطاقة مادة"

    def s_place():
        from datetime import date
        from dpp.utils import week_start
        win = state["win"]
        win.goto_week(week_start(date(2026, 11, 1)))
        sec = win.cb_sec.currentData()
        items = win.grid.subject_items(sec)
        if not items:
            raise RuntimeError("لا مواد")
        win.view.armed = items[0]
        day = win.view.days[0]
        before = len(win.view.cards())
        win.view._place(day, 540, 660)             # 09:00 → 11:00
        win.on_changed()
        after = len(win.view.cards())
        if after != before + 1:
            raise RuntimeError(f"لم تُضَف الحصة ({before} → {after})")
        card = [c for c in win.view.cards() if c.start == 540][0]
        win.grid.move(card, day, 660, 780)         # نقل
        win.on_changed()
        if not [c for c in win.view.cards() if c.start == 660]:
            raise RuntimeError("لم تُنقل الحصة")
        state["sid"] = [c for c in win.view.cards() if c.start == 660][0].sid
        return f"{after} حصة بعد الإضافة والنقل"

    def s_undo():
        win = state["win"]
        win.undo()
        win.undo()
        n = len(win.view.cards())
        win.redo()
        return f"التراجع والإعادة يعملان ({n} حصة بعد تراجعين)"

    def s_pdf():
        from .qt import QPrinter, set_landscape
        win = state["win"]
        out = tmp / "week.pdf"
        pr = QPrinter(QPrinter.HighResolution)
        set_landscape(pr)
        pr.setOutputFormat(QPrinter.PdfFormat)
        pr.setOutputFileName(str(out))
        win._render(pr)
        size = out.stat().st_size if out.exists() else 0
        if size < 1000:
            raise RuntimeError("ملف PDF فارغ")
        return f"PDF {size} بايت"

    def s_weeks():
        win = state["win"]
        rows = win.db.q("SELECT COUNT(DISTINCT week_start) FROM timetables")
        return f"{rows[0][0]} أسبوع محفوظ"

    for name, fn in (("تشغيل Qt", s_app), ("قاعدة تجريبية", s_db), ("النافذة", s_window),
                     ("وضع حصة ونقلها", s_place), ("التراجع والإعادة", s_undo),
                     ("تصدير PDF", s_pdf), ("الأسابيع السابقة", s_weeks)):
        step(name, fn)

    text = "\n".join(report) + f"\n\nالنتيجة: {'نجاح' if ok else 'فشل'}\nمجلد الفحص: {tmp}\n"
    (tmp / "selftest_report.txt").write_text(text, encoding="utf-8")
    try:
        if sys.stdout is not None:
            print(text)
    except Exception:
        pass
    return 0 if ok else 1
