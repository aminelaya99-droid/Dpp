import os
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from dpp.db.database import Database  # noqa: E402
from dpp.demo import seed  # noqa: E402

START = date(2026, 11, 1)   # أحد
ROZ = Path(os.environ.get("DPP_TEST_ROZ", ROOT / "tests" / "data" / "6.roz"))


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DPP_DATA_DIR", str(tmp_path / "data"))
    d = Database(tmp_path / "test.sqlite")
    yield d
    try:
        d.close()
    except Exception:
        pass


@pytest.fixture
def seeded(db):
    ids = seed(db, start=START, weeks=4)
    return db, ids


def overlaps(db, day=None):
    """يعيد قائمة التعارضات الفعلية بين الحصص المخزنة (أستاذ/قاعة/فوج ذري)."""
    from dpp.services.timetables import _group_units
    units = _group_units(db)
    rows = [dict(r) for r in db.q("""SELECT s.*, GROUP_CONCAT(sg.group_id) gids FROM sessions s
                                      LEFT JOIN session_groups sg ON sg.session_id=s.id
                                      WHERE s.status IN ('planned','done') GROUP BY s.id""")]
    bad = []
    for i, a in enumerate(rows):
        for b in rows[i + 1:]:
            if a["date"] != b["date"] or a["start_min"] >= b["end_min"] or b["start_min"] >= a["end_min"]:
                continue
            ta, tb = a["substitute_id"] or a["teacher_id"], b["substitute_id"] or b["teacher_id"]
            if ta and ta == tb:
                bad.append(("teacher", a["id"], b["id"]))
            if a["room_id"] and a["room_id"] == b["room_id"]:
                bad.append(("room", a["id"], b["id"]))
            ua = set().union(*[units[int(g)] for g in (a["gids"] or "").split(",") if g] or [set()])
            ub = set().union(*[units[int(g)] for g in (b["gids"] or "").split(",") if g] or [set()])
            if ua & ub:
                bad.append(("group", a["id"], b["id"]))
    return bad
