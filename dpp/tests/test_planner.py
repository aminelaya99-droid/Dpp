from dpp.models import Subject, Teacher
from dpp.services import planner
from dpp.services.conflicts import TEACHER


def test_place_move_conflicts(session, sample):
    t, a, b = sample["training"], sample["a"], sample["b"]
    w = planner.get_week(session, t, 10)
    subj = Subject(name="الطبوغرافيا", kind="military")
    pe = session.query(Subject).filter_by(name="التربية البدنية").one()
    teacher = Teacher(last_name="بن علي")
    session.add_all([subj, teacher])
    l1 = planner.place_lesson(session, w, a, 0, 480, subj, teacher, 90)
    assert l1.duration == 90
    l2 = planner.place_lesson(session, w, b, 0, 510, subj, teacher)
    cs = planner.lesson_conflicts(session, [l2])
    assert [c.kind for c in cs] == [TEACHER]
    # مادة مشتركة مسموحة
    l1.subject = pe
    l2.subject = pe
    l2.start = 480
    l2.duration = 90
    assert planner.lesson_conflicts(session, [l2]) == []
    # تجاهل تعارض
    l2.subject = subj
    cs = planner.lesson_conflicts(session, [l2])
    planner.ignore_conflicts(session, cs)
    assert planner.lesson_conflicts(session, [l2]) == []


def test_duration_clamp_and_free_starts(session, sample):
    w = planner.get_week(session, sample["training"], 3)
    assert planner.clamp_duration(10) == 30
    assert planner.clamp_duration(500) == 240
    planner.place_lesson(session, w, sample["a"], 1, 480, None, None, 120)
    starts = planner.free_starts(session, w, sample["a"], 1, 60)
    assert 480 not in starts and 600 in starts and 720 not in starts  # الغداء 12:00


def test_teacher_busy_across_trainings(session, sample):
    from sqlalchemy import select
    from dpp.models import Training
    from dpp.services import structure
    res = session.scalar(select(Training).where(Training.code == "RES"))
    sp = structure.add_specialty(session, res.levels[0], "مشاة")
    r1 = structure.add_section(session, sp, "OFR-1")
    teacher = Teacher(last_name="قاسمي")
    session.add(teacher)
    w_bmp = planner.get_week(session, sample["training"], 4)
    w_res = planner.get_week(session, res, 4)  # نفس التاريخ (نفس البداية)
    planner.place_lesson(session, w_res, r1, 2, 540, None, teacher, 60)
    busy = planner.teacher_busy(session, w_bmp, teacher, 2, 510, 600)
    assert len(busy) == 1


def test_previous_teacher_and_copy(session, sample):
    w1 = planner.get_week(session, sample["training"], 1)
    w2 = planner.get_week(session, sample["training"], 2)
    subj = Subject(name="لاسلكي", kind="specialized")
    t = Teacher(last_name="سعيدي")
    session.add_all([subj, t])
    planner.place_lesson(session, w1, sample["a"], 0, 480, subj, t)
    session.commit()
    assert planner.previous_teacher(session, sample["a"], subj) is t
    assert planner.copy_week(session, w1, w2) == 1
    snap = planner.Snapshot.of(w2.lessons[0])
    w2.lessons[0].start = 900
    session.commit()
    snap.restore(session)
    assert w2.lessons[0].start == 480
