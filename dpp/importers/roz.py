"""قارئ ملفات aSc Timetables (.roz).

البنية مستخرجة بالهندسة العكسية من ملف حقيقي (6.roz، الإصدار 702).
ما تم التحقق منه:
  * التوقيع: 4 بايت (رقم الإصدار little-endian) ثم بايت الطول 5 ثم 'ASCTT'.
  * الملف غير مضغوط، والنصوص Pascal ShortString (بايت طول + نص) بترميز Windows-1256.
  * كل سجل يبدأ برأس: index(int32) 00 01000000 type(int32) ... color ثم
    02000000 02000000 0200 0100 ثم معرّف 8 بايت ثم 7 أصفار وبايت.
  * أنواع السجلات المؤكدة: 8=أيام/فترات، 10=مستويات، 2=مواد، 1=أساتذة،
    6=أفواج (مجموعات)، 0=أقسام (CLASSTT)، 3=قاعات، 7=دروس (lessons).
  * الدرس: المادة عند الإزاحة 34 من نهاية الرأس، ثم قوائم (عدد + فهارس):
    الأفواج، الأساتذة، القاعات (10001/10002 = قيم خاصة بلا قاعة محددة).
  * البطاقات (cards = أماكن الحصص): بعد آخر درس، كل بطاقة تبدأ بـ
    lesson(int32) 01000000 FFFFFFFF ثم period(int32, يبدأ من 1) ثم extra(int32: عدد الفترات الإضافية)
    ثم 0 ثم قناع اليوم (الأحد=1، الإثنين=2 … السبت=64). تحقق منها بالمطابقة مع جداول مطبوعة.
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

TAIL = b"\x02\x00\x00\x00\x02\x00\x00\x00\x02\x00\x01\x00"
MARK = b"\x00\x01\x00\x00\x00"
ROOM_ANY = {10001, 10002}

TYPE_DAYPERIOD, TYPE_TEACHER, TYPE_SUBJECT, TYPE_ROOM = 8, 1, 2, 3
TYPE_GROUP, TYPE_LESSON, TYPE_GRADE, TYPE_CLASS = 6, 7, 10, 0


class RozError(Exception):
    pass


@dataclass
class RozLesson:
    index: int
    subject: int
    groups: list[int]
    teachers: list[int]
    rooms: list[int]
    duration_raw: int  # غير مؤكد


@dataclass
class RozCard:
    lesson: int
    period: int      # 1..n
    extra: int       # فترات إضافية: البطاقة تغطي period..period+extra
    day: int         # 0=الأحد … 6=السبت


@dataclass
class RozData:
    version: int
    days: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    subjects: list[tuple[str, str]] = field(default_factory=list)
    teachers: list[tuple[str, str]] = field(default_factory=list)
    rooms: list[tuple[str, str]] = field(default_factory=list)
    classes: list[tuple[str, str, list[int]]] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    lessons: list[RozLesson] = field(default_factory=list)
    cards: list[RozCard] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def group_class(self, g: int) -> int | None:
        for ci, (_, _, gl) in enumerate(self.classes):
            if g in gl:
                return ci
        return None

    def summary(self) -> dict:
        return {
            "الإصدار": self.version, "الأيام": len(self.days), "الفترات": len(self.periods),
            "المواد": len(self.subjects), "الأساتذة": len(self.teachers),
            "القاعات": len(self.rooms), "الأقسام": len(self.classes),
            "الأفواج": len(self.groups), "الدروس": len(self.lessons), "البطاقات": len(self.cards),
        }


def _i32(d: bytes, p: int) -> int:
    return struct.unpack_from("<i", d, p)[0]


def _pstr(d: bytes, p: int) -> tuple[str, int]:
    n = d[p]
    return d[p + 1:p + 1 + n].decode("cp1256", "replace").strip(), p + 1 + n


def check_signature(d: bytes) -> int:
    if len(d) < 16 or d[4:10] != b"\x05ASCTT":
        raise RozError("الملف لا يحمل توقيع ASCTT؛ ليس ملف aSc Timetables أو أنه تالف.")
    return _i32(d, 0)


def _records(d: bytes):
    """يعيد (type, index, body_start) لكل سجل.

    الرأس: index(int32) custom(pstr) 01000000 type(int32) count(int32) [tag pstr] color
    ثم 02000000 02000000 0200 0100 ثم معرّف 8 بايت ثم 7 أصفار وبايت.
    """
    for m in re.finditer(re.escape(TAIL), d):
        t = m.start()
        if d[t + 20:t + 27] != b"\x00" * 7:
            continue
        body = t + 28
        h = None
        if d[t - 15:t - 11] == b"\x01\x00\x00\x00" and _i32(d, t - 7) == 0 \
                and 0 <= _i32(d, t - 11) <= 20:
            h = t - 15
        else:
            for n in range(1, 120):
                s = t - 5 - n
                if s < 12:
                    break
                if d[s] == n and _i32(d, s - 4) == 1 and d[s - 12:s - 8] == b"\x01\x00\x00\x00" \
                        and 0 <= _i32(d, s - 8) <= 20:
                    h = s - 12
                    break
        if h is None:
            continue
        typ = _i32(d, h + 4)
        for n in range(0, 160):
            q = h - 1 - n
            if q < 4:
                break
            if d[q] == n and (n == 0 or all(b >= 0x20 for b in d[q + 1:h])):
                yield typ, _i32(d, q - 4), body
                break


def _first_name(d: bytes, body: int) -> str:
    for off in range(0, 14):
        n = d[body + off]
        if n >= 2:
            raw = d[body + off + 1: body + off + 1 + n]
            if all(b >= 0x20 and b != 0xFF for b in raw):
                return raw.decode("cp1256", "replace").strip()
    return ""


def parse_roz(data: bytes) -> RozData:
    version = check_signature(data)
    out = RozData(version=version)
    by_type: dict[int, dict[int, int]] = {}
    for typ, idx, body in _records(data):
        by_type.setdefault(typ, {}).setdefault(idx, body)

    def names(typ):
        res = []
        recs = by_type.get(typ, {})
        for idx in sorted(recs):
            a, p = _pstr(data, recs[idx])
            b, _ = _pstr(data, p)
            res.append((idx, a, b))
        return res

    # الأيام (سجلات النوع 8) ثم الفترات: أسماء السجلات في القسم الأول قبل جدول المستويات
    first_grade = min(by_type.get(TYPE_GRADE, {}).values(), default=90120) - 120
    for typ, idx, body in _records(data[:first_grade]):
        if typ == TYPE_DAYPERIOD:
            a = _first_name(data, body)
            if a and a not in out.days:
                out.days.append(a)
    for m in re.finditer(re.escape(TAIL), data[:first_grade]):
        t = m.start()
        if data[t + 20:t + 27] != b"\x00" * 7:
            continue
        a = _first_name(data, t + 28)
        if a and a not in out.days and a not in out.periods:
            out.periods.append(a)

    out.subjects = [(a, b or a) for _, a, b in names(TYPE_SUBJECT)]
    out.rooms = [(a, b or a) for _, a, b in names(TYPE_ROOM)]
    out.groups = [a for _, a, _ in names(TYPE_GROUP)]
    t = names(TYPE_TEACHER)
    out.teachers = [(a, b or a) for _, a, b in t]
    if t and [i for i, _, _ in t] != list(range(len(t))):
        out.warnings.append("فهارس الأساتذة غير متصلة؛ قد تكون بعض السجلات غير مقروءة.")

    # الأقسام: مرتكزة على وسم CLASSTT
    for m in re.finditer(rb"\x07CLASSTT", data):
        name, p = _pstr(data, m.start() + 8)
        short, p = _pstr(data, p)
        # الحقل المخصص "0|اختصار;" الذي يكتبه المستخدم في aSc يسبق رأس السجل
        win = data[max(0, m.start() - 260):m.start()]
        k = win.rfind(b"0|")
        if k >= 0 and b";" in win[k:]:
            code = win[k + 2:win.index(b";", k)].decode("cp1256", "replace").strip()
            if 0 < len(code) <= 40:
                short = code
        p += 1
        _ = _i32(data, p)  # حقل غير مفسر (3)
        n = _i32(data, p + 4)
        gl = [_i32(data, p + 8 + 4 * k) for k in range(n)] if 0 < n < 64 else []
        out.classes.append((name, short, gl))

    for idx, body in sorted(by_type.get(TYPE_LESSON, {}).items()):
        try:
            dur = _i32(data, body + 13)
            subj = _i32(data, body + 34)
            p = body + 38
            lists = []
            for _ in range(3):
                n = _i32(data, p)
                if not 0 <= n < 50:
                    raise ValueError("عدد غير منطقي")
                lists.append([_i32(data, p + 4 + 4 * k) for k in range(n)])
                p += 4 + 4 * n
            out.lessons.append(RozLesson(idx, subj, lists[0], lists[1],
                                         [r for r in lists[2] if r not in ROOM_ANY], dur))
        except (struct.error, ValueError) as e:
            out.warnings.append(f"تعذر قراءة الدرس {idx}: {e}")

    # تحقق الاتساق
    bad = [l.index for l in out.lessons if not (0 <= l.subject < len(out.subjects))
           or any(not 0 <= g < len(out.groups) for g in l.groups)
           or any(not 0 <= t_ < len(out.teachers) for t_ in l.teachers)]
    if bad:
        out.warnings.append(f"{len(bad)} درساً تشير إلى فهارس غير موجودة وسيتم تجاهلها.")
        out.lessons = [l for l in out.lessons if l.index not in set(bad)]
    lesson_bodies = by_type.get(TYPE_LESSON, {})
    if lesson_bodies:
        out.cards = _cards(data, max(lesson_bodies.values()), {l.index for l in out.lessons})
    return out


DAY_MASKS = {1 << k: k for k in range(7)}
CARD_MARK = b"\x01\x00\x00\x00\xff\xff\xff\xff"


def _cards(d: bytes, start: int, lessons: set[int]) -> list[RozCard]:
    """البطاقة تبدأ بعد نهاية السجل السابق (01000000 + 6 أصفار) بـ lesson(int32)، وأحياناً حقل إضافي int32،
    ثم 01000000 FFFFFFFF ثم period, extra, 0, day_mask."""
    out = []
    end10 = b"\x01\x00\x00\x00" + b"\x00" * 6
    for m in re.finditer(re.escape(CARD_MARK), d[start:]):
        p = start + m.start()
        if d[p - 14:p - 4] == end10:
            idx = _i32(d, p - 4)
        elif d[p - 18:p - 8] == end10:
            idx = _i32(d, p - 8)
        else:
            continue
        try:
            a, b, z, mask = struct.unpack_from("<iiii", d, p + 8)
        except struct.error:
            break
        if idx in lessons and 1 <= a <= 12 and 0 <= b <= 11 and z == 0 and mask in DAY_MASKS:
            out.append(RozCard(idx, a, b, DAY_MASKS[mask]))
    return out


def parse_roz_file(path: str) -> RozData:
    with open(path, "rb") as f:
        return parse_roz(f.read())


def split_rank(full: str) -> tuple[str, str]:
    """يفصل الرتبة/التصنيف عن الاسم في صيغة 'رتبة: الاسم'."""
    if ":" in full:
        a, b = full.split(":", 1)
        if len(a.strip()) <= 25 and b.strip():
            return a.strip(), b.strip()
    return "", full.strip()
