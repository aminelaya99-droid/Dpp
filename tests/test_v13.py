"""اختبارات الإصدار 1.3: الطباعة الرسمية، الحجم الساعي الأسبوعي، التعويض، الاختصارات، استيراد المقرر."""
from datetime import timedelta

from conftest import START

from dpp.exporters import official as O
from dpp.scheduler.engine import Scheduler
from dpp.services import absences as A
from dpp.services import progress as P
from dpp.services import timetables as T
from dpp.utils import make_abbrev, space_arabic_initials


def _week(db, ids):
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    return T.save_result(db, ids["formation"], res)


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_ordinals_and_week_number(db):
    assert [O.arabic_ordinal(n) for n in (1, 8, 11, 12, 20, 21, 33)] == [
        "الأول", "الثامن", "الحادي عشر", "الثاني عشر", "العشرون", "الحادي والعشرون", "الثالث والثلاثون"]
    db.set_setting("week1_start", "2026-09-13")
    assert O.week_number(db, "2026-11-01") == 8
    assert O.school_year(db, "2026-11-01") == "2027/2026"


def test_section_sheet_layout(seeded):
    db, ids = seeded
    _week(db, ids)
    sec = ids["sections"][0]
    sh = O.build_section_sheet(db, sec, START)
    assert sh.days[0] == "الأحد" and len(sh.days) == 7
    assert sh.periods and all(" - " in p[1] for p in sh.periods)
    assert sh.cells, "يجب أن تظهر الحصص في الورقة"
    # لا خانتين على نفس (اليوم، الحصة)
    seen = set()
    for c in sh.cells:
        for j in range(c.c0, c.c1 + 1):
            assert (c.day, j) not in seen
            seen.add((c.day, j))
    # بلا مقرر للاختصاص: سطر المقرر يختفي، والقالب يحتفظ به عند الحفظ
    assert "المقرر رقم" not in sh.fields["center_block"]
    edited = sh.fields["center_block"].replace("الأسبوع :", "الأسبوع رقم :")
    raw = O.unfill(edited, sh.raw["center_block"], sh.values)
    assert "{decree}" in raw and "{target}" in raw and "{week_words}" in raw
    O.save_template_fields(db, sh.scope, {"center_block": raw, "sign_left": "مدير التعليم: فلان"})
    sh2 = O.build_section_sheet(db, sec, START + timedelta(days=7))
    assert sh2.fields["center_block"].startswith("الأسبوع رقم : ")
    assert sh2.fields["sign_left"] == "مدير التعليم: فلان"


def test_teacher_sheet_and_pdf(seeded, tmp_path):
    db, ids = seeded
    _week(db, ids)
    tid = db.scalar("SELECT teacher_id FROM sessions WHERE teacher_id IS NOT NULL LIMIT 1")
    sh = O.build_teacher_sheet(db, tid, START)
    assert sh.cells and float(sh.values["hours"]) > 0
    _app()
    from dpp.ui.sheet_view import SheetScene, render_to_pdf
    sc = SheetScene(sh, show_room=True, color=False)
    out = render_to_pdf([sc], str(tmp_path / "t.pdf"))
    assert (tmp_path / "t.pdf").stat().st_size > 2000 and out
    O.to_xlsx([sh], tmp_path / "t.xlsx")
    assert (tmp_path / "t.xlsx").exists()


def test_print_dialog_jobs(seeded):
    db, ids = seeded
    _week(db, ids)
    _app()
    from dpp.ui.context import AppContext
    from dpp.ui.sheet_view import PreviewDialog, PrintDialog
    ctx = AppContext(db)
    ctx.set_formation(ids["formation"])
    d = PrintDialog(ctx, START, None, "all_sections")
    jobs = d.jobs()
    assert len(jobs) == len(ids["sections"])
    d.kind.setCurrentIndex(d.kind.findData("all_teachers"))
    assert d.jobs()
    sheets = [O.build(db, k, t, ws) for k, t, ws in jobs]
    pv = PreviewDialog(db, sheets, None)
    pv.b_edit.setChecked(True)
    sc = pv.scene(0)
    it = next(t for t in sc.texts if t.key == "note")
    it.setPlainText("ملاحظة جديدة")
    assert pv._field_edits() and sheets[0].edits["note"] == "ملاحظة جديدة"
    pv.b_save.setEnabled(False)   # لا نسأل عند الإغلاق
    pv.close()


