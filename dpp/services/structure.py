"""عمليات شجرة التكوينات: تكوين → طور → اختصاص → فروع، والمخطط الزمني."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from dpp.models import (Level, Phase, Section, Specialty, Teacher, Training, Week)


def trainings(s: Session) -> list[Training]:
    return list(s.scalars(select(Training).order_by(Training.order, Training.id)))


def all_sections(s: Session, training_id: int | None = None, level_id: int | None = None) -> list[Section]:
    q = (select(Section).join(Specialty).join(Level).join(Training)
         .order_by(Training.order, Level.order, Specialty.order, Section.order, Section.name))
    if training_id:
        q = q.where(Level.training_id == training_id)
    if level_id:
        q = q.where(Specialty.level_id == level_id)
    return list(s.scalars(q))


def level_stats(level: Level) -> tuple[int, int]:
    secs = [sec for sp in level.specialties for sec in sp.sections]
    return len(secs), sum(x.headcount or 0 for x in secs)


def training_stats(t: Training) -> tuple[int, int]:
    n = h = 0
    for lv in t.levels:
        a, b = level_stats(lv)
        n += a
        h += b
    return n, h


def add_level(s: Session, training: Training, code: str, name: str) -> Level:
    lv = Level(training=training, code=code, name=name or code, order=len(training.levels))
    s.add(lv)
    s.commit()
    return lv


def add_specialty(s: Session, level: Level, name: str, code: str = "") -> Specialty:
    sp = Specialty(level=level, name=name, code=code, order=len(level.specialties))
    s.add(sp)
    s.commit()
    return sp


def add_section(s: Session, specialty: Specialty, name: str, headcount: int = 0, code: str = "") -> Section:
    sec = Section(specialty=specialty, name=name, code=code or name, headcount=headcount,
                  order=len(specialty.sections))
    s.add(sec)
    s.commit()
    return sec


def move_section(s: Session, section: Section, specialty: Specialty) -> None:
    section.specialty = specialty
    section.order = len(specialty.sections)
    s.commit()


def get_or_create_week(s: Session, training: Training, number: int) -> Week:
    w = s.scalar(select(Week).where(Week.training_id == training.id, Week.number == number))
    if w is None:
        w = Week(training=training, number=number)
        s.add(w)
        s.flush()
    return w


def current_week_number(training: Training, today: Optional[dt.date] = None) -> int:
    today = today or dt.date.today()
    return max(1, training.week_number_for(today))


def phases_for(training: Training, level_id: int | None = None, specialty_id: int | None = None) -> list[Phase]:
    """مراحل المخطط الزمني الخاصة بطور/اختصاص (الخاصة تتقدم على العامة لنفس الأسابيع)."""
    general = [p for p in training.phases if p.level_id is None and p.specialty_id is None]
    lvl = [p for p in training.phases if p.level_id == level_id and p.specialty_id is None] if level_id else []
    spc = [p for p in training.phases if p.specialty_id == specialty_id] if specialty_id else []
    result: list[Phase] = list(spc)
    for group in (lvl, general):
        for p in group:
            if not any(_overlap(p, q) for q in result):
                result.append(p)
    return sorted(result, key=lambda p: p.start_week)


def _overlap(a: Phase, b: Phase) -> bool:
    return a.start_week <= b.end_week and b.start_week <= a.end_week


def phase_for_week(training: Training, week_number: int, level_id: int | None = None,
                   specialty_id: int | None = None) -> Optional[Phase]:
    for p in phases_for(training, level_id, specialty_id):
        if p.contains(week_number):
            return p
    return None


def specialty_teachers(sp: Specialty) -> list[Teacher]:
    return sorted(sp.teachers, key=lambda t: t.last_name)


def count_sections(s: Session) -> int:
    return s.scalar(select(func.count(Section.id))) or 0
