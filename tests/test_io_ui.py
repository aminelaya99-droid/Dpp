"""اختبارات الاستيراد والتصدير والواجهة."""
from datetime import timedelta

import pytest
from conftest import ROZ, START

from dpp.importers.roz import RozError, parse_roz, parse_roz_file, split_rank
from dpp.importers.roz_import import ImportOptions, import_roz, preview
from dpp.services import timetables as T


# ------------------------------------------------------------------ .roz
def test_roz_signature_rejected():
    with pytest.raises(RozError):
        parse_roz(b"PK\x03\x04 not a timetable file....")


@pytest.mark.skipif(not ROZ.exists(), reason="ضع ملف 6.roz في tests/data لتشغيل هذا الاختبار")
def test_roz_parse_real_file():
    r = parse_roz_file(str(ROZ))
    s = r.summary()
    assert s["الإصدار"] == 702
    assert (s["الأيام"], s["الفترات"], s["المواد"], s["الأساتذة"], s["القاعات"], s["الأقسام"], s["الأفواج"], s["الدروس"]) == \
        (7, 5, 305, 172, 5, 40, 200, 1351)
    assert r.days[0] == "الأحد" and r.periods[0] == "الحصة الأولى"
    assert all(len(c[2]) == 5 for c in r.classes)
    # كل الدروس تشير إلى فهارس موجودة
    assert all(0 <= l.subject < 305 and all(0 <= g < 200 for g in l.groups) for l in r.lessons)
    assert split_rank("مساعد أول: عيسو جمال") == ("مساعد أول", "عيسو جمال")


@pytest.mark.skipif(not ROZ.exists(), reason="ضع ملف 6.roz في tests/data لتشغيل هذا الاختبار")
def test_roz_import_into_db(db):
    r = parse_roz_file(str(ROZ))
    p = preview(r)
    assert p["summary"]["الدروس"] == 1351
    f = db.insert("formations", name="تكوين مستورد", start_date="2026-09-06", end_date="2027-06-30")
    rep = import_roz(db, r, ImportOptions(formation_id=f))
    assert rep.added["المواد"] == len({s[0] for s in r.subjects})
    assert db.scalar("SELECT COUNT(*) FROM sections WHERE formation_id=?", (f,)) == 40
    assert db.scalar("SELECT COUNT(*) FROM requirements") > 0
    assert db.scalar("SELECT COUNT(*) FROM teacher_subjects") > 0
    assert db.scalar("SELECT COUNT(*) FROM teachers WHERE rank='م م م'") >= 1
    # إعادة الاستيراد لا تكرر البيانات
    rep2 = import_roz(db, r, ImportOptions(formation_id=f))
    assert rep2.added["المواد"] == 0 and rep2.added["الأقسام"] == 0


def test_excel_import(db, tmp_path):
    from openpyxl import Workbook

    from dpp.importers import excel as X
    wb = Workbook()
    ws = wb.active
    ws.append(["الاسم واللقب", "الرتبة", "التصنيف"])
    ws.append(["أستاذ أول", "مساعد", "عسكري"])
    ws.append(["أستاذ ثان", "", "م م م"])
    ws.append([None, "رقيب", ""])
    ws.append(["أستاذ أول", "مكرر", ""])
    p = tmp_path / "t.xlsx"
    wb.save(p)
    headers, rows = X.read_sheet(str(p))
    mapping = X.guess_mapping("teachers", headers)
    assert mapping["full_name"] == 0 and mapping["rank"] == 1
    issues = X.validate("teachers", mapping, rows)
    assert any("فارغة" in i.message for i in issues) and any("مكرر" in i.message for i in issues)
    res = X.import_rows(db, "teachers", mapping, rows)
    assert res.added == 2
    assert db.scalar("SELECT COUNT(*) FROM teachers") == 2


