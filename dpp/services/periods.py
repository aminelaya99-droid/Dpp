"""الفترات (الحصص) حسب الطور مع إمكانية تجاوزها للقسم.

ملف الفترات (profile) يحدد أوقات الحصص؛ الطور يحدد الملف وفترة الغداء، والقسم قد يتجاوزهما.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..db.database import Database


@dataclass(frozen=True)
class Period:
    idx: int
    label: str
    start: int
    end: int
    kind: str = "day"

    @property
    def minutes(self) -> int:
        return self.end - self.start


class PeriodMap:
    """ذاكرة مؤقتة لملفات الفترات وإعدادات الأقسام (تُحدَّث بـ reload)."""

    def __init__(self, db: Database):
        self.db = db
        self.reload()

    def reload(self):
        self.profiles: dict[str, list[Period]] = {}
        for r in self.db.q("SELECT * FROM periods ORDER BY profile, idx"):
            self.profiles.setdefault(r["profile"], []).append(
                Period(r["idx"], r["label"], r["start_min"], r["end_min"], r["kind"] or "day"))
        self.sec: dict[int, tuple[str, int]] = {}
        for r in self.db.q("""SELECT s.id, COALESCE(s.profile, l.profile, 'standard') prof,
                                     COALESCE(s.lunch_period, l.lunch_period, 3) lunch
                              FROM sections s LEFT JOIN levels l ON l.id=s.level_id"""):
            self.sec[r["id"]] = (r["prof"] if r["prof"] in self.profiles else "standard", r["lunch"])

    def periods(self, section_id: int | None = None, profile: str | None = None) -> list[Period]:
        if profile is None:
            profile = self.sec.get(section_id, ("standard", 3))[0]
        return self.profiles.get(profile) or self.profiles.get("standard", [])

    def lunch(self, section_id: int) -> int:
        return self.sec.get(section_id, ("standard", 3))[1]

    def max_periods(self) -> int:
        return max((len(v) for v in self.profiles.values()), default=5)

    def span_minutes(self, section_id: int, first: int, last: int) -> tuple[int, int] | None:
        ps = {p.idx: p for p in self.periods(section_id)}
        if first not in ps or last not in ps:
            return None
        return ps[first].start, ps[last].end

    def period_range(self, section_id: int, start: int, end: int) -> tuple[int, int] | None:
        """أول وآخر فترة تغطيها حصة [start, end) — أو None إن كانت خارج الفترات."""
        ps = self.periods(section_id)
        hit = [p.idx for p in ps if p.start < end and p.end > start]
        return (hit[0], hit[-1]) if hit else None


def set_profile_periods(db: Database, profile: str, rows: list[tuple[int, str, int, int, str]]):
    with db.tx():
        db.execute("DELETE FROM periods WHERE profile=?", (profile,))
        for idx, label, s, e, kind in rows:
            db.execute("INSERT INTO periods(profile, idx, label, start_min, end_min, kind) VALUES (?,?,?,?,?,?)",
                       (profile, idx, label, s, e, kind))
