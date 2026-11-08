"""أدوات مساعدة: الوقت، التواريخ، الاختصارات."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

DAY_NAMES = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
STATUS_LABELS = {"planned": "مبرمجة", "done": "منجزة", "postponed": "مؤجلة", "cancelled": "ملغاة", "tray": "في الانتظار"}
ALLOWED_DURATIONS = [60, 90, 120, 150, 180, 210, 240]   # من 1 إلى 4 سا بخطوة 30 د + اليوم الكامل (0)
FULL_DAY = 0


def to_date(v) -> date:
    if isinstance(v, date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()


def iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def weekday_sun0(d: date) -> int:
    """رقم اليوم بحيث الأحد = 0 … السبت = 6."""
    return (d.weekday() + 1) % 7


def week_start(d) -> date:
    d = to_date(d)
    return d - timedelta(days=weekday_sun0(d))


def week_days(ws) -> list[date]:
    ws = to_date(ws)
    return [ws + timedelta(days=i) for i in range(7)]


def weeks_between(start, end) -> list[date]:
    s, e = week_start(start), to_date(end)
    out = []
    while s <= e:
        out.append(s)
        s += timedelta(days=7)
    return out


LRM = "\u200e"


def ltr(text: str) -> str:
    """يحافظ على ترتيب النص اللاتيني/الأرقام داخل سياق عربي (RTL)."""
    return LRM + str(text).replace(" ", LRM + " " + LRM).replace("–", LRM + "–" + LRM) + LRM


def hm_range(a: int, b: int) -> str:
    return ltr(f"{hm(a)}–{hm(b)}")


def hm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_hm(text: str) -> int:
    h, m = text.strip().split(":")
    return int(h) * 60 + int(m)


def fmt_hours(h: float) -> str:
    return f"{h:g}"


def parse_rest_days(s: str | None) -> set[int]:
    if not s:
        return set()
    return {int(x) for x in str(s).split(",") if x.strip().isdigit()}


# ---------------------------------------------------------------- الاختصارات
_STOP = {"de", "du", "des", "la", "le", "les", "et", "en", "d", "l", "a", "au", "aux", "pour",
         "في", "و", "من", "على", "إلى", "ال", "عن"}


_AR = re.compile(r"[\u0600-\u06FF]")


def make_abbrev(name: str, max_len: int = 12, spaced: bool = True) -> str:
    """يولّد اختصاراً من الحروف الأولى والأرقام.

    الحروف العربية تُفصل بفراغ حتى تُقرأ: 'كتابة الضبط' -> 'ك ا'، 'تقني تسخين وتبريد' -> 'ت ت و'.
    اللاتينية تبقى ملتصقة: 'Brevet Militaire Professionnel 2' -> 'BMP2'، 'ESOC 1 - C1' -> 'ESOC1-C1'
    """
    name = (name or "").strip()
    if not name:
        return ""
    parts = re.split(r"\s*[-–/]\s*", name)
    out = []
    for part in parts:
        tokens = re.findall(r"[A-Za-zÀ-ɏ]+|\d+|[؀-ۿ]+", part)
        piece = []
        for t in tokens:
            if t.isdigit():
                piece.append(t)
            elif t.lower() in _STOP:
                continue
            elif t.isupper() and len(t) <= 6:
                piece.append(t)
            else:
                piece.append(t[0].upper())
        if piece:
            out.append(_join_initials(piece, spaced))
    ab = "-".join(out)
    return ab[:max_len].strip() if ab else name[:max_len]


def _join_initials(piece: list[str], spaced: bool) -> str:
    if not spaced:
        return "".join(piece)
    s = ""
    for i, x in enumerate(piece):
        if i and (_AR.search(x) or _AR.search(piece[i - 1])):
            s += " "
        s += x
    return s


def space_arabic_initials(ab: str) -> str:
    """'فتم' -> 'ف ت م'، 'تم-أوب' -> 'ت م-أ و ب' (للاختصارات القديمة الملتصقة)."""
    return "-".join(" ".join(ch for ch in part) if part and all(_AR.match(ch) for ch in part) else part
                    for part in (ab or "").split("-"))


def unique_abbrev(base: str, existing: set[str]) -> str:
    if base not in existing:
        return base
    i = 2
    while f"{base}{i}" in existing or f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"
