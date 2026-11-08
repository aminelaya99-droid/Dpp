"""اختبارات الساعات، الاستخلاف، التعويض، التعارضات، الرزنامة، النسخ الاحتياطي، الحفظ، الدخول."""
import zipfile
from datetime import timedelta

import pytest
from conftest import START

from dpp.db.database import Database
from dpp.scheduler.engine import Scheduler
from dpp.services import absences as A
from dpp.services import backup as B
from dpp.services import calendar as C
from dpp.services import hours as H
from dpp.services import timetables as T
from dpp.utils import iso, make_abbrev, unique_abbrev


def _week(db, ids):
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    return T.save_result(db, ids["formation"], res)


def test_hours_planned_vs_done(seeded):
    db, ids = seeded
    _week(db, ids)
    g, fr = ids["groups"][0], ids["subjects"]["FR"]
    rows = db.q("""SELECT s.id FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                   WHERE sg.group_id=? AND s.subject_id=? ORDER BY s.date""", (g, fr))
    assert len(rows) == 2
    p = next(r for r in H.requirement_progress(db, ids["formation"], START) if r["group"] == "الفوج الكامل"
             and r["subject"] == "لغة فرنسية" and r["section_short"] == "BMP1")
    assert p["planned"] == 4 and p["done"] == 0          # المبرمج ليس منجزاً
    T.set_status(db, rows[0]["id"], "done")
    T.set_status(db, rows[1]["id"], "cancelled")
    p = next(r for r in H.requirement_progress(db, ids["formation"], START) if r["requirement_id"] == p["requirement_id"])
    assert p["done"] == 2 and p["cancelled"] == 2 and p["planned"] == 2 and p["remaining"] == 14


def test_substitute_hours_not_double_counted(seeded):
    db, ids = seeded
    _week(db, ids)
    s = db.one("SELECT * FROM sessions WHERE subject_id=? ORDER BY date LIMIT 1", (ids["subjects"]["FR"],))
    orig = s["teacher_id"]
    A.add_absence(db, orig, "مهمة", s["date"], s["date"])
    aff = [x["id"] for x in A.affected_sessions(db, db.scalar("SELECT id FROM absences"))]
    assert s["id"] in aff
    extra = db.insert("teachers", full_name="أستاذ احتياط", rank="مساعد")
    db.execute("INSERT INTO teacher_subjects VALUES (?,?)", (extra, ids["subjects"]["FR"]))
    cands = A.suggest_substitutes(db, s["id"])
    assert cands and all(c["id"] != orig for c in cands)
    # أي أستاذ متفرغ مقبول، لكن من يدرّس المادة يأتي أولاً
    assert db.scalar("SELECT COUNT(*) FROM teacher_subjects WHERE teacher_id=? AND subject_id=?",
                     (cands[0]["id"], ids["subjects"]["FR"]))
    tiers = [c["tier"] for c in cands]
    assert tiers == sorted(tiers)
    sub = cands[0]["id"]
    A.assign_substitute(db, s["id"], sub)
    T.set_status(db, s["id"], "done")
    h_orig = H.teacher_hours(db, orig)
    h_sub = H.teacher_hours(db, sub)
    dur = (s["end_min"] - s["start_min"]) / 60
    assert h_sub["done"] == dur and h_sub["as_substitute"] == dur
    assert h_orig["done"] == 0 and h_orig["replaced_by_others"] == dur
    row = db.one("SELECT teacher_id, substitute_id FROM sessions WHERE id=?", (s["id"],))
    assert row["teacher_id"] == orig and row["substitute_id"] == sub   # الأصلي محفوظ للتتبع


def test_substitute_must_be_free(seeded):
    db, ids = seeded
    tt = T.get_or_create_timetable(db, ids["formation"], START)
    a = T.create_session(db, tt, START, 480, 600, ids["subjects"]["FR"], ids["teachers"]["أحمد بن علي"], None, [ids["groups"][0]])
    T.create_session(db, tt, START, 480, 600, ids["subjects"]["FR"], ids["teachers"]["سامية قاسمي"], None, [ids["groups"][1]])
    assert all(c["id"] != ids["teachers"]["سامية قاسمي"] for c in A.suggest_substitutes(db, a))
    with pytest.raises(T.ConflictError):
        A.assign_substitute(db, a, ids["teachers"]["سامية قاسمي"])


def test_makeup_counts_once(seeded):
    db, ids = seeded
    tt = T.get_or_create_timetable(db, ids["formation"], START)
    sid = T.create_session(db, tt, START, 480, 600, ids["subjects"]["FR"], ids["teachers"]["أحمد بن علي"], None, [ids["groups"][0]])
    with pytest.raises(ValueError):
        T.create_makeup(db, sid, START + timedelta(days=1), 480)     # يجب التأجيل أولاً
    T.set_status(db, sid, "postponed")
    mk = T.create_makeup(db, sid, START + timedelta(days=1), 480)
    with pytest.raises(ValueError):
        T.create_makeup(db, sid, START + timedelta(days=2), 480)     # لا تعويض مزدوج
    T.set_status(db, mk, "done")
    h = H.teacher_hours(db, ids["teachers"]["أحمد بن علي"])
    assert h["done"] == 2 and h["planned"] == 2


