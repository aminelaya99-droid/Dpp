import datetime as dt

from sqlalchemy import select

from dpp.models import CurriculumItem, Event, Lesson, Subject, Teacher, Training
from dpp.services import planner, scheduler, structure


def _setup(session, sample, hours=None):
    sp = sample["specialty"]
    subs = {}
    for name, kind, h in [("الطبوغرافيا", "military", 36), ("الاتصالات", "specialized", 72),
                          ("الفرنسية", "general", 18)]:
        subj = Subject(name=name, kind=kind)
        session.add(subj)
        session.flush()
        session.add(CurriculumItem(specialty_id=sp.id, subject_id=subj.id, hours=(hours or {}).get(name, h)))
        subs[name] = subj
    session.commit()
    return subs


def _no_conflicts(session, week):
    return planner.week_conflicts(session, week)


def test_schedule_respects_rules(session, sample):
    subs = _setup(session, sample)
    t = sample["training"]
    # أستاذ مشترك بين الفرعين لمادة واحدة
    teacher = Teacher(last_name="بن علي")
    teacher.subjects.append(subs["الاتصالات"])
    teacher.specialties.append(sample["specialty"])
    session.add(teacher)
    session.commit()
    res = scheduler.schedule_week(session, t, 2)
    assert res.proposals
    week = planner.get_week(session, t, 2)
    assert _no_conflicts(session, week) == []
    for les in week.lessons:
        assert les.origin == "auto"
        lv = les.section.level
        assert lv.day_start <= les.start and les.end <= lv.day_end
        assert les.day not in t.weekend_days
        assert 30 <= les.duration <= 240
    # 72 سا على 36 أسبوعاً = 2 سا/أسبوع لكل فرع
    comm = [x for x in week.lessons if x.subject_id == subs["الاتصالات"].id]
    assert sum(x.duration for x in comm) == 2 * 120
    assert all(x.teacher_id == teacher.id for x in comm)
    # اليوم لا يتجاوز 7 ساعات
    for sec in (sample["a"], sample["b"]):
        for d in range(7):
            assert planner.day_study_minutes(week, sec.id, d) <= 420


def test_keeps_previous_teacher_and_replaces_auto(session, sample):
    subs = _setup(session, sample)
    t = sample["training"]
    prev = Teacher(last_name="قاسمي")
    session.add(prev)
    w1 = planner.get_week(session, t, 1)
    planner.place_lesson(session, w1, sample["a"], 0, 480, subs["الفرنسية"], prev, 60)
    session.commit()
    scheduler.schedule_week(session, t, 2)
    scheduler.schedule_week(session, t, 2)  # إعادة التشغيل تستبدل الحصص الآلية
    week = planner.get_week(session, t, 2)
    fr = [x for x in week.lessons if x.subject_id == subs["الفرنسية"].id and x.section_id == sample["a"].id]
    assert fr and all(x.teacher_id == prev.id for x in fr)
    assert len(fr) == 1


def test_manual_lessons_fixed_and_counted(session, sample):
    subs = _setup(session, sample)
    t = sample["training"]
    w = planner.get_week(session, t, 3)
    manual = planner.place_lesson(session, w, sample["a"], 0, 480, subs["الاتصالات"], None, 120)
    session.commit()
    scheduler.schedule_week(session, t, 3, sections=[sample["a"]])
    week = planner.get_week(session, t, 3)
    comm = [x for x in week.lessons if x.subject_id == subs["الاتصالات"].id]
    assert comm == [manual]  # الحاجة الأسبوعية (2 سا) مغطاة يدوياً
    assert _no_conflicts(session, week) == []


def test_events_holiday_and_dry_run(session, sample):
    _setup(session, sample)
    t = sample["training"]
    # حدث يغطي الأحد كاملاً للفرع A
    ev = Event(title="زيارة", date=t.week_start(4), start=480, end=990)
    ev.sections.append(sample["a"])
    session.add(ev)
    session.commit()
    res = scheduler.schedule_week(session, t, 4, dry_run=True)
    assert res.proposals and session.query(Lesson).count() == 0
    assert all(not (p.section.id == sample["a"].id and p.day == 0) for p in res.proposals)
    res = session.scalar(select(Training).where(Training.code == "RES"))
    sp = structure.add_specialty(session, res.levels[0], "مشاة")
    sec = structure.add_section(session, sp, "R1")
    r = scheduler.schedule_week(session, res, 8, sections=[sec])  # الأسبوع 8 عطلة
    assert r.proposals == [] and any("عطلة" in w for w in r.warnings)


def test_overloaded_week_scaled(session, sample):
    _setup(session, sample, hours={"الطبوغرافيا": 2000, "الاتصالات": 2000, "الفرنسية": 2000})
    t = sample["training"]
    res = scheduler.schedule_week(session, t, 5, sections=[sample["a"]])
    week = planner.get_week(session, t, 5)
    assert any("تفوق السعة" in w for w in res.warnings)
    total = sum(x.duration for x in week.lessons)
    assert total <= 5 * 420
    assert _no_conflicts(session, week) == []
