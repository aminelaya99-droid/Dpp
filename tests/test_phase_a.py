"""اختبارات المرحلة أ: الهيكل، الفترات، قواعد المشاركة والتعارض، الجدول العام، استيراد الأسابيع."""
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import ROOT, START

from dpp.services import conflicts as CF
from dpp.services import structure as ST
from dpp.services import timetables as T
from dpp.services.grid import WeekGrid
from dpp.services.periods import PeriodMap

WEEKS_DIR = Path(os.environ.get("DPP_TEST_WEEKS", ROOT / "tests" / "data" / "weeks"))
TIMELINE = Path(os.environ.get("DPP_TEST_TIMELINE", ROOT / "tests" / "data" / "timeline.xlsx"))


def test_schema_v2(db):
    assert db.scalar("SELECT value FROM meta WHERE key='schema_version'") == "8"
    assert db.scalar("SELECT COUNT(*) FROM periods WHERE profile='basic_night' AND kind='night'") == 1
    cols = {r[1] for r in db.q("PRAGMA table_info(sections)")}
    assert {"specialty_id", "cohort_id", "lunch_period", "profile"} <= cols


def test_structure_and_classification(db):
    lv = ST.ensure_structure(db)
    assert set(lv) == {"BMP2", "BMP1", "ESOC2", "ESOC1", "OF-R", "ESO-R", "I-ESO-R", "I-HDT-R"}
    assert db.scalar("SELECT COUNT(*) FROM formations") == 3
    assert ST.classify_class("ضباط الصف المتربصين العاملين (أ م ع د 2:كتابة الضبط)") == "BMP2"
    assert ST.classify_class("طلبة ضباط الصف المتعاقدين سنة أولى(سرية ثانية)") == "ESOC1"
    assert ST.classify_class("طلبة جنود خدمة وطنبية (العصاة-خدمة وطنية)") == "I-HDT-R"
    assert ST.classify_class("طلبة ضباط (خدمة وطنية)") == "OF-R"
    assert ST.split_class("الطلبة ضباط الصف المتعاقدين سنة ثانية (مطبخ وإطعام وإيواء:فصيلة ثالثة)", "ESOC2") == \
        ("مطبخ وإطعام وإيواء", "فصيلة ثالثة")
    # المشاركة: الرمي والتربية البدنية والنظام المنظم والمحاضرات فقط
    for n in ("رمي الصيانة", "تعليم الرمي", "تربية بدنية عسكرية", "العدو الريفي", "نظام منظم",
              "محاضرة بعنوان: الاخطار و الكوارث في الجزائر", "محاضرات وندوات"):
        assert ST.is_shared_subject(n), n
    for n in ("لغة إنجليزية", "إعلام آلي", "نظام الخدمة في الجيش"):
        assert not ST.is_shared_subject(n), n
    assert ST.subject_category("وجبة الغذاء") == "nonteach"
    assert ST.subject_category("خدمــــــــــــــــات") == "nonteach"
    assert ST.subject_category("نظام الخدمة في الجيش") == "military"
    assert ST.subject_category("القانون الأساسي للمستخدمين العسكريين") != "nonteach"


def test_periods_profiles(db):
    lv = ST.ensure_structure(db)
    f = db.scalar("SELECT formation_id FROM levels WHERE id=?", (lv["ESOC1"],))
    s1 = db.insert("sections", formation_id=f, level_id=lv["ESOC1"], name="س1", short="E1")
    f2 = db.scalar("SELECT formation_id FROM levels WHERE id=?", (lv["BMP2"],))
    s2 = db.insert("sections", formation_id=f2, level_id=lv["BMP2"], name="ب", short="B2")
    pm = PeriodMap(db)
    assert pm.span_minutes(s1, 4, 5) == (780, 960)
    assert [p.start for p in pm.periods(s1)][3:] == [780, 870, 1020]      # 13:00، 14:30، الليلية 17:00
    assert pm.lunch(s2) == 4 and pm.lunch(s1) == 3
    assert pm.period_range(s2, 600, 780) == (2, 3)


