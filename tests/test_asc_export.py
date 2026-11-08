"""تصدير أسبوع إلى صيغة aSc (XML): الدورة الكاملة ‎.roz‎ ← DPP ← XML."""
from xml.etree import ElementTree as ET

from conftest import START

from dpp.exporters import asc_xml as AX
from dpp.scheduler.engine import Scheduler
from dpp.services import timetables as T


def _week(db, ids):
    res = Scheduler(db, time_limit=15).schedule_week(ids["formation"], START)
    T.save_result(db, ids["formation"], res)
    return res


def test_export_week_xml(seeded, tmp_path):
    db, ids = seeded
    res = _week(db, ids)
    out = tmp_path / AX.default_name(db, START)
    info = AX.export_week_xml(db, START, out)
    assert out.exists() and info["card"] > 0

    root = ET.parse(out).getroot()
    assert root.tag == "timetable"
    # البطاقات تساوي الحصص المحفوظة في الأسبوع
    saved = db.scalar("SELECT COUNT(*) FROM sessions s JOIN timetables t ON t.id=s.timetable_id "
                      "WHERE s.date BETWEEN ? AND ?",
                      (START.isoformat(), (START.replace(day=START.day + 6)).isoformat()), 0)
    assert info["card"] == saved == len(res.placements)

    # كل بطاقة تشير إلى درس موجود، وكل درس إلى مادة وأفواج موجودة
    lessons = {e.get("id"): e for e in root.findall("lessons/lesson")}
    subjects = {e.get("id") for e in root.findall("subjects/subject")}
    groups = {e.get("id") for e in root.findall("groups/group")}
    classes = {e.get("id") for e in root.findall("classes/class")}
    teachers = {e.get("id") for e in root.findall("teachers/teacher")}
    assert lessons and subjects and groups and classes
    for ln in lessons.values():
        assert ln.get("subjectid") in subjects
        for g in filter(None, ln.get("groupids", "").split(",")):
            assert g in groups
        for c in filter(None, ln.get("classids", "").split(",")):
            assert c in classes
        for t in filter(None, ln.get("teacherids", "").split(",")):
            assert t in teachers
    ndays = len(root.findall("daysdefs/daysdef")) - 1          # عدا «أي يوم»
    for card in root.findall("cards/card"):
        assert card.get("lessonid") in lessons
        assert int(card.get("period")) >= 1
        assert len(card.get("days")) == ndays and card.get("days").count("1") == 1


def test_export_filters_by_formation(seeded, tmp_path):
    db, ids = seeded
    _week(db, ids)
    other = db.execute("INSERT INTO formations(name, short) VALUES (?, ?)", ("تكوين آخر", "X"))
    out = tmp_path / "other.xml"
    info = AX.export_week_xml(db, START, out, formation_ids=[other])
    assert info["card"] == 0                                    # لا حصص لهذا التكوين
    info2 = AX.export_week_xml(db, START, tmp_path / "mine.xml", formation_ids=[ids["formation"]])
    assert info2["card"] > 0


def test_export_empty_week_is_valid(seeded, tmp_path):
    """أسبوع بلا حصص يُنتج ملفاً صالحاً (بلا بطاقات) لا استثناء."""
    db, _ids = seeded
    out = tmp_path / "empty.xml"
    info = AX.export_week_xml(db, START, out)
    assert info["card"] == 0
    assert ET.parse(out).getroot().tag == "timetable"


def test_export_tab_in_ui(seeded, tmp_path, monkeypatch):
    """تبويب «التصدير إلى aSc» يعمل من الواجهة ويكتب الملف فعلاً."""
    from PySide6.QtWidgets import QApplication, QFileDialog
    from dpp.ui.context import AppContext
    from dpp.ui.pages.import_page import ImportPage
    db, ids = seeded
    _week(db, ids)
    app = QApplication.instance() or QApplication([])
    page = ImportPage(AppContext(db))
    page.show()
    app.processEvents()
    from PySide6.QtCore import QDate
    page.exp_week.setDate(QDate(START.year, START.month, START.day))   # الأسبوع المجدول
    page.preview_export()
    assert "الحصص (البطاقات)" in page.exp_log.toPlainText()
    out = tmp_path / "ui.xml"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    page.do_export()
    assert out.exists() and "حُفظ الملف" in page.exp_log.toPlainText()
    page.close()
