"""بطاقات «اليوم كاملاً» (اختبار، خفارة، خدمة، تمرين ميداني، وأي نوع يضيفه المستخدم) وبطاقة الغداء.

* الاختبار مادة دراسية (تُحسب في المقرر تحت بند «الامتحانات والتقييم» إن وُجد للطور).
* الخفارة والخدمة والتمرين الميداني غير دراسية: تشغل الوقت ولا تدخل في المنجز.
* القائمة محفوظة في الإعداد fullday_subjects (أرقام المواد بالترتيب).
"""
from __future__ import annotations

import json
from collections import Counter

from ..db.database import Database

KEY = "fullday_subjects"
DEFAULTS = [  # (الاسم، النوع، الفئة، اللون)
    ("اختبار", "teach", "general", "#E8A3A3"),
    ("خفارة", "nonteach", "nonteach", "#CDB89B"),
    ("خدمة", "nonteach", "nonteach", "#B6C6D8"),
    ("تمرين ميداني", "nonteach", "nonteach", "#A9CBA0"),
]
LUNCH_NAMES = ("وجبة الغذاء", "وجبة الغداء")


def _subject(db: Database, name: str, kind: str, cat: str, color: str) -> int:
    sid = db.scalar("SELECT id FROM subjects WHERE name=?", (name,))
    if sid:
        return sid
    from ..utils import make_abbrev
    short, k = make_abbrev(name), 1
    while db.scalar("SELECT 1 FROM subjects WHERE short=?", (short,)):
        k += 1
        short = f"{make_abbrev(name)}{k}"
    with db.tx():
        sid = db.insert("subjects", name=name, short=short, color=color, category=cat, kind=kind, shareable=1)
    return sid


def subjects(db: Database) -> list[int]:
    """أرقام مواد «اليوم كاملاً» بالترتيب (تُنشأ الافتراضية عند أول استعمال)."""
    try:
        ids = [int(x) for x in json.loads(db.get_setting(KEY, "") or "null") or []]
    except (ValueError, TypeError):
        ids = []
    if not db.get_setting(KEY, ""):
        ids = [_subject(db, *d) for d in DEFAULTS]
        db.set_setting(KEY, json.dumps(ids))
    have = {r[0] for r in db.q("SELECT id FROM subjects")}
    return [i for i in ids if i in have]


def add(db: Database, subject_id: int) -> None:
    ids = subjects(db)
    if subject_id not in ids:
        ids.append(subject_id)
        db.set_setting(KEY, json.dumps(ids))


def remove(db: Database, subject_id: int) -> None:
    ids = [i for i in subjects(db) if i != subject_id]
    db.set_setting(KEY, json.dumps(ids))


def is_full_day(db: Database, subject_id: int) -> bool:
    return subject_id in subjects(db)


def exam_subject(db: Database) -> int:
    return _subject(db, *DEFAULTS[0])


def lunch_subject(db: Database) -> int:
    for n in LUNCH_NAMES:
        sid = db.scalar("SELECT id FROM subjects WHERE name LIKE ?", (f"%{n}%",))
        if sid:
            return sid
    return _subject(db, "وجبة الغذاء", "nonteach", "nonteach", "#DDE4E6")


def bootstrap_exams(db: Database, force: bool = False) -> int:
    """يدرج مرة واحدة ساعات «الامتحانات والتقييم» من ملف المقرر المرفق كمقرر لمادة «اختبار»
    (الأسطر التي تجمع الامتحانات مع الاحتياطات لا تُحتسب لأنها لا تفصل بينهما). يعيد عدد الأسطر."""
    if db.get_setting("curriculum_exams_v1", "") == "1" and not force:
        return 0
    from ..importers import curriculum as CI
    path = CI.bundled_file()
    if not path or not db.scalar("SELECT COUNT(*) FROM levels WHERE code IS NOT NULL", (), 0):
        return 0
    try:
        blocks = CI.analyze(db, str(path))
    except Exception:
        return 0
    ex = exam_subject(db)
    vals: dict[tuple, Counter] = {}
    for b in blocks:
        if b.skip or not b.level_id:
            continue
        for r in b.rows:
            n = r.name
            if "متحان" in n and "تقييم" in n and "حتياط" not in n and r.hours:
                vals.setdefault((b.level_id, b.specialty_id or 0), Counter())[float(r.hours)] += 1
    n = 0
    with db.tx():
        for (lvl, spec), cnt in vals.items():
            hours = cnt.most_common(1)[0][0]
            if db.one("""SELECT id FROM curriculum WHERE level_id=? AND specialty_id=? AND subject_id=? AND phase='all'
                         AND source='manual'""", (lvl, spec, ex)):
                continue
            db.execute("""INSERT INTO curriculum(level_id, specialty_id, subject_id, phase, hours, source)
                          VALUES (?,?,?,'all',?,'import')
                          ON CONFLICT(level_id, specialty_id, subject_id, phase) DO UPDATE SET hours=excluded.hours""",
                       (lvl, spec, ex, hours))
            n += 1
    db.set_setting("curriculum_exams_v1", "1")
    return n
