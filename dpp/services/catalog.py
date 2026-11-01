"""المواد والأساتذة: البحث، الإنشاء، تخمين النوع، الربط بالاختصاصات."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpp.models import (SUBJECT_GENERAL, SUBJECT_MILITARY, SUBJECT_SPECIALIZED, Specialty, Subject,
                        Teacher)
from dpp.services.textnorm import normalize

MILITARY_KW = ["رمي", "سلاح", "اسلحه", "تكتيك", "طبوغراف", "نظام منظم", "تربيه بدنيه", "رياضه",
               "قتال", "ميدان", "حراسه", "عسكري", "انضباط", "خدمه داخليه", "اسعاف", "نووي", "حرب",
               "tir", "arme", "ttc", "eps", "topo", "tactique", "ordre serre"]
GENERAL_KW = ["لغه", "عربيه", "فرنسيه", "انجليزيه", "انكليزيه", "رياضيات", "فيزياء", "تاريخ",
              "جغرافيا", "تربيه اسلاميه", "تربيه مدنيه", "اعلام الي", "معلوماتيه", "ثقافه",
              "محاضره", "francais", "anglais", "math", "informatique"]
SHARED_KW = ["رمي", "تربيه بدنيه", "نظام منظم", "محاضره", "tir", "eps", "ordre serre", "conference"]
NIGHT_KW = ["ليلي", "nuit"]


def guess_kind(name: str) -> str:
    n = normalize(name)
    if any(k in n for k in MILITARY_KW):
        return SUBJECT_MILITARY
    if any(k in n for k in GENERAL_KW):
        return SUBJECT_GENERAL
    return SUBJECT_SPECIALIZED


def guess_shared(name: str) -> bool:
    n = normalize(name)
    return any(k in n for k in SHARED_KW)


def find_subject(s: Session, name: str) -> Subject | None:
    key = normalize(name)
    if not key:
        return None
    for subj in s.scalars(select(Subject)):
        if normalize(subj.name) == key or (subj.short_name and normalize(subj.short_name) == key):
            return subj
    return None


def get_or_create_subject(s: Session, name: str, short: str = "", kind: str | None = None,
                          created: list | None = None) -> Subject:
    subj = find_subject(s, name)
    if subj:
        return subj
    n = normalize(name)
    subj = Subject(name=name.strip(), short_name=short.strip(), kind=kind or guess_kind(name),
                   allow_shared=guess_shared(name), is_shooting="رمي" in n or "tir" in n,
                   is_night=any(k in n for k in NIGHT_KW))
    s.add(subj)
    s.flush()
    if created is not None:
        created.append(subj)
    return subj


def find_teacher(s: Session, last_name: str, first_name: str = "") -> Teacher | None:
    ln, fn = normalize(last_name), normalize(first_name)
    full = normalize(f"{last_name} {first_name}")
    for t in s.scalars(select(Teacher)):
        if normalize(t.last_name) == ln and (not fn or not t.first_name or normalize(t.first_name) == fn):
            return t
        if full and normalize(f"{t.last_name} {t.first_name}") == full:
            return t
    return None


def get_or_create_teacher(s: Session, last_name: str, first_name: str = "", specialty: Specialty | None = None,
                          created: list | None = None) -> Teacher:
    t = find_teacher(s, last_name, first_name)
    if t is None:
        t = Teacher(last_name=last_name.strip(), first_name=first_name.strip())
        s.add(t)
        s.flush()
        if created is not None:
            created.append(t)
    if specialty is not None and specialty not in t.specialties:
        t.specialties.append(specialty)
    return t


def link_teacher_subject(t: Teacher, subj: Subject) -> None:
    if subj not in t.subjects:
        t.subjects.append(subj)


def subjects(s: Session) -> list[Subject]:
    return list(s.scalars(select(Subject).order_by(Subject.kind, Subject.name)))


def teachers(s: Session) -> list[Teacher]:
    return list(s.scalars(select(Teacher).order_by(Teacher.last_name, Teacher.first_name)))


def subjects_for_section(s: Session, section) -> list[Subject]:
    """مواد الطور (العسكرية والعامة مشتركة) + تخصصية الاختصاص + المواد العامة غير المربوطة."""
    lv, sp = section.specialty.level_id, section.specialty_id
    out = []
    for subj in subjects(s):
        if subj.specialty_id and subj.specialty_id != sp:
            continue
        if subj.level_id and subj.level_id != lv:
            continue
        out.append(subj)
    return out
