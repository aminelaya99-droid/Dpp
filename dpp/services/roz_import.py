"""استيراد أسابيع aSc إلى قاعدة البيانات مع حفظ النسخة الأصلية."""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from dpp.importers.roz import RozData, parse_roz, week_number_from_filename
from dpp.models import (ImportedLesson, Lesson, Level, Section, Specialty, Training, Week)
from dpp.services import catalog, structure
from dpp.services.textnorm import normalize

UNSORTED = "غير مصنف (مستورد)"


@dataclass
class ImportReport:
    week_number: int = 0
    lessons: int = 0
    new_sections: list[str] = field(default_factory=list)
    new_subjects: list[str] = field(default_factory=list)
    new_teachers: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = [f"الأسبوع {self.week_number}: {self.lessons} حصة"]
        if self.new_sections:
            parts.append(f"فروع جديدة: {len(self.new_sections)}")
        if self.new_subjects:
            parts.append(f"مواد جديدة: {len(self.new_subjects)}")
        if self.new_teachers:
            parts.append(f"أساتذة جدد: {len(self.new_teachers)}")
        if self.warnings:
            parts.append(f"تنبيهات: {len(self.warnings)}")
        return "، ".join(parts)


def _find_section(sections: list[Section], name: str, short: str) -> Section | None:
    keys = {normalize(name), normalize(short)} - {""}
    for sec in sections:
        if normalize(sec.name) in keys or (sec.code and normalize(sec.code) in keys):
            return sec
    return None


def _unsorted_specialty(s: Session, level: Level) -> Specialty:
    for sp in level.specialties:
        if sp.name == UNSORTED:
            return sp
    return structure.add_specialty(s, level, UNSORTED)


def import_roz(s: Session, training: Training, src, week_number: int | None = None,
               level: Level | None = None, data: RozData | None = None) -> ImportReport:
    """يستورد ملف .roz كأسبوع فعلي. إن كان الأسبوع موجوداً يُستبدل."""
    data = data or parse_roz(src)
    if week_number is None:
        week_number = week_number_from_filename(src) if not isinstance(src, (bytes, bytearray)) else None
    if not week_number:
        raise ValueError("تعذر تحديد رقم الأسبوع من اسم الملف؛ حدده يدوياً")
    rep = ImportReport(week_number=week_number, warnings=list(data.warnings))
    level = level or (training.levels[0] if training.levels else None)
    if level is None:
        raise ValueError("التكوين لا يحتوي على أي طور")

    week = structure.get_or_create_week(s, training, week_number)
    s.execute(delete(Lesson).where(Lesson.week_id == week.id))
    s.execute(delete(ImportedLesson).where(ImportedLesson.week_id == week.id))

    sections = structure.all_sections(s, training_id=training.id)
    sec_map: dict[str, Section] = {}
    for cid, (cname, cshort) in data.classes.items():
        sec = _find_section(sections, cname, cshort)
        if sec is None:
            sec = structure.add_section(s, _unsorted_specialty(s, level), cname or cshort, 0, cshort or cname)
            sections.append(sec)
            rep.new_sections.append(sec.name)
        sec_map[cid] = sec

    subj_created, teach_created = [], []
    subj_cache: dict[str, object] = {}
    for e in data.entries:
        sec = sec_map.get(e.class_id)
        if sec is None:
            rep.warnings.append(f"فرع غير معروف: {e.class_name}")
            continue
        subj = None
        if e.subject_name:
            subj = subj_cache.get(e.subject_id)
            if subj is None:
                short = data.subjects.get(e.subject_id, ("", ""))[1]
                subj = catalog.get_or_create_subject(s, e.subject_name, short, created=subj_created)
                subj_cache[e.subject_id] = subj
        teacher = None
        for tid in e.teacher_ids[:1]:
            rt = data.teachers.get(tid)
            if rt is None:
                continue
            last = rt.last_name or rt.name  # عند غياب اللقب يُحفظ الاسم كاملاً (قابل للتعديل)
            first = rt.first_name if rt.last_name else ""
            teacher = catalog.get_or_create_teacher(s, last, first, sec.specialty, created=teach_created)
            if not teacher.asc_id:
                teacher.asc_id = tid
            if subj is not None:
                catalog.link_teacher_subject(teacher, subj)
        if len(e.teacher_ids) > 1:
            rep.warnings.append(f"حصة بعدة أساتذة ({e.subject_name} / {e.class_name}): أُخذ الأول")
        note = f"فوج: {e.group_name}" if e.group_name else ""
        common = dict(section_id=sec.id, subject_id=subj.id if subj else None,
                      teacher_id=teacher.id if teacher else None, day=e.day, start=e.start,
                      duration=e.duration)
        s.add(Lesson(week_id=week.id, origin="import", note=note, **common))
        s.add(ImportedLesson(week_id=week.id, **common))
        rep.lessons += 1

    week.imported = True
    week.source_file = "" if isinstance(src, (bytes, bytearray)) else str(Path(str(src)).name)
    week.imported_at = dt.datetime.now()
    rep.new_subjects = [x.name for x in subj_created]
    rep.new_teachers = [x.last_name for x in teach_created]
    s.commit()
    return rep


def revert_week(s: Session, week: Week) -> int:
    """الرجوع إلى النسخة المستوردة الأصلية للأسبوع."""
    originals = list(s.scalars(select(ImportedLesson).where(ImportedLesson.week_id == week.id)))
    if not originals:
        raise ValueError("لا توجد نسخة مستوردة أصلية لهذا الأسبوع")
    s.execute(delete(Lesson).where(Lesson.week_id == week.id))
    for o in originals:
        s.add(Lesson(week_id=week.id, section_id=o.section_id, subject_id=o.subject_id,
                     teacher_id=o.teacher_id, day=o.day, start=o.start, duration=o.duration,
                     kind=o.kind, origin="import"))
    s.commit()
    s.expire_all()
    return len(originals)


def imported_weeks(s: Session) -> list[Week]:
    return list(s.scalars(select(Week).where(Week.imported.is_(True)).order_by(Week.training_id, Week.number)))