def test_shared_vs_teacher_conflict(seeded):
    db, ids = seeded
    g1, g2 = ids["groups"][0], ids["groups"][1]
    t = ids["teachers"]["يوسف طويل"]
    eps, fr = ids["subjects"]["EPS"], ids["subjects"]["FR"]
    d = START + timedelta(days=1)
    db.execute("DELETE FROM sessions")
    tt = T.get_or_create_timetable(db, ids["formation"], d)
    a = T.create_session(db, tt, d, 480, 600, eps, t, None, [g1], force=True)
    b = T.create_session(db, tt, d, 480, 600, eps, t, None, [g2], force=True)
    assert CF.find_conflicts(db, d, d) == []          # مادة مشتركة: نفس الأستاذ مسموح
    db.execute("INSERT OR IGNORE INTO teacher_subjects VALUES (?,?)", (t, fr))
    c = T.create_session(db, tt, d, 540, 660, fr, t, None, [ids["groups"][2]], force=True)
    cs = CF.find_conflicts(db, d, d)
    assert {x.kind for x in cs} == {"teacher"} and len(cs) == 2
    CF.ignore(db, [cs[0].key])
    assert len(CF.active_conflicts(db, d, d)) == 1
    # المفتاح مبني على المحتوى: نقل الحصة يُظهر التعارض من جديد
    T.update_session(db, a, force=True, start_min=510, end_min=630)
    assert len(CF.active_conflicts(db, d, d)) == 2
    assert a and b and c


def test_grid_move_tray_undo(seeded):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    g = WeekGrid(db, START, today=START)
    assert g.cards
    c = next(iter(g.cards.values()))
    sec = c.sections[0]
    valid = g.row_validity(c.minutes, sec, lambda d, s, e: g.check_card(c, d, s, e), range(5), range(1, 6))
    target = next(((di, p) for (di, p), (ok, _m) in valid.items()
                   if ok and g.proposal(c.minutes, sec, di, p)[1:] != (c.start, c.end)), None)
    assert target, "يجب أن توجد خانة متاحة"
    d, s, e = g.proposal(c.minutes, sec, *target)
    g.move(g.cards[c.sid], d, s, e)
    assert (g.cards[c.sid].day, g.cards[c.sid].start) == (d, s)
    g.undo()
    assert (g.cards[c.sid].day, g.cards[c.sid].start) == (c.day, c.start)
    g.redo()
    assert g.cards[c.sid].start == s
    g.to_tray(g.cards[c.sid])
    assert c.sid in g.tray_cards and c.sid not in g.cards
    item = next(i for i in g.tray_items() if i.sid == c.sid)
    g.place(item, d, s, e)
    assert g.cards[c.sid].status == "planned"
    # بطاقة من الحجم الساعي المتبقي
    g.delete(c.sid)
    items = [i for i in g.tray_items() if i.requirement]
    assert items
    it = items[0]
    for (di, p), (ok, _m) in g.row_validity(it.minutes, it.section, lambda d, s, e: g.check_tray(it, d, s, e),
                                           range(5), range(1, 6)).items():
        if ok:
            sid = g.place(it, *g.proposal(it.minutes, it.section, di, p))
            assert sid in g.cards
            break
    g.undo()
    assert sid not in g.cards


def test_master_page_ui(seeded):
    from PySide6.QtWidgets import QApplication
    from dpp.ui import theme
    from dpp.ui.context import AppContext
    from dpp.ui.main_window import MainWindow
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    app = QApplication.instance() or QApplication([])
    theme.install_ltr_filter(app)
    ctx = AppContext(db)
    w = MainWindow(ctx, app)
    w.show()
    for st in ("modern", "classic", "focus", "modern"):
        w.apply_style(st, save=False)
        app.processEvents()
    page = w.show_page("master")
    page.set_week(START)
    for v in ("teachers", "rooms", "sections"):
        page.set_view(v)
        app.processEvents()
    assert page.view_grid.rows
    page.view_grid.viewport().repaint()
    c = next(iter(page.grid.cards.values()))
    page.view_grid.pick(c)
    assert page.view_grid.validity
    page.view_grid.cancel_pick()
    page.to_tray(page.grid.cards[c.sid])
    assert c.sid in page.grid.tray_cards
    page.undo()
    assert c.sid in page.grid.cards
    w.close()


