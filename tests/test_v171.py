"""الإصدار 1.7.1: البرنامج يعمل حتى لو تعذّر تحميل OR-Tools."""
import pytest


def test_scheduler_unavailable_message(monkeypatch, seeded):
    db, ids = seeded
    from dpp.scheduler import engine as E
    monkeypatch.setattr(E, "cp_model", None)
    monkeypatch.setattr(E, "ORTOOLS_ERROR", "ImportError: DLL load failed")
    assert not E.available()
    with pytest.raises(E.SchedulerUnavailable) as ei:
        E.Scheduler(db)
    msg = str(ei.value)
    assert "ortools" in msg and ".libs" in msg and "DLL load failed" in msg


def test_timetables_import_without_engine():
    """services.timetables لا يستورد محرك OR-Tools عند التحميل (الاستيراد داخل الدوال)."""
    import importlib
    import dpp.services.timetables as T
    src = open(T.__file__, encoding="utf-8").read()
    assert "\nfrom ..scheduler.engine import" not in src
    importlib.reload(T)