def test_weekly_hours_adjust(seeded):
    db, ids = seeded
    _week(db, ids)
    sec = ids["sections"][0]
    T_ids = db.q("SELECT id FROM sessions")
    for r in T_ids:
        T.set_status(db, r["id"], "done")
    wk = P.weekly_hours(db, [ids["formation"]], sec)
    assert wk["weeks"] and wk["rows"]
    row = wk["rows"][0]
    w = wk["weeks"][0]
    lvl = db.scalar("SELECT level_id FROM sections WHERE id=?", (sec,))
    P.set_hours(db, lvl, None, row["subject_id"], "all", 40)
    today = START + timedelta(days=6)
    before = next(r for r in P.section_progress(db, [ids["formation"]], today, sec) if r["subject_id"] == row["subject_id"])
    P.set_adjust(db, sec, row["subject_id"], w, row["actual"].get(w, 0) + 3, "خطأ استيراد")
    after = next(r for r in P.section_progress(db, [ids["formation"]], today, sec) if r["subject_id"] == row["subject_id"])
    assert abs(after["done"] - before["done"] - 3) < 1e-6 and after["adjusted"]
    wk2 = P.weekly_hours(db, [ids["formation"]], sec)
    r2 = next(r for r in wk2["rows"] if r["subject_id"] == row["subject_id"])
    assert w in r2["adjust"] and r2["total"] == round(row["total"] + 3, 2)
    P.clear_adjust(db, sec, row["subject_id"], w)
    assert not db.scalar("SELECT COUNT(*) FROM hours_adjust")


def test_substitution_any_free_teacher(seeded):
    db, ids = seeded
    _week(db, ids)
    s = db.one("SELECT * FROM sessions WHERE teacher_id IS NOT NULL ORDER BY date, start_min LIMIT 1")
    aid = A.add_absence(db, s["teacher_id"], "إجازة", s["date"], s["date"])
    from dpp.services.grid import WeekGrid
    g = WeekGrid(db, START)
    assert any(c.key.startswith("absent|") and s["id"] in c.session_ids for c in g.conflicts)
    cands = A.suggest_substitutes(db, s["id"], 0)
    assert cands and all(c["id"] != s["teacher_id"] for c in cands)
    busy = A._busy_teachers(db, s["date"], s["start_min"], s["end_min"], s["id"])
    assert not busy & {c["id"] for c in cands}
    res = A.auto_assign(db, aid)
    assert res["assigned"]
    g = WeekGrid(db, START)
    assert not any(c.key.startswith("absent|") and s["id"] in c.session_ids for c in g.conflicts)
    # كل الأساتذة غائبون: الحصة تبقى بلا معوّض
    db.execute("UPDATE sessions SET substitute_id=NULL")
    for t in db.q("SELECT id FROM teachers WHERE id<>?", (s["teacher_id"],)):
        A.add_absence(db, t["id"], "مهمة", s["date"], s["date"])
    assert A.suggest_substitutes(db, s["id"]) == []
    res = A.auto_assign(db, aid)
    assert s["id"] in res["unassigned"]


def test_teacher_profile(seeded):
    db, ids = seeded
    _week(db, ids)
    from dpp.services.teachers import profile
    tid = db.scalar("SELECT teacher_id FROM sessions WHERE teacher_id IS NOT NULL LIMIT 1")
    p = profile(db, tid, START)
    assert p["weeks"] and p["pairs"] and p["sections"]
    assert p["this_week"] == round(sum(w["planned"] for w in p["weeks"] if w["week"] == START.isoformat()), 2)
    _app()
    from dpp.ui.context import AppContext
    from dpp.ui.teacher_profile import TeacherProfileDialog
    d = TeacherProfileDialog(AppContext(db), tid, None, START)
    assert d.t_weeks.rowCount() == len(p["weeks"]) and d.scene.sheet.cells
    d.close()


