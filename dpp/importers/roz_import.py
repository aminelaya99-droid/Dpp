"""استيراد بيانات ملف .roz إلى قاعدة بيانات DPP مع معاينة وخيارات المطابقة."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from ..db.database import Database
from ..utils import make_abbrev, unique_abbrev
from .roz import RozData, split_rank

CATEGORY_HINTS = [("م م م", "م م م"), ("م م ش", "م م ش"), ("أ ت ج", "أ ت ج"), ("ا ت ج", "أ ت ج"),
                  ("توقيت جزئي", "أستاذ توقيت جزئي")]
GENERIC_TEACHERS = ("قائد", "دائرة", "مكتب", "أستاذ التربية", "سرية")


@dataclass
class ImportOptions:
    formation_id: int
    on_existing: str = "skip"      # skip | update
    import_subjects: bool = True
    import_teachers: bool = True
    import_rooms: bool = True
    import_classes: bool = True
    import_lessons: bool = True
    default_session_minutes: int = 120


@dataclass
class ImportReport:
    added: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = []
        for k in sorted(set(self.added) | set(self.updated) | set(self.skipped)):
            lines.append(f"{k}: أضيف {self.added[k]}، حُدّث {self.updated[k]}، تُجوهل {self.skipped[k]}")
        return "\n".join(lines + self.warnings)


def preview(data: RozData) -> dict:
    """معاينة قبل الاستيراد: الأعداد، أمثلة، المكررات، التحذيرات."""
    dup_subj = [n for n, c in Counter(s[0] for s in data.subjects).items() if c > 1]
    dup_teach = [n for n, c in Counter(t[0] for t in data.teachers).items() if c > 1]
    used_teachers = {t for l in data.lessons for t in l.teachers}
    generic = [t[0] for i, t in enumerate(data.teachers) if t[0].startswith(GENERIC_TEACHERS)]
    return {
        "summary": data.summary(),
        "examples": {
            "المواد": [s[0] for s in data.subjects[:5]],
            "الأساتذة": [t[0] for t in data.teachers[:5]],
            "الأقسام": [c[0] for c in data.classes[:5]],
            "القاعات": [r[0] for r in data.rooms],
        },
        "duplicates": {"المواد": dup_subj, "الأساتذة": dup_teach},
        "unused_teachers": len(data.teachers) - len(used_teachers),
        "generic_teachers": generic,
        "lessons_without_teacher": sum(1 for l in data.lessons if not l.teachers),
        "warnings": list(data.warnings),
    }


def _category_for(db: Database, rank: str, full: str) -> int | None:
    name = None
    for hint, cat in CATEGORY_HINTS:
        if hint in rank or hint in full:
            name = cat
            break
    if name is None and rank:
        name = "عسكري"
    if name is None:
        return None
    return db.scalar("SELECT id FROM teacher_categories WHERE name=?", (name,))


def import_roz(db: Database, data: RozData, opt: ImportOptions) -> ImportReport:
    rep = ImportReport()
    rep.warnings += data.warnings
    with db.tx():
        # ---------------- المواد
        subj_map: dict[int, int] = {}
        shorts = {r[0] for r in db.q("SELECT short FROM subjects WHERE short IS NOT NULL")}
        if opt.import_subjects or opt.import_lessons:
            for i, (name, short) in enumerate(data.subjects):
                ex = db.one("SELECT id FROM subjects WHERE name=?", (name,))
                if ex:
                    subj_map[i] = ex["id"]
                    if opt.on_existing == "update":
                        rep.updated["المواد"] += 1
                    else:
                        rep.skipped["المواد"] += 1
                    continue
                ab = unique_abbrev(make_abbrev(name if short == name else short), shorts)
                shorts.add(ab)
                subj_map[i] = db.insert("subjects", name=name, short=ab)
                rep.added["المواد"] += 1

        # ---------------- الأساتذة
        teach_map: dict[int, int] = {}
        if opt.import_teachers or opt.import_lessons:
            for i, (full, _short) in enumerate(data.teachers):
                rank, name = split_rank(full)
                ex = db.one("SELECT id FROM teachers WHERE full_name=? AND COALESCE(rank,'')=?", (name, rank))
                cat = _category_for(db, rank, full)
                if ex:
                    teach_map[i] = ex["id"]
                    if opt.on_existing == "update":
                        db.update("teachers", ex["id"], category_id=cat)
                        rep.updated["الأساتذة"] += 1
                    else:
                        rep.skipped["الأساتذة"] += 1
                    continue
                teach_map[i] = db.insert("teachers", full_name=name, rank=rank, category_id=cat)
                rep.added["الأساتذة"] += 1

        # ---------------- القاعات
        if opt.import_rooms:
            for name, short in data.rooms:
                if db.one("SELECT id FROM rooms WHERE name=?", (name,)):
                    rep.skipped["القاعات"] += 1
                    continue
                db.insert("rooms", name=name, short=short[:20])
                rep.added["القاعات"] += 1

        # ---------------- الأقسام والأفواج
        group_map: dict[int, int] = {}
        if opt.import_classes or opt.import_lessons:
            used = {g for l in data.lessons for g in l.groups}
            sec_shorts = {r[0] for r in db.q("SELECT short FROM sections WHERE formation_id=?", (opt.formation_id,))}
            for ci, (name, short, gl) in enumerate(data.classes):
                ex = db.one("SELECT id FROM sections WHERE formation_id=? AND name=?", (opt.formation_id, name))
                if ex:
                    sec_id = ex["id"]
                    rep.skipped["الأقسام"] += 1
                else:
                    base = short.upper() if short and short != name and len(short) <= 40 else make_abbrev(name)
                    ab = unique_abbrev(base, sec_shorts)
                    sec_shorts.add(ab)
                    sec_id = db.insert("sections", formation_id=opt.formation_id, name=name, short=ab)
                    rep.added["الأقسام"] += 1
                for k, gi in enumerate(gl):
                    if gi >= len(data.groups):
                        continue
                    whole = (k == 0)
                    if not whole and gi not in used:
                        continue   # لا نُنشئ مجموعات فرعية غير مستعملة في أي درس
                    gname = data.groups[gi] or ("الفوج الكامل" if whole else f"مجموعة {k}")
                    exg = db.one("SELECT id FROM groups_ WHERE section_id=? AND name=?", (sec_id, gname))
                    group_map[gi] = exg["id"] if exg else db.insert("groups_", section_id=sec_id, name=gname,
                                                                    is_whole=int(whole))
                    if not exg:
                        rep.added["الأفواج"] += 1

        # ---------------- الدروس -> المتطلبات + أهلية الأساتذة
        if opt.import_lessons:
            agg = defaultdict(int)
            skipped_events = Counter()
            for l in data.lessons:
                if l.subject not in subj_map:
                    continue
                if not l.teachers:
                    # دروس بلا أستاذ في aSc تمثل غالباً عطلاً أو امتحانات أو تربصات: لا تتحول إلى متطلبات
                    skipped_events[data.subjects[l.subject][0]] += 1
                    continue
                for g in l.groups:
                    if g not in group_map:
                        continue
                    t = teach_map.get(l.teachers[0]) if l.teachers else None
                    agg[(group_map[g], subj_map[l.subject], t)] += 1
                for t in l.teachers:
                    if t in teach_map:
                        db.execute("INSERT OR IGNORE INTO teacher_subjects VALUES (?,?)", (teach_map[t], subj_map[l.subject]))
            for (g, s, t), n in agg.items():
                ex = db.one("""SELECT id FROM requirements WHERE formation_id=? AND group_id=? AND subject_id=?
                               AND COALESCE(teacher_id,0)=COALESCE(?,0)""", (opt.formation_id, g, s, t))
                if ex:
                    rep.skipped["المتطلبات"] += 1
                    continue
                wh = n * opt.default_session_minutes / 60
                db.insert("requirements", formation_id=opt.formation_id, group_id=g, subject_id=s, teacher_id=t,
                          weekly_hours=wh, total_hours=0, session_minutes=opt.default_session_minutes)
                rep.added["المتطلبات"] += 1
            if skipped_events:
                rep.warnings.append(f"{sum(skipped_events.values())} درساً بلا أستاذ لم تُحوَّل إلى متطلبات "
                                    f"(أمثلة: {'، '.join(list(skipped_events)[:4])}). أضف العطل والامتحانات والتربصات "
                                    "كأحداث في الرزنامة.")
            rep.warnings.append("الحجم الساعي الأسبوعي للمتطلبات تقديري (عدد الدروس × المدة الافتراضية) "
                                "والحجم الساعي الكلي = 0؛ راجعهما قبل الجدولة.")
        db.log("استيراد ملف roz", "import", None, {k: v for k, v in rep.added.items()})
    return rep
