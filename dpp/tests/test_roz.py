import gzip
import zipfile
from pathlib import Path

from sqlalchemy import select

from dpp.importers.roz import parse_roz, week_number_from_filename
from dpp.models import Lesson, Section, Teacher
from dpp.services import roz_import

SAMPLE = Path(__file__).parent / "data" / "6.roz"


def test_parse_basic():
    d = parse_roz(SAMPLE)
    assert len(d.periods) == 7
    assert d.periods[5] == (13 * 60, 14 * 60)
    # L1 مزدوجة الأحد 08:00-10:00
    l1 = [e for e in d.entries if e.subject_id == "S1" and e.day == 0]
    assert len(l1) == 1 and (l1[0].start, l1[0].end) == (480, 600)
    # L2 بطاقتان متتاليتان تُدمجان
    l2 = [e for e in d.entries if e.subject_id == "S2"]
    assert len(l2) == 1 and l2[0].duration == 120
    # L3 مشتركة لفرعين
    l3 = [e for e in d.entries if e.subject_id == "S4"]
    assert {e.class_id for e in l3} == {"C1", "C2"} and all(e.day == 1 for e in l3)


def test_parse_compressed(tmp_path):
    raw = SAMPLE.read_bytes()
    gz = tmp_path / "7.roz"
    gz.write_bytes(gzip.compress(raw))
    assert len(parse_roz(gz).entries) == len(parse_roz(SAMPLE).entries)
    zp = tmp_path / "8.roz"
    with zipfile.ZipFile(zp, "w") as z:
        z.writestr("timetable.xml", raw)
    assert len(parse_roz(zp).entries) == len(parse_roz(SAMPLE).entries)
    utf16 = tmp_path / "9.roz"
    utf16.write_bytes(raw.decode("utf-8").replace('encoding="UTF-8"', 'encoding="UTF-16"').encode("utf-16"))
    assert len(parse_roz(utf16).entries) == len(parse_roz(SAMPLE).entries)


def test_week_number():
    assert week_number_from_filename("C:/x/6.roz") == 6
    assert week_number_from_filename("الأسبوع 12.roz") == 12


def test_import_and_revert(session, sample):
    t = sample["training"]
    rep = roz_import.import_roz(session, t, SAMPLE)
    assert rep.week_number == 6
    assert rep.lessons == 6
    assert rep.new_sections == []  # BMP1-A و BMP1-B موجودان
    lessons = list(session.scalars(select(Lesson)))
    assert all(l.origin == "import" for l in lessons)
    # الأستاذ بلا لقب منفصل يُحفظ باسمه الكامل
    assert session.scalar(select(Teacher).where(Teacher.last_name == "سعيدي كريم"))
    t1 = session.scalar(select(Teacher).where(Teacher.last_name == "بن علي"))
    assert sample["specialty"] in t1.specialties
    # تعديل ثم رجوع
    week = lessons[0].week
    session.delete(lessons[0])
    session.commit()
    assert len(week.lessons) == 5
    assert roz_import.revert_week(session, week) == 6
    assert session.query(Lesson).count() == 6
    # إعادة الاستيراد تستبدل ولا تكرر
    roz_import.import_roz(session, t, SAMPLE)
    assert session.query(Lesson).count() == 6


def test_import_unknown_classes(session, sample):
    raw = SAMPLE.read_text(encoding="utf-8").replace("BMP1-A", "BMP1-Z")
    rep = roz_import.import_roz(session, sample["training"], raw.encode("utf-8"), week_number=2)
    assert rep.new_sections == ["BMP1-Z"]
    sec = session.scalar(select(Section).where(Section.name == "BMP1-Z"))
    assert sec.specialty.name == roz_import.UNSORTED
