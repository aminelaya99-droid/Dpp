"""محرك التعارضات (منطق خالص قابل للاختبار).

القواعد:
- تعارض أستاذ: نفس الأستاذ، نفس التاريخ، وقتان متداخلان لفرعين مختلفين؛ إلا إذا كانت الحصتان
  لنفس المادة وهي من المواد المسموح فيها بالحصص المشتركة (الرمي، التربية البدنية، النظام المنظم، المحاضرات).
- تعارض فرع: حصتان متداخلتان لنفس الفرع (أنشطة اليوم الكامل تشغل اليوم كله).
- خارج أوقات اليوم، أثناء الغداء، في يوم العطلة، أثناء حدث يخص الفرع، تدريب ليلي في اليوم العادي.
- تعارضات الأسابيع المستوردة تُتجاهل: لا يُبلَّغ عن تعارض كل حصصه مستوردة.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

from dpp.services.timeutil import fmt, overlaps

TEACHER, SECTION, LUNCH, HOURS, WEEKEND, EVENT, NIGHT = (
    "teacher", "section", "lunch", "hours", "weekend", "event", "night")
KIND_LABELS = {
    TEACHER: "تعارض أستاذ", SECTION: "تعارض فرع", LUNCH: "وقت الغداء", HOURS: "خارج أوقات اليوم",
    WEEKEND: "يوم عطلة", EVENT: "تعارض مع حدث", NIGHT: "تدريب ليلي",
}


@dataclass(frozen=True)
class Item:
    """حصة مبسطة. date = الترتيب الزمني لليوم (date.toordinal())."""
    id: int
    section_id: int
    date: int
    day: int
    start: int
    end: int
    teacher_id: int | None = None
    subject_id: int | None = None
    allow_shared: bool = False
    is_night: bool = False
    origin: str = "manual"
    label: str = ""
    section_name: str = ""
    teacher_name: str = ""


@dataclass
class SectionRules:
    day_start: int = 8 * 60
    day_end: int = 16 * 60
    lunch_start: int | None = 12 * 60
    lunch_minutes: int = 60
    weekend_days: tuple[int, ...] = (5, 6)


@dataclass(frozen=True)
class EventBlock:
    id: int
    title: str
    date: int
    start: int
    end: int
    section_ids: frozenset


@dataclass
class Conflict:
    kind: str
    message: str
    lesson_ids: tuple[int, ...]
    extra: str = ""

    @property
    def signature(self) -> str:
        ids = ",".join(str(i) for i in sorted(self.lesson_ids))
        return f"{self.kind}:{ids}:{self.extra}"

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)


@dataclass
class Context:
    rules: dict[int, SectionRules] = field(default_factory=dict)
    events: list[EventBlock] = field(default_factory=list)
    ignored: set[str] = field(default_factory=set)


def _all_imported(*items: Item) -> bool:
    return all(i.origin == "import" for i in items)


def shared_allowed(a: Item, b: Item) -> bool:
    return (a.allow_shared and b.allow_shared and a.subject_id is not None
            and a.subject_id == b.subject_id)


def find_conflicts(items: list[Item], ctx: Context | None = None, only_ids: set[int] | None = None,
                   include_ignored: bool = False) -> list[Conflict]:
    """يعيد كل التعارضات؛ only_ids يحصرها في التي تمس حصصاً معينة."""
    ctx = ctx or Context()
    out: list[Conflict] = []

    def touch(*its: Item) -> bool:
        return only_ids is None or any(i.id in only_ids for i in its)

    # تعارضات ثنائية
    by_teacher: dict[tuple, list[Item]] = defaultdict(list)
    by_section: dict[tuple, list[Item]] = defaultdict(list)
    for it in items:
        if it.teacher_id is not None:
            by_teacher[(it.teacher_id, it.date)].append(it)
        by_section[(it.section_id, it.date)].append(it)

    for group in by_teacher.values():
        for a, b in combinations(sorted(group, key=lambda x: x.start), 2):
            if a.section_id == b.section_id or not overlaps(a.start, a.end, b.start, b.end):
                continue
            if shared_allowed(a, b) or _all_imported(a, b) or not touch(a, b):
                continue
            out.append(Conflict(TEACHER, f"الأستاذ {a.teacher_name or ''} مبرمج في {a.section_name} و{b.section_name} "
                                         f"في نفس الوقت ({fmt(max(a.start, b.start))})", (a.id, b.id)))
    for group in by_section.values():
        for a, b in combinations(sorted(group, key=lambda x: x.start), 2):
            if not overlaps(a.start, a.end, b.start, b.end) or _all_imported(a, b) or not touch(a, b):
                continue
            out.append(Conflict(SECTION, f"حصتان متداخلتان للفرع {a.section_name}: {a.label} و{b.label}",
                                (a.id, b.id)))

    # قواعد فردية
    for it in items:
        if it.origin == "import" or not touch(it):
            continue
        r = ctx.rules.get(it.section_id)
        if r:
            if it.day in r.weekend_days:
                out.append(Conflict(WEEKEND, f"{it.label} ({it.section_name}) في يوم عطلة", (it.id,)))
            if it.start < r.day_start or it.end > r.day_end:
                out.append(Conflict(HOURS, f"{it.label} ({it.section_name}) خارج أوقات اليوم "
                                           f"{fmt(r.day_start)}–{fmt(r.day_end)}", (it.id,)))
            if (r.lunch_start is not None and r.lunch_minutes and not it.is_night
                    and overlaps(it.start, it.end, r.lunch_start, r.lunch_start + r.lunch_minutes)
                    and (it.end - it.start) < (r.day_end - r.day_start)):
                out.append(Conflict(LUNCH, f"{it.label} ({it.section_name}) يتداخل مع الغداء "
                                           f"{fmt(r.lunch_start)}", (it.id,)))
            if it.is_night and r.day_start <= it.start < r.day_end:
                out.append(Conflict(NIGHT, f"{it.label}: التدريب الليلي لا يُجدول في اليوم العادي", (it.id,)))
        for ev in ctx.events:
            if (ev.date == it.date and it.section_id in ev.section_ids
                    and overlaps(it.start, it.end, ev.start, ev.end)):
                out.append(Conflict(EVENT, f"{it.label} ({it.section_name}) يتزامن مع الحدث «{ev.title}»",
                                    (it.id,), extra=f"e{ev.id}"))
    if not include_ignored:
        out = [c for c in out if c.signature not in ctx.ignored]
    return out