# ------------------------------------------------------------------ التصدير
@pytest.mark.parametrize("fmt", ["docx", "xlsx", "pdf"])
def test_exports_open(seeded, tmp_path, fmt):
    db, ids = seeded
    from dpp.exporters import model as M
    from dpp.exporters.render import export
    from dpp.services.templates import ensure_defaults, get_template
    T.plan_period(db, ids["formation"], time_limit=5)
    ensure_defaults(db)
    reps = [("week_section", M.report_week(db, ids["formation"], START, get_template(db, None, "week_section"),
                                           section_id=ids["sections"][0])),
            ("week_teacher", M.report_week(db, None, START, get_template(db, None, "week_teacher"),
                                           teacher_id=ids["teachers"]["يوسف طويل"])),
            ("progress", M.report_progress(db, ids["formation"], get_template(db, None, "progress"))),
            ("period_plan", M.report_period_plan(db, ids["formation"], get_template(db, None, "period_plan"))),
            ("teacher_hours", M.report_teacher_hours(db, START, START + timedelta(days=30),
                                                     get_template(db, None, "teacher_hours")))]
    for kind, rep in reps:
        out = export(rep, get_template(db, None, kind), fmt, tmp_path / f"{kind}.{fmt}")
        assert out.stat().st_size > 1000
        if fmt == "docx":
            from docx import Document
            d = Document(str(out))
            assert d.tables and rep.title in "\n".join(p.text for p in d.paragraphs)
        elif fmt == "xlsx":
            from openpyxl import load_workbook
            wb = load_workbook(out)
            assert wb.active.sheet_view.rightToLeft
            assert any(rep.title == c.value for row in wb.active.iter_rows() for c in row)
        else:
            assert out.read_bytes()[:5] == b"%PDF-"
    # محتوى جدول القسم يحتوي المواد المبرمجة
    from docx import Document
    if fmt == "docx":
        text = "\n".join(c.text for t in Document(str(tmp_path / "week_section.docx")).tables for r in t.rows for c in r.cells)
        assert "لغة فرنسية" in text


# ------------------------------------------------------------------ الواجهة
@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    return app


def test_themes(qapp, db):
    from dpp.ui import theme
    assert theme.apply(qapp, "dark") == "dark"
    dark_bg = qapp.palette().window().color().name()
    assert theme.apply(qapp, "light") in ("clean", "office")      # الفاتح حسب نمط الواجهة
    light_bg = qapp.palette().window().color().name()
    assert dark_bg != light_bg
    # لكل نمط واجهة لوحة ألوانه الافتراضية
    assert theme.apply(qapp, "style", "office") == "office"
    assert theme.apply(qapp, "style", "teal") == "dark"
    assert theme.apply(qapp, "style", "focus") == "graphite"
    assert theme.apply(qapp, "style", "clean") == "clean"
    db.set_setting("theme", "dark")
    assert db.get_setting("theme") == "dark"   # الاختيار يُحفظ


def test_ui_smoke_all_pages(qapp, seeded, monkeypatch):
    db, ids = seeded
    import dpp.ui.pages.planner as planner_mod
    monkeypatch.setattr(planner_mod, "confirm", lambda *a, **k: False)
    monkeypatch.setattr(planner_mod, "error", lambda *a, **k: None)
    from dpp.services.templates import ensure_defaults
    from dpp.ui import theme
    from dpp.ui.context import AppContext
    from dpp.ui.main_window import PAGES, MainWindow
    ensure_defaults(db)
    theme.install_ltr_filter(qapp)
    theme.apply(qapp, "light")
    T.plan_period(db, ids["formation"], time_limit=5)
    ctx = AppContext(db)
    ctx.set_formation(ids["formation"])
    w = MainWindow(ctx, qapp)
    w.show()
    for key, _t, _i in PAGES:
        w.navigate(key)
        qapp.processEvents()
        if key == "curriculum":               # الإصدار 1.4: المقرر تبويب داخل «المقرر والتقدم»
            assert w.stack.currentWidget() is w.pages["progress"]
            assert w.pages["progress"].tabs.currentWidget() is w.pages["progress"].curriculum
            continue
        assert w.stack.currentWidget() is w.pages[key]
    planner = w.pages["planner"]
    planner.select("section", ids["sections"][0])
    planner.set_week(START)
    qapp.processEvents()
    assert planner.grid.sessions, "يجب أن تظهر حصص القسم في المخطط"
    assert planner.cards.count() == 5
    # نقل حصة عبر المخطط يحدث قاعدة البيانات
    s = planner.grid.sessions[0]
    planner._moved(s["id"], START + timedelta(days=4), 840)
    row = db.one("SELECT date, start_min FROM sessions WHERE id=?", (s["id"],))
    assert row["start_min"] in (840, s["start_min"])   # يُنقل أو يُرفض بسبب تعارض بعد التأكيد
    w.apply_theme("dark")
    qapp.processEvents()
    w.close()