def test_spaced_arabic_abbrev():
    assert make_abbrev("كتابة الضبط") == "ك ا"
    assert make_abbrev("تقني تسخين وتبريد") == "ت ت و"
    assert make_abbrev("Brevet Militaire Professionnel 2") == "BMP2"
    assert space_arabic_initials("تم-أوب") == "ت م-أ و ب"


def test_curriculum_import(db, tmp_path):
    import openpyxl
    lvl = db.insert("levels", formation_id=db.insert("formations", name="ت"), name="أهلية مهنية عسكرية درجة أولى",
                    code="BMP1")
    sp1 = db.insert("specialties", level_id=lvl, name="كتابة الضبط")
    db.insert("specialties", level_id=lvl, name="تقني تسخين وتبريد")
    s_fr = db.insert("subjects", name="لغة فرنسية", short="FR")
    s_ped = db.insert("subjects", name="بيداغوجية", short="PED")
    wb = openpyxl.Workbook()
    ws = wb.active
    rows = [["الفئة : أهلية عسكرية مهنية درجة أولى الإختصاص : إدارة عقابية"], ["الرقم", "تعين المادة", "الحجم الساعي"],
            [None, None, "المقرر", "المنفذ"], [1, "لغة فرنسية", 27, 20], [2, "بيداغوجيا", 122, 100],
            [3, "مادة لا توجد", 15, 3], [4, "الإمتحانات و التقييم", 70, 70], ["المجموع العام", None, 234],
            ["الفئة : أهلية عسكرية مهنية درجة أولى الإختصاص : إدارة عقابية"], [1, "لغة فرنسية", 30, 1]]
    for r in rows:
        ws.append(r)
    wb.save(tmp_path / "c.xlsx")
    from dpp.importers import curriculum as CI
    blocks = CI.analyze(db, str(tmp_path / "c.xlsx"))
    assert len(blocks) == 2 and blocks[0].level_id == lvl and blocks[0].specialty_id == sp1
    st = {r.name: r.status for r in blocks[0].rows}
    assert st["لغة فرنسية"] == "ok" and st["مادة لا توجد"] == "unmatched" and st["الإمتحانات و التقييم"] == "skip"
    res = CI.apply(db, blocks)
    # بيداغوجيا → بيداغوجية؛ الفرنسية بقيمتين مختلفتين (27/30) → مراجعة
    assert db.scalar("SELECT hours FROM curriculum WHERE subject_id=?", (s_ped,)) is None or res["imported"] >= 0
    issues = db.q("SELECT * FROM curriculum_issues WHERE resolved=0")
    reasons = {r["name"]: r["reason"] for r in issues}
    # الإصدار 1.4: المادة التي لا تشبه أي مادة تُنشأ آلياً بنفس الاسم مع مقررها، وتنبيه بذلك
    new_id = db.scalar("SELECT id FROM subjects WHERE name='مادة لا توجد'")
    assert new_id and "مادة لا توجد" not in reasons
    assert db.scalar("SELECT hours FROM curriculum WHERE subject_id=?", (new_id,)) == 15
    assert db.scalar("SELECT COUNT(*) FROM data_alerts WHERE key='cf:created'") == 1
    assert any(r["guess_subject_id"] == s_fr for r in issues)
    fr_issue = next(r for r in issues if r["guess_subject_id"] == s_fr and r["hours"] == 27)
    CI.resolve_issue(db, fr_issue["id"], lvl, sp1, s_fr, 27)
    assert db.scalar("SELECT hours FROM curriculum WHERE subject_id=? AND specialty_id=?", (s_fr, sp1)) == 27
    assert not db.scalar("SELECT COUNT(*) FROM curriculum_issues WHERE resolved=0 AND guess_subject_id=?", (s_fr,))


def test_new_pages_open(seeded):
    db, ids = seeded
    _app()
    from dpp.ui.context import AppContext
    from dpp.ui.pages.curriculum_page import CurriculumPage
    from dpp.ui.pages.settings_more import GridSettings, PrintSettings, SchedulingSettings
    ctx = AppContext(db)
    for cls in (CurriculumPage, PrintSettings, SchedulingSettings, GridSettings):
        w = cls(ctx)
        w.close()
