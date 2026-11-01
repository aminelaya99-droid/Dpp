"""البيانات الأولية: التكوينات الثلاثة وأطوارها ومراحلها والمواد المشتركة."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpp.models import Level, Phase, Setting, Subject, Training, SUBJECT_MILITARY, SUBJECT_GENERAL

# الأسبوع 1 للتدريب الحالي: الأحد 13/09/2026
DEFAULT_START = dt.date(2026, 9, 13)

DEFAULT_SETTINGS = {
    "default_lesson_minutes": "60",
    "institution_name": "",
    "planner_layout": "days_rows",
    "auto_backup": "1",
}

SHARED_SUBJECTS = [
    # (الاسم، الاختصار، النوع، رمي؟)
    ("الرمي", "رمي", SUBJECT_MILITARY, True),
    ("التربية البدنية", "ت.ب", SUBJECT_MILITARY, False),
    ("النظام المنظم", "ن.م", SUBJECT_MILITARY, False),
    ("محاضرة", "محاضرة", SUBJECT_GENERAL, False),
]


def _training(code, name, cert, weeks, order, levels, phases) -> Training:
    t = Training(code=code, name=name, certificate_name=cert, start_date=DEFAULT_START,
                 weeks_count=weeks, order=order)
    t.weekend_days = [5, 6]  # الجمعة والسبت
    for i, lv in enumerate(levels):
        t.levels.append(Level(order=i, **lv))
    for ph in phases:
        t.phases.append(Phase(**ph))
    return t


def build_default_trainings() -> list[Training]:
    bmp = _training(
        "BMP", "الأهلية المهنية العسكرية", "شهادة الأهلية المهنية العسكرية", 36, 0,
        [dict(code="BMP1", name="BMP1 — السنة الأولى", day_end=16 * 60 + 30, curriculum_scope="training"),
         dict(code="BMP2", name="BMP2 — السنة الثانية", day_end=16 * 60 + 30, curriculum_scope="training")],
        [dict(name="السداسي الأول", kind="normal", start_week=1, weeks_count=18),
         dict(name="السداسي الثاني", kind="normal", start_week=19, weeks_count=18)],
    )
    esoc = _training(
        "ESOC", "شهادة العسكرية المهنية درجة ثانية", "شهادة العسكرية المهنية درجة ثانية", 32, 1,
        [dict(code="ESOC 1", name="ESOC 1 — الطلبة ضباط الصف المتعاقدون (سنة أولى)", day_end=16 * 60 + 30,
              has_night=True),
         dict(code="ESOC 2", name="ESOC 2 — الطلبة ضباط الصف المتعاقدون (سنة ثانية)", day_end=16 * 60 + 30)],
        [dict(name="المرحلة الأولى", kind="normal", start_week=1, weeks_count=16),
         dict(name="المرحلة الثانية", kind="normal", start_week=17, weeks_count=16)],
    )
    reserve = _training(
        "RES", "الاحتياط", "شهادة تكوين الاحتياط", 16, 2,
        [dict(code="OF-R", name="طالب ضابط احتياطي (OF-R)"),
         dict(code="ESO-R", name="طالب ضابط صف احتياط (ESO-R)"),
         dict(code="I-ESO-R", name="طالب ضابط صف احتياط عصاة (I-ESO-R)"),
         dict(code="I-HDT-R", name="طالب جندي احتياطي عصاة (I-HDT-R)")],
        [dict(name="الاستقبال", kind="reception", start_week=1, weeks_count=1),
         dict(name="التكوين القاعدي المشترك", kind="common", start_week=2, weeks_count=6),
         dict(name="عطلة", kind="holiday", start_week=8, weeks_count=1),
         dict(name="التكوين التخصصي", kind="specialized", start_week=9, weeks_count=8)],
    )
    return [bmp, esoc, reserve]


def seed_if_empty(s: Session) -> None:
    if s.scalar(select(Training.id).limit(1)) is None:
        for t in build_default_trainings():
            s.add(t)
        for name, short, kind, shooting in SHARED_SUBJECTS:
            s.add(Subject(name=name, short_name=short, kind=kind, allow_shared=True, is_shooting=shooting))
    for k, v in DEFAULT_SETTINGS.items():
        if s.get(Setting, k) is None:
            s.add(Setting(key=k, value=v))
    s.commit()
