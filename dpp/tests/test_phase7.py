import datetime as dt

import pytest
from sqlalchemy import select

from dpp.models import Event, ShootingSession, Subject, Teacher, Weapon
from dpp.services import auth, backup, planner, reset, shooting


def test_event_blocks_lessons(session, sample):
    t = sample["training"]
    w = planner.get_week(session, t, 3)
    les = planner.place_lesson(session, w, sample["a"], 1, 600, None, None, 60)
    ev = Event(title="محاضرة عامة", date=t.week_start(3) + dt.timedelta(days=1), start=540, end=720)
    ev.sections.append(sample["a"])
    session.add(ev)
    session.commit()
    cs = planner.week_conflicts(session, w)
    assert [c.kind for c in cs] == ["event"] and cs[0].lesson_ids == (les.id,)
    ev.blocks_lessons = False
    session.commit()
    assert planner.week_conflicts(session, w) == []


def test_shooting_sync_and_ammo(session, sample):
    t = sample["training"]
    tir = session.scalar(select(Subject).where(Subject.name == "الرمي"))
    assert tir.is_shooting and tir.allow_shared
    teacher = Teacher(last_name="رامي")
    session.add(teacher)
    w = planner.get_week(session, t, 2)
    planner.place_lesson(session, w, sample["a"], 0, 480, tir, teacher, 240)
    planner.place_lesson(session, w, sample["b"], 0, 480, tir, teacher, 240)  # حصة مشتركة
    session.commit()
    assert planner.week_conflicts(session, w) == []
    assert shooting.sync_from_week(session, w) == 1
    assert shooting.sync_from_week(session, w) == 0  # لا تكرار
    sess = session.scalar(select(ShootingSession))
    assert len(sess.sections) == 2
    wp = Weapon(name="كلاشنيكوف", quantity=30)
    session.add(wp)
    sess.weapon, sess.ammo_planned, sess.ammo_used = wp, 300, 280
    session.commit()
    summ = shooting.ammo_summary(session)
    assert summ == [{"weapon": "كلاشنيكوف", "sessions": 1, "planned": 300, "used": 280, "sections": 2}]


def test_backup_restore_and_wipe(tmp_path, monkeypatch):
    monkeypatch.setenv("DPP_DATA_DIR", str(tmp_path))
    from dpp.db import init_db, reset_engine
    from dpp.models import Weapon as W
    db = tmp_path / "dpp.sqlite3"
    s = init_db(db)
    auth.create_admin(s, "admin", "pass1")
    s.add(W(name="مسدس"))
    s.commit()
    bk = backup.create_backup()
    assert bk.exists() and backup.list_backups()[0] == bk
    s.add(W(name="بندقية"))
    s.commit()
    s = backup.restore_backup(bk)
    assert [w.name for w in s.scalars(select(W))] == ["مسدس"]
    assert any("before_restore" in p.name for p in backup.list_backups())
    with pytest.raises(ValueError):
        reset.wipe_all(s, "wrong")
    s = reset.wipe_all(s, "pass1")
    assert not auth.has_admin(s)
    assert s.scalars(select(W)).all() == []
    assert backup.list_backups() == []
    reset_engine()


def test_invalid_backup_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("DPP_DATA_DIR", str(tmp_path))
    from dpp.db import init_db, reset_engine
    init_db(tmp_path / "dpp.sqlite3")
    bad = tmp_path / "bad.sqlite3"
    import sqlite3
    with sqlite3.connect(bad) as c:
        c.execute("CREATE TABLE x (a)")
    with pytest.raises(ValueError):
        backup.restore_backup(bad)
    reset_engine()
