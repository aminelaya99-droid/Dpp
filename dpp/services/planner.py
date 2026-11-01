"""عمليات المخطط الأسبوعي على قاعدة البيانات + ربطها بمحرك التعارضات."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpp.models import (FULL_DAY_KINDS, LESSON_NORMAL, ConflictIgnore, Event, Lesson, Section, Subject,
                        Teacher, Training, Week)
from dpp.services import settings as cfg
from dpp.services import structure
from dpp.services.conflicts import (Conflict, Context, EventBlock, Item, SectionRules, find_conflicts)
from dpp.services.timeutil import MAX_DURATION, MIN_DURATION, SLOT, overlaps


def lesson_date(lesson: Lesson) -> dt.date:
    return lesson.week.start_date + dt.timedelta(days=lesson.day)


def overlapping_weeks(s: Session, week: Week) -> list[Week]:
    """كل الأسابيع (من كل التكوينات) التي تتقاطع تواريخها مع هذا الأسبوع."""
    start = week.start_date
    out = []
    for w in s.scalars(select(Week)):
        if abs((w.start_date - start).days) < 7:
            out.append(w)
    return out


def to_item(lesson: Lesson) -> Item:
    subj = lesson.subject
    return Item(
        id=lesson.id, section_id=lesson.section_id, date=lesson_date(lesson).toordinal(), day=lesson.day,
        start=lesson.start, end=lesson.end, teacher_id=lesson.teacher_id, subject_id=lesson.subject_id,
        allow_shared=bool(subj and subj.allow_shared), is_night=bool(subj and subj.is_night),
        origin=lesson.origin, label=lesson_title(lesson), section_name=lesson.section.name,
        teacher_name=lesson.teacher.display_name if lesson.teacher else "")


def lesson_title(lesson: Lesson) -> str:
    from dpp.models import LESSON_KINDS
    if lesson.subject:
        return lesson.subject.name
    return LESSON_KINDS.get(lesson.kind, "حصة")


def section_rules(sec: Section) -> SectionRules:
    lv = sec.level
    return SectionRules(lv.day_start, lv.day_end, sec.effective_lunch_start, lv.lunch_minutes,
                        tuple(lv.training.weekend_days))


def build_context(s: Session, weeks: list[Week]) -> tuple[list[Item], Context]:
    items: list[Item] = []
    rules: dict[int, SectionRules] = {}
    lo = hi = None
    for w in weeks:
        for les in w.lessons:
            items.append(to_item(les))
            if les.section_id not in rules:
                rules[les.section_id] = section_rules(les.section)
        d0 = w.start_date
        lo = d0 if lo is None or d0 < lo else lo
        hi = d0 + dt.timedelta(days=6) if hi is None or d0 + dt.timedelta(days=6) > hi else hi
    events = []
    if lo:
        for ev in s.scalars(select(Event).where(Event.date >= lo, Event.date <= hi, Event.blocks_lessons.is_(True))):
            events.append(EventBlock(ev.id, ev.title, ev.date.toordinal(), ev.start, ev.end,
                                     frozenset(x.id for x in ev.sections)))
    ignored = set(s.scalars(select(ConflictIgnore.signature)))
    return items, Context(rules, events, ignored)


def week_conflicts(s: Session, week: Week, include_ignored: bool = False) -> list[Conflict]:
    weeks = overlapping_weeks(s, week)
    items, ctx = build_context(s, weeks)
    own = {les.id for les in week.lessons}
    return find_conflicts(items, ctx, only_ids=own, include_ignored=include_ignored)


def lesson_conflicts(s: Session, lessons: list[Lesson]) -> list[Conflict]:
    if not lessons:
        return []
    s.flush()
    weeks = overlapping_weeks(s, lessons[0].week)
    items, ctx = build_context(s, weeks)
    return find_conflicts(items, ctx, only_ids={x.id for x in lessons})


def ignore_conflicts(s: Session, conflicts: list[Conflict]) -> None:
    for c in conflicts:
        if s.scalar(select(ConflictIgnore).where(ConflictIgnore.signature == c.signature)) is None:
            s.add(ConflictIgnore(signature=c.signature))
    s.commit()


def default_duration(s: Session) -> int:
    return clamp_duration(cfg.get_int(s, "default_lesson_minutes", 60))


def clamp_duration(m: int) -> int:
    m = int(round(m / SLOT) * SLOT)
    return max(MIN_DURATION, min(MAX_DURATION, m))


def place_lesson(s: Session, week: Week, section: Section, day: int, start: int, subject: Subject | None,
                 teacher: Teacher | None = None, duration: int | None = None, kind: str = LESSON_NORMAL,
                 origin: str = "manual") -> Lesson:
    if kind in FULL_DAY_KINDS:
        lv = section.level
        start, duration = lv.day_start, lv.day_end - lv.day_start
    else:
        duration = clamp_duration(duration or default_duration(s))
    les = Lesson(week=week, section=section, day=day, start=start, duration=duration, subject=subject,
                 teacher=teacher, kind=kind, origin=origin)
    s.add(les)
    s.flush()
    return les


@dataclass
class Snapshot:
    """حالة حصة قبل التعديل (للتصحيح = التراجع)."""
    lesson_id: int
    values: dict | None  # None = كانت غير موجودة

    FIELDS = ("section_id", "day", "start", "duration", "teacher_id", "subject_id", "kind", "origin")

    @classmethod
    def of(cls, les: Lesson) -> "Snapshot":
        return cls(les.id, {f: getattr(les, f) for f in cls.FIELDS})

    def restore(self, s: Session) -> None:
        les = s.get(Lesson, self.lesson_id)
        if les is None:
            return
        if self.values is None:
            s.delete(les)
        else:
            for k, v in self.values.items():
                setattr(les, k, v)
        s.commit()
        s.expire_all()


def move_lesson(les: Lesson, section: Section, day: int, start: int) -> None:
    if les.kind in FULL_DAY_KINDS:
        start = section.level.day_start
    les.section = section
    les.section_id = section.id
    les.day, les.start = day, start
    if les.origin == "import":
        les.origin = "manual"


def set_duration(les: Lesson, minutes: int) -> None:
    les.duration = clamp_duration(minutes)
    if les.origin == "import":
        les.origin = "manual"


def teacher_busy(s: Session, week: Week, teacher: Teacher, day: int, start: int, end: int,
                 exclude_ids: set[int] | None = None, subject: Subject | None = None) -> list[Lesson]:
    """حصص الأستاذ المتداخلة مع الوقت المطلوب (بالتاريخ الفعلي، عبر كل التكوينات)."""
    date = week.start_date + dt.timedelta(days=day)
    exclude_ids = exclude_ids or set()
    out = []
    for w in overlapping_weeks(s, week):
        for les in w.lessons:
            if les.teacher_id != teacher.id or les.id in exclude_ids:
                continue
            if lesson_date(les) != date or not overlaps(les.start, les.end, start, end):
                continue
            if subject and subject.allow_shared and les.subject_id == subject.id:
                continue  # حصة مشتركة مسموحة
            out.append(les)
    return out


def previous_teacher(s: Session, section: Section, subject: Subject, before_week: int | None = None) -> Teacher | None:
    """أستاذ آخر حصة لهذه المادة في هذا الفرع (الأسابيع المستقبلية تحافظ على نفس الأساتذة)."""
    q = (select(Lesson).join(Week).where(Lesson.section_id == section.id, Lesson.subject_id == subject.id,
                                          Lesson.teacher_id.is_not(None)))
    if before_week is not None:
        q = q.where(Week.number <= before_week)
    q = q.order_by(Week.number.desc(), Lesson.day.desc(), Lesson.start.desc()).limit(1)
    les = s.scalar(q)
    return les.teacher if les else None


def free_starts(s: Session, week: Week, section: Section, day: int, duration: int,
                exclude_id: int | None = None, limit: int = 8) -> list[int]:
    """أوقات بداية مقترحة (خطوة 30 د) لا تتداخل مع حصص الفرع ولا الغداء."""
    lv = section.level
    busy = [(x.start, x.end) for x in week.lessons
            if x.section_id == section.id and x.day == day and x.id != exclude_id]
    ls = section.effective_lunch_start
    if lv.lunch_minutes:
        busy.append((ls, ls + lv.lunch_minutes))
    out = []
    t = lv.day_start
    while t + duration <= lv.day_end and len(out) < limit:
        if not any(overlaps(t, t + duration, a, b) for a, b in busy):
            out.append(t)
        t += SLOT
    return out


def day_study_minutes(week: Week, section_id: int, day: int) -> int:
    return sum(x.duration for x in week.lessons
               if x.section_id == section_id and x.day == day and x.kind not in FULL_DAY_KINDS)


def copy_week(s: Session, src: Week, dst: Week, sections: set[int] | None = None) -> int:
    n = 0
    for les in src.lessons:
        if sections and les.section_id not in sections:
            continue
        s.add(Lesson(week=dst, section_id=les.section_id, subject_id=les.subject_id, teacher_id=les.teacher_id,
                     day=les.day, start=les.start, duration=les.duration, kind=les.kind, origin="manual",
                     note=les.note))
        n += 1
    s.commit()
    return n


def get_week(s: Session, training: Training, number: int, create: bool = True) -> Week | None:
    if create:
        w = structure.get_or_create_week(s, training, number)
        s.commit()
        return w
    return s.scalar(select(Week).where(Week.training_id == training.id, Week.number == number))
