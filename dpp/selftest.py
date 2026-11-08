"""فحص ذاتي للنسخة النهائية (يعمل من EXE أيضاً):  DPP.exe --selftest

يستعمل مجلد بيانات مؤقتاً منفصلاً تماماً عن بيانات المؤسسة، ويختبر: إنشاء قاعدة البيانات،
الجدولة، الواجهة، التصدير، النسخ الاحتياطي والاستعادة، وبقاء البيانات بعد إعادة الفتح.
"""
from __future__ import annotations

import sys
import tempfile
import traceback
from pathlib import Path


def run() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dpp_selftest_"))
    report = []

    def step(name, fn):
        try:
            detail = fn()
            report.append(f"[نجح] {name}" + (f" — {detail}" if detail else ""))
            return True
        except Exception:
            report.append(f"[فشل] {name}\n{traceback.format_exc()}")
            return False

    import os
    os.environ["DPP_DATA_DIR"] = str(tmp)
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from .db.database import Database
    from .demo import seed
    from .exporters import model as M
    from .exporters.render import export
    from .services import backup as B
    from .services import timetables as T
    from .services.templates import ensure_defaults, get_template
    from .ui import theme
    from .ui.context import AppContext
    from .ui.main_window import PAGES, MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setLayoutDirection(Qt.RightToLeft)
    theme.install_ltr_filter(app)
    state = {}

    def s_db():
        db = Database(tmp / "dpp.sqlite")
        ensure_defaults(db)
        db.create_admin("admin", "selftest")
        state["db"] = db
        state["ids"] = seed(db)
        return str(db.path)

    def s_plan():
        p = T.plan_period(state["db"], state["ids"]["formation"], time_limit=10)
        if p.carried_over:
            raise RuntimeError("بقيت ساعات دون برمجة")
        return f"{p.placed} حصة"

    def s_ui():
        db = state["db"]
        theme.apply(app, "light")
        ctx = AppContext(db)
        ctx.set_formation(state["ids"]["formation"])
        w = MainWindow(ctx, app)
        w.show()
        for k, _t, _i in PAGES:
            w.navigate(k)
            app.processEvents()
        w.apply_theme("dark")
        app.processEvents()
        w.hide()
        state["win"] = w
        return f"{len(PAGES)} صفحة، فاتح وداكن"

    def s_export():
        db, ids = state["db"], state["ids"]
        tpl = get_template(db, None, "week_section")
        rep = M.report_week(db, ids["formation"], db.scalar("SELECT start_date FROM formations"), tpl,
                            section_id=ids["sections"][0])
        out = []
        for fmt in ("docx", "xlsx", "pdf"):
            p = export(rep, tpl, fmt, tmp / f"week.{fmt}")
            if p.stat().st_size < 1000:
                raise RuntimeError(f"ملف {fmt} فارغ")
            out.append(f"{fmt}:{p.stat().st_size}")
        return "، ".join(out)

    def s_asc():
        """تصدير أسبوع إلى صيغة aSc ‏(XML) — الطريق المعاكس لاستيراد ‎.roz‎."""
        from xml.etree import ElementTree as ET
        from .exporters import asc_xml as AX
        db = state["db"]
        ws = db.scalar("SELECT MIN(date) FROM sessions")
        res = AX.export_week_xml(db, ws, tmp / "asc.xml")
        root = ET.parse(tmp / "asc.xml").getroot()
        if root.tag != "timetable" or not res["card"]:
            raise RuntimeError("ملف aSc بلا بطاقات")
        return f"بطاقات:{res['card']}، دروس:{res['lesson']}، أقسام:{res['class']}"

    def s_official():
        from .exporters import official as O
        from .ui.sheet_view import SheetScene, render_to_pdf
        db, ids = state["db"], state["ids"]
        ws = db.scalar("SELECT MIN(date) FROM sessions")
        sh = O.build_section_sheet(db, ids["sections"][0], ws)
        p = render_to_pdf([SheetScene(sh)], str(tmp / "official.pdf"))
        size = (tmp / "official.pdf").stat().st_size
        if size < 2000 or not sh.cells:
            raise RuntimeError("ورقة البرنامج الرسمية فارغة")
        return f"{len(sh.cells)} خانة، PDF {size} بايت" if p else ""

    def s_backup():
        db = state["db"]
        p = B.create_backup(db, "فحص ذاتي")
        n = db.scalar("SELECT COUNT(*) FROM sessions")
        db.execute("DELETE FROM sessions")
        new = B.restore_backup(db, p)
        state["db"] = new
        if new.scalar("SELECT COUNT(*) FROM sessions") != n:
            raise RuntimeError("الاستعادة لم تُرجع البيانات")
        return f"{n} حصة مستعادة"

    def s_reopen():
        db = state["db"]
        n = db.scalar("SELECT COUNT(*) FROM sessions")
        path = db.path
        db.close()
        d2 = Database(path)
        ok = d2.scalar("SELECT COUNT(*) FROM sessions") == n and d2.check_login("admin", "selftest")
        d2.close()
        if not ok:
            raise RuntimeError("البيانات لم تُحفظ بعد إعادة الفتح")
        return "البيانات محفوظة"

    ok = all([step("إنشاء قاعدة البيانات", s_db), step("جدولة فترة كاملة", s_plan), step("الواجهة", s_ui),
              step("التصدير", s_export), step("التصدير إلى aSc", s_asc), step("الطباعة الرسمية", s_official), step("النسخ الاحتياطي والاستعادة", s_backup), step("إعادة الفتح", s_reopen)])
    text = "\n".join(report) + f"\n\nالنتيجة: {'نجاح' if ok else 'فشل'}\nمجلد الفحص: {tmp}\n"
    (tmp / "selftest_report.txt").write_text(text, encoding="utf-8")
    try:
        print(text)
    except Exception:
        pass
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "DPP — الفحص الذاتي", text)
    return 0 if ok else 1
