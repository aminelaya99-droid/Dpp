from sqlalchemy import select

from dpp.models import Level, Training
from dpp.services import auth, structure


def test_seed_levels(session):
    codes = {lv.code for lv in session.scalars(select(Level))}
    assert {"BMP1", "BMP2", "ESOC 1", "ESOC 2", "OF-R", "ESO-R", "I-ESO-R", "I-HDT-R"} <= codes
    res = session.scalar(select(Training).where(Training.code == "RES"))
    kinds = [p.kind for p in res.phases]
    assert kinds == ["reception", "common", "holiday", "specialized"]


def test_admin_account(session):
    assert not auth.has_admin(session)
    auth.create_admin(session, "admin", "secret1")
    assert auth.has_admin(session)
    assert auth.authenticate(session, "admin", "secret1")
    assert auth.authenticate(session, "admin", "wrong") is None
    u = auth.admin(session)
    assert "secret1" not in u.password_hash


def test_tree_and_stats(sample, session):
    t = sample["training"]
    assert structure.training_stats(t) == (2, 49)
    assert t.week_start(1).isoformat() == "2026-09-13"
    sp2 = structure.add_specialty(session, sample["level"], "مشاة")
    structure.move_section(session, sample["b"], sp2)
    assert sample["b"].specialty is sp2


def test_phase_lookup(session):
    res = session.scalar(select(Training).where(Training.code == "RES"))
    assert structure.phase_for_week(res, 5).kind == "common"
    assert structure.phase_for_week(res, 8).kind == "holiday"
