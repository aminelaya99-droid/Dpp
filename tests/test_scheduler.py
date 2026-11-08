"""اختبارات محرك الجدولة والتخطيط الكامل."""
from datetime import timedelta

from conftest import START, overlaps

from dpp.scheduler.engine import Scheduler
from dpp.services import calendar as C
from dpp.services import timetables as T
from dpp.utils import iso, weekday_sun0


def _group_ids(db, section_id):
    return [r[0] for r in db.q("SELECT id FROM groups_ WHERE section_id=?", (section_id,))]


def test_single_section(seeded):
    db, ids = seeded
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START, _group_ids(db, ids["sections"][0]))
    assert res.status in ("OPTIMAL", "FEASIBLE")
    assert not res.unplaced, [u.reason for u in res.unplaced]
    # FR 4h/2h=2, DRT 3h/1.5=2, EPS 1, INF 2 subgroups x1 = 7
    assert len(res.placements) == 7
    T.save_result(db, ids["formation"], res)
    assert overlaps(db) == []


def test_all_sections_no_conflicts(seeded):
    db, ids = seeded
    res = Scheduler(db, time_limit=15).schedule_week(ids["formation"], START)
    assert not res.unplaced
    T.save_result(db, ids["formation"], res)
    assert overlaps(db) == []
    # احترام أيام الراحة (الجمعة والسبت) واستراحة الغداء
    for p in res.placements:
        assert weekday_sun0(p.day) not in (5, 6)
        assert not (p.start_min < 780 and p.end_min > 720)


def test_shared_session_only_for_shareable(seeded):
    db, ids = seeded
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    eps = [p for p in res.placements if p.meeting.subject_id == ids["subjects"]["EPS"]]
    assert len(eps) == 1 and len(eps[0].meeting.group_ids) == 3   # حصة مشتركة واحدة لثلاثة أقسام
    # مادة غير قابلة للمشاركة برمز مشاركة: لا تُدمج
    db.execute("UPDATE requirements SET share_code='X' WHERE subject_id=?", (ids["subjects"]["FR"],))
    res2 = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    fr = [p for p in res2.placements if p.meeting.subject_id == ids["subjects"]["FR"]]
    assert all(len(p.meeting.group_ids) == 1 for p in fr)
    assert any("غير مفعلة كمادة قابلة للمشاركة" in x for x in res2.problems)


def test_teacher_qualification(seeded):
    db, ids = seeded
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    for p in res.placements:
        assert db.scalar("SELECT COUNT(*) FROM teacher_subjects WHERE teacher_id=? AND subject_id=?",
                         (p.meeting.teacher_id, p.meeting.subject_id)) == 1


def test_holiday_blocks_day(seeded):
    db, ids = seeded
    monday = START + timedelta(days=1)
    C.add_event(db, "عطلة", "holiday", monday, monday, ids["formation"])
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    assert monday not in res.days
    assert all(p.day != monday for p in res.placements)


def test_missing_resources_reported(seeded):
    db, ids = seeded
    # مادة بلا أستاذ مؤهل
    s = db.insert("subjects", name="طبوغرافيا", short="TOPO")
    db.insert("requirements", formation_id=ids["formation"], group_id=ids["groups"][0], subject_id=s,
              weekly_hours=2, session_minutes=120)
    # حجم ساعي مستحيل لأستاذ واحد
    db.execute("UPDATE requirements SET weekly_hours=40 WHERE subject_id=? AND group_id=?",
               (ids["subjects"]["FR"], ids["groups"][0]))
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    assert any("لا يوجد أستاذ مؤهل" in p for p in res.problems)
    assert res.unplaced and all(u.reason for u in res.unplaced)
    assert not res.complete


def test_unavailability_reason(seeded):
    db, ids = seeded
    t = ids["teachers"]["يوسف طويل"]
    for wd in range(7):
        db.insert("unavailability", kind="teacher", ref_id=t, weekday=wd, start_min=0, end_min=24 * 60, hard=1)
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    eps = [u for u in res.unplaced if u.meeting.teacher_id == t]
    assert eps and "غير متاح" in eps[0].reason


def test_period_plan_distributes_all_hours(seeded):
    db, ids = seeded
    plan = T.plan_period(db, ids["formation"], time_limit=10)
    assert not plan.carried_over
    for r in db.q("SELECT * FROM requirements WHERE formation_id=?", (ids["formation"],)):
        m = db.scalar("""SELECT SUM(s.end_min-s.start_min) FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                         WHERE sg.group_id=? AND s.subject_id=?""", (r["group_id"], r["subject_id"]), 0)
        assert abs(m / 60 - r["total_hours"]) < 1e-6
    assert db.scalar("SELECT COUNT(*) FROM timetables WHERE formation_id=?", (ids["formation"],)) == 4
    assert overlaps(db) == []


def test_reschedule_after_calendar_change(seeded):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=10)
    before = db.scalar("SELECT SUM(end_min-start_min) FROM sessions")
    tue = START + timedelta(days=9)   # ثلاثاء الأسبوع الثاني
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE date=?", (iso(tue),)) > 0
    C.add_event(db, "توقف", "break", tue, tue, ids["formation"])
    r = T.reschedule_after_calendar_change(db, ids["formation"])
    assert r["removed"] > 0
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE date=?", (iso(tue),)) == 0
    after = db.scalar("SELECT SUM(end_min-start_min) FROM sessions")
    assert after == before   # كل الساعات أعيدت برمجتها
    assert overlaps(db) == []


def test_approved_timetable_untouched(seeded):
    db, ids = seeded
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    tt = T.save_result(db, ids["formation"], res)
    T.approve(db, tt)
    n = db.scalar("SELECT COUNT(*) FROM sessions WHERE timetable_id=?", (tt,))
    try:
        T.save_result(db, ids["formation"], res)
        raise AssertionError("كان يجب رفض الاستبدال")
    except T.ConflictError:
        pass
    plan = T.plan_period(db, ids["formation"], time_limit=10)
    assert any("معتمد" in m for m in plan.messages)
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE timetable_id=?", (tt,)) == n


def test_regenerate_keeps_manual(seeded):
    db, ids = seeded
    tt = T.get_or_create_timetable(db, ids["formation"], START)
    sid = T.create_session(db, tt, START, 480, 600, ids["subjects"]["FR"], ids["teachers"]["أحمد بن علي"], None,
                           [ids["groups"][0]], manual=True)
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    T.save_result(db, ids["formation"], res)
    assert db.one("SELECT id FROM sessions WHERE id=?", (sid,))
    assert overlaps(db) == []
    # الحصة اليدوية تُحتسب من الحجم الأسبوعي: FR لـ BMP1 = 4 سا إجمالاً
    m = db.scalar("""SELECT SUM(s.end_min-s.start_min) FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                     WHERE sg.group_id=? AND s.subject_id=?""", (ids["groups"][0], ids["subjects"]["FR"]))
    assert m == 240
