"""التقدم: الساعات المنجزة لكل فرع × مادة مقابل المقرر (بغض النظر عن الأستاذ).

- تُحسب الحصص العادية والامتحانات فقط (الخفارة والخدمات والتمرين الميداني لا تُحسب).
- نسبة الإنجاز = المنجز / المقرر.
- التأخر = المتوقع حتى اليوم − المنجز، على المرحلة الحالية فقط.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpp.models import LESSON_EXAM, LESSON_NORMAL, CurriculumItem, Lesson, Phase, Section, Subject, Week
from dpp.services import structure

COUNTED_KINDS = (LESSON_NORMAL, LESSON_EXAM)


@dataclass
class Row:
    subject: Subject
    planned: float | None  # ساعات المقرر (None = ناقص)
    done: float            # منجز (كل الفترة المعنية)
    done_phase: float      # منجز خلال المرحلة الحالية
    expected: float        # المتوقع حتى اليوم (للمرحلة الحالية)
    delay: float           # موجب = متأخر

    @property
    def percent(self) -> float:
        if not self.planned:
            return 0.0
        return min(100.0, 100.0 * self.done / self.planned)

    @property
    def remaining(self) -> float:
        return max(0.0, (self.planned or 0) - self.done)


@dataclass
class SectionProgress:
    section: Section
    phase: Phase | None
    rows: list[Row]
    remaining_weeks: int
    phase_fraction: float

    @property
    def planned(self) -> float:
        return sum(r.planned or 0 for r in self.rows)

    @property
    def done(self) -> float:
        return sum(min(r.done, r.planned or r.done) for r in self.rows)

    @property
    def percent(self) -> float:
        return 100.0 * self.done / self.planned if self.planned else 0.0

    @property
    def delay(self) -> float:
        return sum(r.delay for r in self.rows)


def _phase_dates(training, phase: Phase) -> tuple[dt.date, dt.date]:
    start = training.week_start(phase.start_week)
    return start, start + dt.timedelta(days=7 * phase.weeks_count - 1)


def done_minutes(s: Session, section: Section, until: dt.date | None = None,
                 start: dt.date | None = None) -> dict[int, int]:
    """الدقائق المنجزة لكل مادة بين التاريخين (شاملين)."""
    out: dict[int, int] = {}
    q = (select(Lesson).join(Week).where(Lesson.section_id == section.id, Lesson.subject_id.is_not(None),
                                         Lesson.kind.in_(COUNTED_KINDS)))
    for les in s.scalars(q):
        d = les.week.start_date + dt.timedelta(days=les.day)
        if until and d > until:
            continue
        if start and d < start:
            continue
        out[les.subject_id] = out.get(les.subject_id, 0) + les.duration
    return out


def current_phase(section: Section, today: dt.date) -> Phase | None:
    t = section.training
    wn = structure.current_week_number(t, today)
    phases = [p for p in structure.phases_for(t, section.level.id, section.specialty_id) if p.kind != "holiday"]
    for p in phases:
        if p.contains(wn):
            return p
    past = [p for p in phases if p.end_week < wn]
    if past:
        return past[-1]
    return phases[0] if phases else None


def _fraction(training, phase: Phase, today: dt.date) -> float:
    a, b = _phase_dates(training, phase)
    if today < a:
        return 0.0
    if today >= b:
        return 1.0
    return ((today - a).days + 1) / ((b - a).days + 1)


def section_progress(s: Session, section: Section, today: dt.date | None = None) -> SectionProgress:
    today = today or dt.date.today()
    t = section.training
    lv = section.level
    phase = current_phase(section, today)
    items = list(s.scalars(select(CurriculumItem).where(CurriculumItem.specialty_id == section.specialty_id)))
    frac = _fraction(t, phase, today) if phase else 0.0
    phase_start, phase_end = _phase_dates(t, phase) if phase else (None, None)
    rows: list[Row] = []
    if lv.curriculum_scope == "phase":
        sel = [i for i in items if phase is not None and i.phase_id == phase.id]
        done_all = done_minutes(s, section, today, phase_start) if phase else {}
        for it in sel:
            done = done_all.get(it.subject_id, 0) / 60
            exp = (it.hours or 0) * frac
            rows.append(Row(it.subject, it.hours, done, done, exp, exp - done))
        remaining_weeks = max(0, phase.end_week - structure.current_week_number(t, today) + 1) if phase else 0
    else:
        teaching = [p for p in structure.phases_for(t, lv.id, section.specialty_id) if p.kind != "holiday"]
        total_weeks = sum(p.weeks_count for p in teaching) or t.weeks_count
        done_all = done_minutes(s, section, today)
        done_ph = done_minutes(s, section, today, phase_start) if phase else {}
        agg: dict[int, tuple[Subject, float | None]] = {}
        for it in items:
            subj, h = agg.get(it.subject_id, (it.subject, 0.0))
            agg[it.subject_id] = (subj, None if (h is None or it.hours is None) else h + it.hours)
        share = (phase.weeks_count / total_weeks) if phase else 0
        for sid, (subj, hours) in agg.items():
            done = done_all.get(sid, 0) / 60
            dph = done_ph.get(sid, 0) / 60
            exp = (hours or 0) * share * frac
            rows.append(Row(subj, hours, done, dph, exp, exp - dph))
        cw = structure.current_week_number(t, today)
        remaining_weeks = sum(max(0, min(p.end_week, 10 ** 6) - max(cw, p.start_week) + 1)
                              for p in teaching if p.end_week >= cw)
    rows.sort(key=lambda r: ({"military": 0, "specialized": 1}.get(r.subject.kind, 2), r.subject.name))
    return SectionProgress(section, phase, rows, remaining_weeks, frac)


def section_overall(s: Session, section: Section, today: dt.date | None = None) -> dict | None:
    p = section_progress(s, section, today)
    if not p.rows:
        return None
    return {"percent": p.percent, "planned": p.planned, "done": p.done, "delay": p.delay,
            "remaining_weeks": p.remaining_weeks}


def remaining_hours(s: Session, section: Section, today: dt.date | None = None) -> dict[int, float]:
    return {r.subject.id: round(r.remaining, 1) for r in section_progress(s, section, today).rows}