def test_conflict_rules(seeded):
    db, ids = seeded
    tt = T.get_or_create_timetable(db, ids["formation"], START)
    whole, g1, g2 = ids["groups"][0], ids["subgroups"][0], ids["subgroups"][1]
    T.create_session(db, tt, START, 480, 600, ids["subjects"]["INF"], ids["teachers"]["كريم عيسو"], ids["rooms"][0], [g1])
    # مجموعتان فرعيتان لا تتعارضان
    T.create_session(db, tt, START, 480, 600, ids["subjects"]["INF"], ids["teachers"]["ليلى حمزي"], ids["rooms"][1], [g2])
    # الفوج الكامل يتعارض مع مجموعاته
    c = T.check_conflicts(db, START, 540, 660, ids["teachers"]["أحمد بن علي"], None, [whole], ids["subjects"]["FR"])
    assert any("الفوج" in x for x in c)
    # تعارض الأستاذ والقاعة
    c = T.check_conflicts(db, START, 540, 660, ids["teachers"]["كريم عيسو"], ids["rooms"][1], [ids["groups"][1]],
                          ids["subjects"]["INF"])
    assert any("الأستاذ" in x for x in c) and any("القاعة" in x for x in c)
    # الأهلية
    c = T.check_conflicts(db, START, 840, 960, ids["teachers"]["كريم عيسو"], None, [ids["groups"][2]], ids["subjects"]["FR"])
    assert any("غير مؤهل" in x for x in c)
    with pytest.raises(T.ConflictError):
        T.create_session(db, tt, START, 540, 660, ids["subjects"]["FR"], ids["teachers"]["أحمد بن علي"], None, [whole])


def test_move_and_approve_locks(seeded):
    db, ids = seeded
    tt = _week(db, ids)
    s = db.one("SELECT * FROM sessions WHERE timetable_id=? LIMIT 1", (tt,))
    T.approve(db, tt)
    with pytest.raises(T.ConflictError):
        T.update_session(db, s["id"], start_min=s["start_min"] + 30, end_min=s["end_min"] + 30)
    T.set_status(db, s["id"], "done")   # تسجيل الإنجاز مسموح في الجدول المعتمد
    T.reopen(db, tt)
    assert db.scalar("SELECT version FROM timetables WHERE id=?", (tt,)) == 2


def test_snapshot_restore(seeded):
    db, ids = seeded
    tt = _week(db, ids)
    snap = T.snapshot(db, tt, "test")
    n = db.scalar("SELECT COUNT(*) FROM sessions WHERE timetable_id=?", (tt,))
    db.execute("DELETE FROM sessions WHERE timetable_id=?", (tt,))
    T.restore_snapshot(db, snap)
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE timetable_id=?", (tt,)) == n


def test_copy_week_independent(seeded):
    db, ids = seeded
    tt = _week(db, ids)
    db.execute("UPDATE sessions SET status='done' WHERE timetable_id=?", (tt,))
    n, skipped = T.copy_week(db, ids["formation"], START, START + timedelta(days=7))
    assert n > 0
    tt2 = T.get_or_create_timetable(db, ids["formation"], START + timedelta(days=7))
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE timetable_id=? AND status<>'planned'", (tt2,)) == 0


def test_reminders_and_countdown(db):
    from datetime import date
    today = date(2026, 11, 1)
    C.add_event(db, "امتحان", "exam", today + timedelta(days=7), today + timedelta(days=8), remind_days="30,7,1")
    C.add_event(db, "اجتماع", "meeting", today + timedelta(days=5), remind_days="3")
    up = C.upcoming(db, today)
    assert [e["days_left"] for e in up] == [5, 7]
    due = C.due_reminders(db, today)
    assert [e["title"] for e in due] == ["امتحان"]
    assert C.due_reminders(db, today + timedelta(days=2))[0]["title"] == "اجتماع"


def test_late_subject_alert(seeded):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=10)
    late = H.late_subjects(db, ids["formation"], START + timedelta(days=20))
    assert late   # لا شيء مسجل كمنجز بعد 3 أسابيع → متأخر
    assert H.late_subjects(db, ids["formation"], START) == []


def test_backup_and_restore(db, tmp_path):
    db.insert("formations", name="أ")
    p = B.create_backup(db, target_dir=tmp_path / "bk")
    assert B.inspect_backup(p)["valid"]
    db.insert("formations", name="ب")
    new = B.restore_backup(db, p)
    assert [r[0] for r in new.q("SELECT name FROM formations")] == ["أ"]
    # النسخة التالفة تُرفض دون تغيير البيانات
    bad = tmp_path / "bk" / "DPP_bad.dppbak"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("dpp.sqlite", b"not a database")
        z.writestr("dpp_backup.json", "{}")
    with pytest.raises(RuntimeError):
        B.restore_backup(new, bad)
    assert new.scalar("SELECT COUNT(*) FROM formations") == 1
    new.close()


def test_persistence_after_reopen(tmp_path):
    p = tmp_path / "x.sqlite"
    d = Database(p)
    d.create_admin("admin", "secret1")
    d.insert("teachers", full_name="أستاذ")
    d.close()
    d2 = Database(p)
    assert d2.scalar("SELECT COUNT(*) FROM teachers") == 1
    assert d2.check_login("admin", "secret1") and not d2.check_login("admin", "wrong")
    with pytest.raises(ValueError):
        d2.create_admin("other", "123456")   # حساب واحد فقط
    d2.close()


def test_abbreviations():
    assert make_abbrev("Brevet Militaire Professionnel 2") == "BMP2"
    assert make_abbrev("ESOC 2 - CRH") == "ESOC2-CRH"
    assert make_abbrev("ESOC 1 - C1") == "ESOC1-C1"
    assert unique_abbrev("BMP2", {"BMP2"}) == "BMP2-2"
