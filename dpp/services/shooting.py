"""وحدة تدريب الرمي والأسلحة: حصص الرمي على مستوى الأفواج (لا نتائج لكل طالب)."""
from __future__ import annotations

import datetime as dt
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpp.models import Lesson, ShootingSession, Subject, Weapon, Week


def sessions_between(s: Session, start: dt.date, end: dt.date) -> list[ShootingSession]:
    q = select(ShootingSession).where(ShootingSession.date >= start, ShootingSession.date <= end)
    return list(s.scalars(q.order_by(ShootingSession.date, ShootingSession.start)))


def sync_from_week(s: Session, week: Week) -> int:
    """ينشئ حصص رمي من الحصص المبرمجة لمواد الرمي في الجدول الأسبوعي.
    الحصص المشتركة (نفس الأستاذ والوقت) تُجمع في حصة رمي واحدة بعدة أفواج."""
    groups: dict[tuple, list[Lesson]] = defaultdict(list)
    for les in week.lessons:
        if les.subject and les.subject.is_shooting:
            date = week.start_date + dt.timedelta(days=les.day)
            groups[(date, les.start, les.duration, les.teacher_id)].append(les)
    created = 0
    for (date, start, dur, teacher_id), lessons in groups.items():
        existing = s.scalar(select(ShootingSession).where(ShootingSession.date == date,
                                                          ShootingSession.start == start,
                                                          ShootingSession.teacher_id == teacher_id))
        sess = existing or ShootingSession(date=date, start=start, duration=dur, teacher_id=teacher_id)
        if existing is None:
            s.add(sess)
            created += 1
        for les in lessons:
            if les.section not in sess.sections:
                sess.sections.append(les.section)
    s.commit()
    return created


def ammo_summary(s: Session, start: dt.date | None = None, end: dt.date | None = None) -> list[dict]:
    q = select(ShootingSession)
    if start:
        q = q.where(ShootingSession.date >= start)
    if end:
        q = q.where(ShootingSession.date <= end)
    acc: dict[int | None, dict] = {}
    for x in s.scalars(q):
        key = x.weapon_id
        d = acc.setdefault(key, {"weapon": x.weapon.name if x.weapon else "غير محدد", "sessions": 0,
                                 "planned": 0, "used": 0, "sections": 0})
        d["sessions"] += 1
        d["planned"] += x.ammo_planned
        d["used"] += x.ammo_used
        d["sections"] += len(x.sections)
    return sorted(acc.values(), key=lambda d: d["weapon"])


def weapons(s: Session) -> list[Weapon]:
    return list(s.scalars(select(Weapon).order_by(Weapon.name)))