@pytest.mark.skipif(not (WEEKS_DIR / "8.roz").exists(), reason="ملفات الأسابيع غير مرفقة (بيانات المؤسسة)")
def test_import_real_weeks(db):
    from dpp.importers.history import import_history
    files = {int(p.stem): str(p) for p in WEEKS_DIR.glob("*.roz") if p.stem.isdigit()}
    rep = import_history(db, files, today=date(2026, 10, 27))
    assert rep.sections == 40 and rep.sessions > 4000
    # لا تداخل داخل القسم الواحد في الملفات (البطاقات مقروءة بدقة)
    assert not [c for c in CF.find_conflicts(db, "2026-09-13", "2026-11-07") if c.kind == "group"]
    assert not CF.active_conflicts(db, "2026-09-13", "2026-11-07")    # التعارضات الأصلية متجاهلة
    # فترة الغداء: BMP2 = 4، مطبخ ESOC2 = 4
    assert db.scalar("SELECT lunch_period FROM levels WHERE code='BMP2'") == 4
    # أسبوع 7: قبل اليوم منجزة، بعده مبرمجة
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE date='2026-10-26' AND status='done'") > 0
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE date='2026-10-28' AND status='done'") == 0
    g = WeekGrid(db, "2026-11-01")
    c = next(c for c in g.cards.values() if c.kind == "teach" and not c.shareable)
    g.move(c, c.day + timedelta(days=1), c.start, c.end)
    assert g.revert_to_imported() >= 1
    assert g.cards[next(k for k in g.cards if g.cards[k].sname == c.sname and g.cards[k].start == c.start
                        and g.cards[k].day == c.day)]


@pytest.mark.skipif(not TIMELINE.exists(), reason="ملف المخطط الزمني غير مرفق")
def test_timeline(db):
    from dpp.importers.timeline import import_timeline, phase_of
    r = import_timeline(db, str(TIMELINE))
    assert r["rows"] == 9
    assert phase_of(db, "BMP2", "2026-09-13") == "reception"
    assert phase_of(db, "BMP2", "2026-09-20") == "specialized"
    assert phase_of(db, "ESOC1", "2026-09-20") == "basic"


# ---------------------------------------------------------------- الإصدار 1.2: الواجهة الجديدة
def test_free_subject_card_and_resize(seeded):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    g = WeekGrid(db, START, today=START)
    sec = ids["sections"][0]
    items = g.subject_items(sec, only_section=False, history_first=True)
    assert items and all(i.free and i.section is None for i in items)
    assert items[0].history >= items[-1].history          # المواد السابقة أولاً
    only = g.subject_items(sec, only_section=True)
    assert 0 < len(only) <= len(items)
    assert g.subject_items(sec, search=items[0].sname[:3])   # البحث
    it = items[0]
    other = ids["sections"][1]                               # تُوضع في أي قسم
    placed = None
    for di in range(5):
        for m in range(480, 900, 30):
            prop = g.proposal_at(60, other, di, m)
            if prop and not g.check_free(it, other, *prop):
                placed = prop
                break
        if placed:
            break
    assert placed
    cands = g.teacher_candidates(other, it.subject, *placed)
    assert cands and cands[0]["group"] in ("history", "qualified", "qualified_spec", "other")
    sid = g.place_free(it, other, cands[0]["id"], *placed)
    c = g.cards[sid]
    assert c.sections == [other] and c.teacher == cands[0]["id"]
    g.resize(c, c.start, c.end + 30)
    assert g.cards[sid].end == placed[2] + 30
    g.undo()
    assert g.cards[sid].end == placed[2]
    g.set_teacher(g.cards[sid], None)
    assert g.cards[sid].teacher is None


