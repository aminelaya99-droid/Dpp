import datetime as dt

from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from dpp.models import Alert, CurriculumItem, Subject, Training
from dpp.services import curriculum, planner, progress, structure


def _book(path, rows):
    wb = Workbook()
    ws = wb.active
    ws.append(curriculum.HEADERS)
    for r in rows:
        ws.append(r)
    wb.save(path)
    return path


def test_template(session, sample, tmp_path):
    p = curriculum.write_template(session, tmp_path / "t.xlsx")
    wb = load_workbook(p)
    assert [c.value for c in wb.worksheets[0][1]] == curriculum.HEADERS
    assert "تعليمات" in wb.sheetnames


def test_import_matching_and_alerts(session, sample, tmp_path):
    session.add(Subject(name="الطبوغرافيا", kind="military"))
    session.add(Subject(name="الاتصالات اللاسلكية", kind="specialized"))
    sp2 = structure.add_specialty(session, sample["level"], "مشاة")
    session.commit()
    path = _book(tmp_path / "c.xlsx", [
        ["BMP", "BMP1", "", "طبوغرافيا", "عسكرية", "", 40],          # مطابقة تلقائية، كل الاختصاصات
        ["BMP", "BMP1", "إشارة", "الاتصالات السلكية واللاسلكية", "", "", 60],   # مشكوك فيها
        ["", "", "إشارة", "مادة جديدة كليا", "تخصصية", "", None],     # حجم ناقص، مادة جديدة
        ["BMP", "BMP1", "إشارة", "", "", "", 10],                     # مادة ناقصة
        ["BMP", "BMP1", "طيران", "رادار", "تخصصية", "", 10],          # اختصاص غير واضح
        ["BMP", "BMP1", "إشارة", "المجموع", "", "", 200],             # عدم تطابق
    ])
    res = curriculum.import_excel(session, path)
    topo = session.scalar(select(Subject).where(Subject.name == "الطبوغرافيا"))
    items = session.scalars(select(CurriculumItem).where(CurriculumItem.subject_id == topo.id)).all()
    assert {i.specialty_id for i in items} == {sample["specialty"].id, sp2.id}
    assert res.doubtful == 1
    assert "مادة جديدة كليا" in res.new_subjects
    text = " | ".join(res.alerts)
    assert "الحجم الساعي ناقص" in text and "مادة ناقصة" in text and "اختصاص غير واضح" in text
    assert "عدم تطابق المجاميع" in text
    # المراجعة: إنشاء مادة جديدة بدل المطابقة المشكوك فيها
    pend = curriculum.pending_matches(session)
    assert len(pend) == 1
    curriculum.resolve_match(session, pend[0], create_new=True)
    assert curriculum.pending_matches(session) == []
    assert session.scalar(select(Subject).where(Subject.name == "الاتصالات السلكية واللاسلكية"))
    # إعادة الاستيراد تحدث ولا تكرر
    res2 = curriculum.import_excel(session, _book(tmp_path / "d.xlsx", [["BMP", "BMP1", "", "طبوغرافيا", "", "", 45]]))
    assert res2.updated == 2 and res2.created == 0


def test_audit(session, sample):
    sp2 = structure.add_specialty(session, sample["level"], "مشاة")
    structure.add_section(session, sp2, "M1")
    topo = Subject(name="الطبوغرافيا", kind="military")
    radio = Subject(name="راديو", kind="specialized")
    session.add_all([topo, radio])
    session.flush()
    session.add(CurriculumItem(specialty_id=sample["specialty"].id, subject_id=topo.id, hours=10))
    session.add(CurriculumItem(specialty_id=sp2.id, subject_id=radio.id, hours=None))
    session.commit()
    msgs = curriculum.audit(session)
    assert any("ناقصة في: مشاة" in m for m in msgs)
    assert any("الحجم الساعي ناقص" in m for m in msgs)


def test_progress_phase_scope(session):
    res = session.scalar(select(Training).where(Training.code == "RES"))
    lv = res.levels[0]
    sp = structure.add_specialty(session, lv, "مشاة")
    sec = structure.add_section(session, sp, "R1")
    subj = Subject(name="الرمي", kind="military")
    session.add(subj)
    session.flush()
    common = next(p for p in res.phases if p.kind == "common")  # الأسابيع 2-7
    session.add(CurriculumItem(specialty_id=sp.id, subject_id=subj.id, phase_id=common.id, hours=12))
    session.commit()
    # 4 ساعات في الأسبوع 2، ساعتان في الأسبوع 1 (خارج المرحلة)، خفارة لا تُحسب
    w1, w2 = planner.get_week(session, res, 1), planner.get_week(session, res, 2)
    planner.place_lesson(session, w2, sec, 0, 480, subj, None, 240)
    planner.place_lesson(session, w1, sec, 0, 480, subj, None, 120)
    planner.place_lesson(session, w2, sec, 1, 0, subj, None, kind="guard")
    session.commit()
    # منتصف المرحلة: نهاية الأسبوع 4 (3 من 6 أسابيع)
    today = res.week_start(4) + dt.timedelta(days=6)
    p = progress.section_progress(session, sec, today)
    assert p.phase.id == common.id
    row = p.rows[0]
    assert row.done == 4 and row.planned == 12
    assert abs(row.expected - 6) < 0.01 and abs(row.delay - 2) < 0.01
    assert round(row.percent) == 33 and row.remaining == 8
    assert p.remaining_weeks == 4  # الأسابيع 4..7
    assert progress.remaining_hours(session, sec, today) == {subj.id: 8.0}


def test_progress_training_scope(session, sample):
    t, sec = sample["training"], sample["a"]
    subj = Subject(name="الطبوغرافيا", kind="military")
    session.add(subj)
    session.flush()
    session.add(CurriculumItem(specialty_id=sample["specialty"].id, subject_id=subj.id, hours=72))
    w = planner.get_week(session, t, 1)
    planner.place_lesson(session, w, sec, 0, 480, subj, None, 120)
    planner.place_lesson(session, w, sec, 2, 0, subj, None, kind="exam")  # الامتحان يُحسب
    session.commit()
    today = t.week_start(2) - dt.timedelta(days=1)  # نهاية الأسبوع 1
    p = progress.section_progress(session, sec, today)
    row = p.rows[0]
    exam_h = (sample["level"].day_end - sample["level"].day_start) / 60
    assert row.done == 2 + exam_h
    # المرحلة الحالية = السداسي الأول (18 من 36 أسبوعاً) ← المتوقع = 72 × 0.5 × 1/18 = 2
    assert abs(row.expected - 2) < 0.01
    assert progress.section_overall(session, sec, today)["percent"] > 0
