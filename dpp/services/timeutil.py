"""أدوات الوقت: الدقائق ↔ نص، خطوات 30 دقيقة."""
from __future__ import annotations

SLOT = 30
MIN_DURATION = 30      # طلب Amine: من 30 دقيقة
MAX_DURATION = 4 * 60  # حتى 4 ساعات


def fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse(text: str) -> int:
    text = text.strip().replace(".", ":").replace("h", ":")
    if ":" in text:
        h, m = text.split(":", 1)
        return int(h) * 60 + int(m or 0)
    return int(text) * 60


def fmt_duration(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    if h and m:
        return f"{h} سا {m} د"
    if h:
        return f"{h} سا"
    return f"{m} د"


def duration_choices() -> list[int]:
    return list(range(MIN_DURATION, MAX_DURATION + 1, SLOT))


def snap(minutes: int, step: int = SLOT) -> int:
    return int(round(minutes / step) * step)


def overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end
