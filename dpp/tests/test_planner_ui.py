"""اختبار واجهة المخطط دون شاشة (offscreen)."""
import pytest

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture
def page(session, sample, monkeypatch):
    from dpp.app import create_app
    create_app([])
    from dpp.ui.planner import planner_page as pp
    from dpp.ui.planner.dialogs import ConflictDialog, TeacherDialog
    from dpp.models import Teacher
    teacher = Teacher(last_name="بن علي")
    session.add(teacher)
    session.commit()
    state = {"teacher": teacher, "choice": ConflictDialog.FIX}

    def fake_teacher_exec(self):
        self.result_teacher = state["teacher"]
        return 1

    def fake_conflict_exec(self):
        self.choice = state["choice"]
        return 1
    monkeypatch.setattr(TeacherDialog, "exec", fake_teacher_exec)
    monkeypatch.setattr(ConflictDialog, "exec", fake_conflict_exec)
    p = pp.PlannerPage(None)
    p.focus_on(training_id=sample["training"].id, week=5)
    return p, state


def test_drop_duration_move(page, session, sample):
    from dpp.models import Lesson, Subject
    p, state = page
    subj = Subject(name="الطبوغرافيا", kind="military")
    session.add(subj)
    session.commit()
    a, b = sample["a"], sample["b"]
    p.on_card_dropped({"subject_id": subj.id}, a.id, 0, 480)
    les = session.query(Lesson).one()
    assert les.teacher is state["teacher"] and les.duration == 60
    p.set_duration(les.id, 150)
    assert les.duration == 150
    p.set_duration(les.id, 30)
    assert les.duration == 30
    # نقل إلى فرع آخر يحتفظ بالأستاذ
    p.on_lesson_moved(les.id, b.id, 1, 540)
    assert (les.section_id, les.day, les.start, les.teacher_id) == (b.id, 1, 540, state["teacher"].id)
    # حصة ثانية بنفس الأستاذ والوقت لفرع آخر → تعارض → تصحيح = حذف
    p.on_card_dropped({"subject_id": subj.id}, a.id, 1, 540)
    assert session.query(Lesson).count() == 1
    # تجاهل → تبقى
    from dpp.ui.planner.dialogs import ConflictDialog
    state["choice"] = ConflictDialog.IGNORE
    p.on_card_dropped({"subject_id": subj.id}, a.id, 1, 540)
    assert session.query(Lesson).count() == 2
    assert p._conflicts == []  # التعارض متجاهل


def test_move_conflict_fix_restores(page, session, sample):
    from dpp.models import Lesson, Subject
    p, state = page
    subj = Subject(name="لاسلكي", kind="specialized")
    session.add(subj)
    session.commit()
    p.on_card_dropped({"subject_id": subj.id}, sample["a"].id, 0, 480)
    p.on_card_dropped({"subject_id": subj.id}, sample["a"].id, 0, 600)
    l1, l2 = session.query(Lesson).order_by(Lesson.start).all()
    p.on_lesson_moved(l2.id, sample["a"].id, 0, 480)  # تداخل مع الأولى → تصحيح
    assert l2.start == 600
    p.add_full_day(sample["b"].id, 2, "guard")
    g = session.query(Lesson).filter_by(kind="guard").one()
    assert g.duration == sample["level"].day_end - sample["level"].day_start