def test_all_formations_scope(db):
    from dpp.ui.context import ALL, AppContext
    ST.ensure_structure(db)
    ctx = AppContext(db)
    ctx.set_formation(ALL)
    assert ctx.all_formations and len(ctx.formation_ids()) == 3
    n_all = len(ctx.q("SELECT id FROM levels WHERE formation_id=?", (ctx.formation_id,)))
    assert n_all == 8
    fid = db.scalar("SELECT id FROM formations WHERE short='BMP'")
    ctx.set_formation(fid)
    assert not ctx.all_formations
    assert len(ctx.q("SELECT id FROM levels WHERE formation_id=?", (ctx.formation_id,))) == 2


@pytest.mark.skipif(not (WEEKS_DIR / "8.roz").exists() or not TIMELINE.exists(), reason="بيانات المؤسسة غير مرفقة")
def test_progress_vs_curriculum(db):
    from dpp.importers.history import import_history
    from dpp.importers.timeline import import_timeline
    from dpp.services import progress as P
    import_history(db, {int(p.stem): str(p) for p in WEEKS_DIR.glob("*.roz") if p.stem.isdigit()},
                   today=date(2026, 10, 27))
    import_timeline(db, str(TIMELINE))
    fids = [r[0] for r in db.q("SELECT id FROM formations")]
    today = date(2026, 10, 28)
    ph = P.current_phase(db, "OF-R", None, today)
    assert ph.kind == "basic" and ph.total == 14            # دفعة الاحتياط: 14 أسبوع دراسة
    ph1 = P.current_phase(db, "BMP1", None, date(2027, 3, 1))
    assert ph1.start == date(2027, 2, 7)                    # الدورة الثانية لـ BMP1
    rows = P.section_progress(db, fids, today)
    assert rows and all(r["pct_done"] is None for r in rows)   # بلا مقرر: «—» وليس 0%
    # سطر واحد لكل قسم × مادة (بلا تكرار حسب الأستاذ)
    assert len({(r["section_id"], r["subject_id"]) for r in rows}) == len(rows)
    r = next(x for x in rows if x["level"] == "OF-R" and x["done"] > 0)
    P.set_hours(db, r["level_id"], None, r["subject_id"], r["phase"], 30)
    r2 = next(x for x in P.section_progress(db, fids, today)
              if x["section_id"] == r["section_id"] and x["subject_id"] == r["subject_id"])
    assert r2["hours"] == 30 and r2["pct_done"] == round(r2["done"] / 30 * 100, 1)
    assert r2["expected"] == round(30 * ph.elapsed / ph.total, 2)
    assert r2["remaining"] == round(30 - r2["done"], 2) and r2["per_week"] is not None


def test_ui_all_styles_all_pages(seeded):
    from PySide6.QtWidgets import QApplication
    from dpp.ui import theme
    from dpp.ui.context import AppContext
    from dpp.ui.main_window import PAGES, MainWindow
    db, ids = seeded
    app = QApplication.instance() or QApplication([])
    ctx = AppContext(db)
    w = MainWindow(ctx, app)
    w.show()
    for st in ("office", "teal", "clean", "focus"):
        w.apply_style(st)
        app.processEvents()
        assert db.get_setting("ui_style") == st
        for k, _t, _i in PAGES:
            w.navigate(k)
            app.processEvents()
    w.apply_style("teal")
    w.toggle_side()
    assert w.modern_side.collapsed and db.get_setting("side_collapsed") == "1"
    w.toggle_side()
    path = db.path
    w.close()                                   # الإغلاق يغلق قاعدة البيانات
    # النمط يُستعاد بعد إعادة الفتح
    from dpp.db.database import Database
    db2 = Database(path)
    w2 = MainWindow(AppContext(db2), app)
    assert w2.ui_style == "teal" and theme.CURRENT_NAME == "dark"
    assert db2.scalar("SELECT COUNT(*) FROM sessions") is not None     # البيانات سليمة
    w2.close()
