"""المجدول الآلي: ملء أسبوع بناءً على المقرر المتبقي والأساتذة السابقين مع احترام كل القواعد.

الخطوات لكل فرع:
1. المرحلة الحالية للأسبوع (تُتخطى العطل ومراحل الاستقبال بلا مقرر).
2. الحاجة الأسبوعية لكل مادة = المتبقي من المقرر ÷ الأسابيع المتبقية (مقربة لـ 30 د)، ناقص ما هو مبرمج يدوياً.
3. الأولوية للمواد الأكثر تأخراً. السعة اليومية = ساعات الدراسة للطور (7 سا).
4. الأستاذ = أستاذ آخر حصة لنفس المادة في نفس الفرع، وإلا أستاذ الاختصاص الذي يدرّس المادة.
5. الوضع: كتل (ساعتان افتراضياً، الرمي صبيحة 4 سا) في أول وقت ممكن دون تداخل للفرع أو الأستاذ
   (بالتاريخ الفعلي عبر كل التكوينات)، دون الغداء والأحداث والعطل، مع توزيع المادة على أيام مختلفة.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dpp.models import (FULL_DAY_KINDS, CurriculumItem, Event, Lesson, Section, Subject, Teacher, Training,
                        Week)
from dpp.services import planner, progress, structure
from dpp.services.timeutil import SLOT, overlaps


@dataclass
class Proposal:
    section: Section
    subject: Subject
    teacher: Teacher | None
    day: int
    start: int
    duration: int


@dataclass
class Need:
    section: Section
    subject: Subject
    minutes: int
    priority: float
    teacher: Teacher | None


@dataclass
class ScheduleResult:
    week: Week
    proposals: list[Proposal] = field(default_factory=list)
    unplaced: list[tuple[Section, Subject, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        mins = sum(p.duration for p in self.proposals)
        return (f"{len(self.proposals)} حصة ({mins / 60:g} سا)"
                + (f"، تعذر وضع {sum(u[2] for u in self.unplaced) / 60:g} سا" if self.unplaced else "")
                + (f"، {len(self.warnings)} تنبيه" if self.warnings else ""))


def _ceil_slot(minutes: float) -> int:
    return int(math.ceil(max(0.0, minutes) / SLOT) * SLOT)


def _round_slot(minutes: float) -> int:
    """تقريب لأقرب 30 د (30 د على الأقل إن بقي شيء)؛ الفروق تُستدرك في الأسابيع التالية."""
    if minutes <= 0:
        return 0
    return max(SLOT, int(round(minutes / SLOT)) * SLOT)


def pick_teacher(s: Session, section: Section, subject: Subject, before_week: int) -> Teacher | None:
    t = planner.previous_teacher(s, section, subject, before_week)
    if t:
        return t
    cands = [x for x in section.specialty.teachers if subject in x.subjects]
    if not cands:
        cands = [x for x in subject.teachers]
    return sorted(cands, key=lambda x: x.last_name)[0] if cands else None


def weekly_needs(s: Session, section: Section, week: Week, res: ScheduleResult) -> list[Need]:
    t: Training = section.training
    lv = section.level
    wn = week.number
    phase = structure.phase_for_week(t, wn, lv.id, section.specialty_id)
    if phase is None or phase.kind == "holiday":
        res.warnings.append(f"{section.name}: الأسبوع {wn} " + ("عطلة" if phase else "خارج المخطط الزمني"))
        return []
    week_start = week.start_date
    before = week_start - dt.timedelta(days=1)
    items = list(s.scalars(select(CurriculumItem).where(CurriculumItem.specialty_id == section.specialty_id)))
    if lv.curriculum_scope == "phase":
        items = [i for i in items if i.phase_id == phase.id]
        ph_start = t.week_start(phase.start_week)
        done = progress.done_minutes(s, section, before, ph_start)
        weeks_left = max(1, phase.end_week - wn + 1)
        hours: dict[int, tuple[Subject, float | None]] = {i.subject_id: (i.subject, i.hours) for i in items}
    else:
        done = progress.done_minutes(s, section, before)
        teaching = [p for p in structure.phases_for(t, lv.id, section.specialty_id) if p.kind != "holiday"]
        weeks_left = max(1, sum(max(0, p.end_week - max(wn, p.start_week) + 1) for p in teaching if p.end_week >= wn))
        hours = {}
        for i in items:
            subj, h = hours.get(i.subject_id, (i.subject, 0.0))
            hours[i.subject_id] = (subj, None if (h is None or i.hours is None) else h + i.hours)
    if not items:
        res.warnings.append(f"{section.name}: لا يوجد مقرر للمرحلة «{phase.name}»")
        return []
    # ما هو مبرمج أصلاً في هذا الأسبوع (يدوي/مستورد)
    fixed = defaultdict(int)
    for les in week.lessons:
        if les.section_id == section.id and les.subject_id and les.kind not in FULL_DAY_KINDS:
            fixed[les.subject_id] += les.duration
    needs = []
    for sid, (subj, h) in hours.items():
        if h is None:
            res.warnings.append(f"{section.name}: «{subj.name}» بلا حجم ساعي في المقرر")
            continue
        if subj.is_night:
            continue  # التدريب الليلي لا يُجدول في اليوم العادي
        remaining = h * 60 - done.get(sid, 0)
        if remaining <= 0:
            continue
        want = min(_round_slot(remaining / weeks_left), _ceil_slot(remaining)) - fixed.get(sid, 0)
        if want <= 0:
            continue
        needs.append(Need(section, subj, want, remaining / weeks_left / 60,
                          pick_teacher(s, section, subj, wn)))
    # السعة الأسبوعية
    days = [d for d in range(7) if d not in t.weekend_days]
    used = sum(x.duration for x in week.lessons if x.section_id == section.id and x.kind not in FULL_DAY_KINDS)
    full_days = {x.day for x in week.lessons if x.section_id == section.id and x.kind in FULL_DAY_KINDS}
    capacity = (len([d for d in days if d not in full_days]) * lv.study_minutes) - used
    total = sum(n.minutes for n in needs)
    if total > capacity > 0:
        ratio = capacity / total
        res.warnings.append(f"{section.name}: الحاجة ({total / 60:g} سا) تفوق السعة ({capacity / 60:g} سا) — توزيع نسبي")
        for n in needs:
            n.minutes = max(SLOT, int(n.minutes * ratio) // SLOT * SLOT)
    needs.sort(key=lambda n: -n.priority)
    for n in needs:
        if n.teacher is None:
            res.warnings.append(f"{section.name}: «{n.subject.name}» بلا أستاذ معروف — تُبرمج دون أستاذ")
    return needs


def chunks(minutes: int, subject: Subject, block: int) -> list[int]:
    if subject.is_shooting:
        block = max(block, 240)  # الرمي صبيحة
    out = []
    left = minutes
    while left > 0:
        c = min(left, block)
        if 0 < left - c < 60 and c + (left - c) <= 240:
            c = left  # لا نترك بقايا صغيرة
        out.append(c)
        left -= c
    return out


class Board:
    """حالة الانشغال في الذاكرة (الفروع والأساتذة والأحداث) للأسبوع المعني."""

    def __init__(self, s: Session, week: Week):
        self.week = week
        self.sec_busy: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        self.sec_study: dict[tuple[int, int], int] = defaultdict(int)
        self.subj_days: dict[tuple[int, int], set[int]] = defaultdict(set)
        self.teacher_busy: dict[tuple[int, int], list[tuple[int, int, int | None, bool]]] = defaultdict(list)
        self.events: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
        start = week.start_date
        for w in planner.overlapping_weeks(s, week):
            for les in w.lessons:
                date = (w.start_date + dt.timedelta(days=les.day)).toordinal()
                if les.teacher_id:
                    self.teacher_busy[(les.teacher_id, date)].append(
                        (les.start, les.end, les.subject_id, bool(les.subject and les.subject.allow_shared)))
                if w.id == week.id:
                    self.sec_busy[(les.section_id, les.day)].append((les.start, les.end))
                    if les.kind not in FULL_DAY_KINDS:
                        self.sec_study[(les.section_id, les.day)] += les.duration
                    if les.subject_id:
                        self.subj_days[(les.section_id, les.subject_id)].add(les.day)
        for ev in s.scalars(select(Event).where(Event.date >= start, Event.date <= start + dt.timedelta(days=6),
                                                Event.blocks_lessons.is_(True))):
            for sec in ev.sections:
                self.events[(sec.id, (ev.date - start).days)].append((ev.start, ev.end))

    def date(self, day: int) -> int:
        return (self.week.start_date + dt.timedelta(days=day)).toordinal()

    def fits(self, sec: Section, day: int, start: int, dur: int, subject: Subject, teacher: Teacher | None) -> bool:
        lv = sec.level
        end = start + dur
        if start < lv.day_start or end > lv.day_end:
            return False
        ls = sec.effective_lunch_start
        if lv.lunch_minutes and overlaps(start, end, ls, ls + lv.lunch_minutes):
            return False
        if any(overlaps(start, end, a, b) for a, b in self.sec_busy[(sec.id, day)]):
            return False
        if any(overlaps(start, end, a, b) for a, b in self.events[(sec.id, day)]):
            return False
        if self.sec_study[(sec.id, day)] + dur > lv.study_minutes:
            return False
        if teacher is not None:
            for a, b, sid, shared in self.teacher_busy[(teacher.id, self.date(day))]:
                if overlaps(start, end, a, b) and not (shared and subject.allow_shared and sid == subject.id):
                    return False
        return True

    def take(self, p: Proposal) -> None:
        self.sec_busy[(p.section.id, p.day)].append((p.start, p.start + p.duration))
        self.sec_study[(p.section.id, p.day)] += p.duration
        self.subj_days[(p.section.id, p.subject.id)].add(p.day)
        if p.teacher:
            self.teacher_busy[(p.teacher.id, self.date(p.day))].append(
                (p.start, p.start + p.duration, p.subject.id, p.subject.allow_shared))


def schedule_week(s: Session, training: Training, week_number: int, sections: list[Section] | None = None,
                  block: int = 120, replace_auto: bool = True, dry_run: bool = False) -> ScheduleResult:
    week = planner.get_week(s, training, week_number)
    sections = sections or structure.all_sections(s, training_id=training.id)
    if replace_auto:
        s.execute(delete(Lesson).where(Lesson.week_id == week.id, Lesson.origin == "auto",
                                       Lesson.section_id.in_([x.id for x in sections])))
        s.flush()
        s.expire(week)
    res = ScheduleResult(week)
    board = Board(s, week)
    days = [d for d in range(7) if d not in training.weekend_days]
    all_needs: list[Need] = []
    for sec in sections:
        all_needs.extend(weekly_needs(s, sec, week, res))
    # ترتيب عام: الأكثر تأخراً أولاً، ثم الكتل الكبيرة (الرمي) لتجد مكاناً
    all_needs.sort(key=lambda n: (-n.subject.is_shooting, -n.priority))
    rot = 0
    for need in all_needs:
        sec, subj = need.section, need.subject
        lv = sec.level
        for dur in chunks(need.minutes, subj, block):
            placed = False
            order = days[rot % len(days):] + days[:rot % len(days)]
            rot += 1
            for allow_same_day in (False, True):
                for day in order:
                    if not allow_same_day and day in board.subj_days[(sec.id, subj.id)]:
                        continue
                    t0 = lv.day_start
                    while t0 + dur <= lv.day_end:
                        if board.fits(sec, day, t0, dur, subj, need.teacher):
                            p = Proposal(sec, subj, need.teacher, day, t0, dur)
                            board.take(p)
                            res.proposals.append(p)
                            placed = True
                            break
                        t0 += SLOT
                    if placed:
                        break
                if placed:
                    break
            if not placed:
                # محاولة بكتلة أصغر
                if dur > 60:
                    half = dur // 2 // SLOT * SLOT
                    need2 = Need(sec, subj, dur, need.priority, need.teacher)
                    for d2 in (half, dur - half):
                        ok = False
                        for day in order:
                            t0 = lv.day_start
                            while t0 + d2 <= lv.day_end:
                                if board.fits(sec, day, t0, d2, subj, need2.teacher):
                                    p = Proposal(sec, subj, need2.teacher, day, t0, d2)
                                    board.take(p)
                                    res.proposals.append(p)
                                    ok = True
                                    break
                                t0 += SLOT
                            if ok:
                                break
                        if not ok:
                            res.unplaced.append((sec, subj, d2))
                else:
                    res.unplaced.append((sec, subj, dur))
    for sec, subj, mins in res.unplaced:
        res.warnings.append(f"{sec.name}: تعذر وضع {mins} د من «{subj.name}» (لا وقت/أستاذ متاح)")
    if dry_run:
        s.rollback()
        return res
    for p in res.proposals:
        s.add(Lesson(week_id=week.id, section_id=p.section.id, subject_id=p.subject.id,
                     teacher_id=p.teacher.id if p.teacher else None, day=p.day, start=p.start,
                     duration=p.duration, origin="auto"))
    s.commit()
    s.expire_all()
    return res
