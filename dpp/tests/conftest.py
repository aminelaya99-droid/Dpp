import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setenv("DPP_DATA_DIR", str(tmp_path))
    from dpp.db import init_db, reset_engine
    s = init_db(":memory:")
    yield s
    reset_engine()


@pytest.fixture
def sample(session):
    """تكوين BMP مع اختصاص وفرعين وأستاذين."""
    from sqlalchemy import select
    from dpp.models import Training
    from dpp.services import structure
    t = session.scalar(select(Training).where(Training.code == "BMP"))
    lv = t.levels[0]
    sp = structure.add_specialty(session, lv, "إشارة")
    a = structure.add_section(session, sp, "BMP1-A", 25)
    b = structure.add_section(session, sp, "BMP1-B", 24)
    return dict(training=t, level=lv, specialty=sp, a=a, b=b)



def pytest_sessionfinish(session, exitstatus):
    """تنظيف نوافذ Qt قبل إغلاق المفسر (يقلل انهيارات التفكيك على Windows)."""
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:
            for w in QApplication.topLevelWidgets():
                w.close()
                w.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
    except Exception:  # noqa: BLE001
        pass
