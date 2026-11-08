"""نموذج «الجدول العام» (بدون واجهة): كل الأقسام لأسبوع واحد، الفحص الفوري، النقل، الشريط السفلي، التراجع.

يعمل في الذاكرة لأسبوع واحد (بضع مئات من الحصص) ويكتب كل عملية مباشرة في قاعدة البيانات داخل معاملة.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..db.database import Database
from ..utils import DAY_NAMES, hm, hm_range, iso, to_date, week_start
from . import conflicts as C
from .periods import PeriodMap


class GridError(Exception):
    pass


@dataclass
class Card:
    sid: int
    day: date
    start: int
    end: int
    subject: int
    sname: str
    sshort: str
    color: str
    category: str
    kind: str
    shareable: bool
    teacher: int | None
    tname: str
    room: int | None
    rname: str
    groups: set[int]
    sections: list[int]
    status: str
    imported: bool
    note: str
    requirement: int | None
    timetable: int | None
    tt_status: str = "draft"

    @property
    def minutes(self) -> int:
        return self.end - self.start

    @property
    def wd(self) -> int:
        return (self.day.weekday() + 1) % 7   # 0 = الأحد


@dataclass
class TrayItem:
    key: str
    section: int | None                 # None = بطاقة مادة حرة (تُوضع في أي قسم)
    subject: int
    sname: str
    sshort: str
    color: str
    category: str
    teacher: int | None
    tname: str
    minutes: int
    groups: set[int]
    sid: int | None = None              # حصة موضوعة في الانتظار
    requirement: int | None = None      # بطاقة جديدة من الحجم الساعي
    shareable: bool = False
    kind: str = "teach"
    free: bool = False
    history: int = 0                    # عدد مرات تدريس المادة للقسم في الأسابيع السابقة
    left_hours: float | None = None     # الباقي من المقرر (إن وُجد)
    pinned: bool = False                # بطاقة مثبتة في أول الشريط
    home: int | None = None             # القسم الذي أُنشئت له البطاقة (للاقتراحات)
    full_day: bool = False              # بطاقة «اليوم كاملاً» (اختبار، خفارة، خدمة…)


@dataclass
class SectionRow:
    id: int
    short: str
    name: str
    level_id: int | None
    level_code: str
    level_color: str
    level_name: str
    formation_id: int
    specialty: str


def week_number(db: Database, d) -> int:
    w1 = to_date(db.get_setting("week1_start", "2026-09-13") or "2026-09-13")
    return (week_start(d) - week_start(w1)).days // 7 + 1


def week_of_number(db: Database, n: int) -> date:
    w1 = week_start(to_date(db.get_setting("week1_start", "2026-09-13") or "2026-09-13"))
    return w1 + timedelta(days=7 * (n - 1))


class WeekGrid:
    def __init__(self, db: Database, ws, today: date | None = None):
        self.db = db
        self.today = today or date.today()
        self.undo_stack: list[dict] = []
        self.redo_stack: list[dict] = []
        self.set_week(ws)

    # ------------------------------------------------------------------ تحميل
    def set_week(self, ws):
        self.ws = week_start(to_date(ws))
        self.we = self.ws + timedelta(days=6)
        self.reload()

    def reload(self):
        db = self.db
        self.pm = PeriodMap(db)
        self.sections: list[SectionRow] = [SectionRow(
            r["id"], r["short"] or r["name"], r["name"], r["level_id"], r["code"] or "", r["lcolor"] or "#888888",
            r["lname"] or "", r["formation_id"], r["spec"] or "")
            for r in db.q("""SELECT s.*, l.code, l.color lcolor, l.name lname, sp.name spec FROM sections s
                             LEFT JOIN levels l ON l.id=s.level_id LEFT JOIN specialties sp ON sp.id=s.specialty_id
                             JOIN formations f ON f.id=s.formation_id WHERE f.archived=0
                             ORDER BY COALESCE(l.sort, 99), s.sort, s.id""")]
        self.sec_by_id = {s.id: s for s in self.sections}
        from .teachers import short_names
        self.tshort = short_names(db)          # اللقب (+ أول حرف من الاسم عند التشابه) لعرضه على البطاقات
        self.group_sec = {r[0]: r[1] for r in db.q("SELECT id, section_id FROM groups_")}
        self.whole_group = {r[0]: r[1] for r in db.q("SELECT section_id, id FROM groups_ WHERE is_whole=1")}
        self.units, _ = C._units(db)
        self.cards: dict[int, Card] = {}
        self.tray_cards: dict[int, Card] = {}
        groups = defaultdict(set)
        for r in db.q("""SELECT sg.session_id, sg.group_id FROM session_groups sg JOIN sessions s ON s.id=sg.session_id
                         WHERE s.date BETWEEN ? AND ?""", (iso(self.ws), iso(self.we))):
            groups[r[0]].add(r[1])
        for r in db.q("""SELECT s.*, sub.name sname, sub.short sshort, sub.color, COALESCE(sub.category,'specialty') cat,
                                COALESCE(sub.kind,'teach') kind, sub.shareable,
                                COALESCE(t2.full_name, t.full_name) tname, COALESCE(t2.rank, t.rank) trank,
                                rm.name rname, tt.status tts
                         FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                         LEFT JOIN teachers t ON t.id=s.teacher_id LEFT JOIN teachers t2 ON t2.id=s.substitute_id
                         LEFT JOIN rooms rm ON rm.id=s.room_id LEFT JOIN timetables tt ON tt.id=s.timetable_id
                         WHERE s.date BETWEEN ? AND ?""", (iso(self.ws), iso(self.we))):
            g = groups.get(r["id"], set())
            secs = sorted({self.group_sec[x] for x in g if x in self.group_sec},
                          key=lambda s: self.sections.index(self.sec_by_id[s]) if s in self.sec_by_id else 9999)
            tname = f"{r['trank']} {r['tname']}".strip() if r["tname"] else ""
            c = Card(r["id"], to_date(r["date"]), r["start_min"], r["end_min"], r["subject_id"], r["sname"],
                     r["sshort"] or r["sname"], r["color"] or "#CCCCCC", r["cat"], r["kind"], bool(r["shareable"]),
                     r["substitute_id"] or r["teacher_id"], tname, r["room_id"], r["rname"] or "", g, secs,
                     r["status"], bool(r["imported"]), r["note"] or "", r["requirement_id"], r["timetable_id"],
                     r["tts"] or "draft")
            (self.tray_cards if r["status"] == "tray" else self.cards)[c.sid] = c
        self.by_section = defaultdict(list)
        self.by_teacher = defaultdict(list)
        self.by_room = defaultdict(list)
        for c in self.cards.values():
            for s in c.sections:
                self.by_section[s].append(c)
            if c.teacher:
                self.by_teacher[c.teacher].append(c)
            if c.room:
                self.by_room[c.room].append(c)
        self.absent = defaultdict(set)
        self.absent_reason: dict[int, str] = {}
        for r in db.q("SELECT teacher_id, start_date, end_date, reason FROM absences WHERE end_date>=? AND start_date<=?",
                      (iso(self.ws), iso(self.we))):
            d = max(self.ws, to_date(r["start_date"]))
            self.absent_reason[r["teacher_id"]] = r["reason"] or "غياب"
            while d <= min(self.we, to_date(r["end_date"])):
                self.absent[r["teacher_id"]].add(d)
                d += timedelta(days=1)
        self.day_events: dict[tuple[int, date], list[tuple[str, str]]] = {}
        try:
            from .calendar import section_day_events
            self.day_events = section_day_events(db, self.ws, self.we, [s.id for s in self.sections])
        except Exception:
            self.day_events = {}
        self.refresh_conflicts()

    def refresh_conflicts(self):
        sess = [C._S(c.sid, iso(c.day), c.start, c.end, c.subject, c.sname, c.shareable, c.teacher, c.room,
                     set(c.groups)) for c in self.cards.values() if c.status in ("planned", "done")]
        self.conflicts = C.find_conflicts(self.db, self.ws, self.we, sess)
        # حصص أستاذ غائب بلا معوّض: تبقى في مكانها «بدون أستاذ» وتظهر بالأحمر
        ign = getattr(self, "_ignored_keys", None)
        if ign is None:
            try:
                ign = {r[0] for r in self.db.q("SELECT key FROM conflict_ignores")}
            except Exception:
                ign = set()
        for c in self.cards.values():
            if c.teacher and c.status == "planned" and c.day in self.absent.get(c.teacher, ()):
                key = f"absent|{c.teacher}|{iso(c.day)}|{c.start}|{c.subject}"
                self.conflicts.append(C.Conflict(
                    "teacher", key, [c.sid], iso(c.day),
                    f"الأستاذ في {self.absent_reason.get(c.teacher, 'غياب')} — الحصة بدون معوّض", key in ign,
                    c.tname))
        self.conflict_by_sid = C.conflicts_for_session([c for c in self.conflicts if not c.ignored])
        self.ignored_by_sid = C.conflicts_for_session([c for c in self.conflicts if c.ignored])

    # ------------------------------------------------------------------ مساعدات
    def days(self) -> list[date]:
        return [self.ws + timedelta(days=i) for i in range(7)]

    def teachers_rows(self, only_active=True) -> list[tuple[int, str]]:
        ids = set(self.by_teacher)
        rows = self.db.q("SELECT id, full_name, rank FROM teachers WHERE active=1 ORDER BY full_name")
        return [(r["id"], f"{r['rank'] or ''} {r['full_name']}".strip()) for r in rows if (r["id"] in ids or not only_active)]

    def rooms_rows(self) -> list[tuple[int, str]]:
        return [(r["id"], r["name"]) for r in self.db.q("SELECT id, name FROM rooms ORDER BY name") if r["id"] in self.by_room]

    def period_span(self, card: Card, section_id: int | None = None) -> tuple[int, int] | None:
        sec = section_id if section_id is not None else (card.sections[0] if card.sections else None)
        return self.pm.period_range(sec, card.start, card.end)

    def proposal(self, minutes: int, section_id: int, day_idx: int, period: int) -> tuple[date, int, int] | None:
        ps = {p.idx: p for p in self.pm.periods(section_id)}
        if period not in ps:
            return None
        p = ps[period]
        start = p.start
        end = start + minutes
        limit = p.end if p.kind == "night" else max(x.end for x in ps.values() if x.kind == "day")
        if end > limit:
            return None
        return self.ws + timedelta(days=day_idx), start, end

    def day_limit(self, section_id: int, start: int) -> int:
        """آخر دقيقة مسموحة لحصة تبدأ في start: نهاية آخر حصة نهارية، أو نهاية الفترة الليلية."""
        ps = self.pm.periods(section_id)
        night = [p for p in ps if p.kind == "night"]
        for p in night:
            if p.start <= start < p.end:
                return p.end
        return max((p.end for p in ps if p.kind == "day"), default=960)

    def day_start(self, section_id: int) -> int:
        ps = [p for p in self.pm.periods(section_id) if p.kind == "day"]
        return min((p.start for p in ps), default=480)

    def proposal_at(self, minutes: int, section_id: int, day_idx: int, start: int) -> tuple[date, int, int] | None:
        """اقتراح بوقت بداية حر (بخطوة 30 د)."""
        if start < self.day_start(section_id):
            return None
        end = start + minutes
        if end > self.day_limit(section_id, start):
            return None
        return self.ws + timedelta(days=day_idx), start, end

    # ------------------------------------------------------------------ الفحص الفوري
    def check(self, *, sections: list[int], groups: set[int], teacher: int | None, room: int | None, subject: int,
              shareable: bool, kind: str, day: date, start: int, end: int, ignore_sid: int | None = None) -> list[str]:
        out = []
        units = set().union(*(self.units.get(g, {g}) for g in groups)) if groups else set()
        seen = set()
        for s in sections:
            for c in self.by_section.get(s, []):
                if c.sid == ignore_sid or c.sid in seen or c.day != day or c.status not in ("planned", "done"):
                    continue
                if c.start < end and c.end > start and (units & c.groups):
                    seen.add(c.sid)
                    out.append(f"القسم {self.sec_by_id[s].short} مشغول: {c.sname} {hm_range(c.start, c.end)}")
            ev = self.day_events.get((s, day))
            if ev:
                out.append(f"القسم {self.sec_by_id[s].short}: {ev[0][0]} (اليوم كاملاً)")
            if kind != "nonteach" and s in self.sec_by_id:
                msg = self.lunch_room_msg(s, day, start, end, ignore_sid)
                if msg:
                    out.append(msg)
        if teacher:
            if day in self.absent.get(teacher, ()):
                out.append("الأستاذ غائب في هذا اليوم")
            for c in self.by_teacher.get(teacher, []):
                if c.sid == ignore_sid or c.sid in seen or c.day != day or c.status not in ("planned", "done"):
                    continue
                if c.start < end and c.end > start and not (c.subject == subject and shareable):
                    seen.add(c.sid)
                    out.append(f"الأستاذ مشغول: {c.sname} — {', '.join(self.sec_by_id[x].short for x in c.sections if x in self.sec_by_id)} "
                               f"{hm_range(c.start, c.end)}")
        if room:
            for c in self.by_room.get(room, []):
                if c.sid == ignore_sid or c.sid in seen or c.day != day or c.status not in ("planned", "done"):
                    continue
                if c.start < end and c.end > start and not (c.subject == subject and shareable):
                    out.append(f"القاعة مشغولة: {c.sname} {hm_range(c.start, c.end)}")
        return out

    def lunch_room_msg(self, section_id: int, day: date, start: int, end: int, ignore_sid=None) -> str | None:
        """وقت الغداء غير ثابت: اليوم = ساعات دراسة + ساعة غداء في أي مكان. إذا لم توجد بطاقة غداء في اليوم،
        يكفي أن تبقى بعد الوضع ساعة متصلة فارغة داخل اليوم للغداء."""
        cards = [c for c in self.by_section.get(section_id, []) if c.day == day and c.sid != ignore_sid
                 and c.status in ("planned", "done")]
        if any(c.kind == "nonteach" and ("غذاء" in c.sname or "غداء" in c.sname) for c in cards):
            return None
        if any(c.end - c.start >= self.day_limit(section_id, self.day_start(section_id)) - self.day_start(section_id)
               for c in cards):
            return None                                   # يوم كامل (اختبار، خفارة…) يغطي الغداء
        d0, d1 = self.day_start(section_id), self.day_limit(section_id, self.day_start(section_id))
        if start >= d1 or end <= d0 or (start <= d0 and end >= d1):
            return None                                   # الفترة الليلية لا تمس الغداء، واليوم الكامل يغطيه
        busy = sorted([(c.start, c.end) for c in cards if c.start < d1 and c.end > d0] + [(start, end)])
        t, gap = d0, 0
        for a, b in busy:
            gap = max(gap, a - t)
            t = max(t, b)
        gap = max(gap, d1 - t)
        if gap < 60:
            return f"لا تبقى ساعة للغداء في يوم القسم {self.sec_by_id[section_id].short}"
        return None

    def full_day_range(self, section_id: int) -> tuple[int, int]:
        s = self.day_start(section_id)
        return s, self.day_limit(section_id, s)

    def day_cards(self, section_id: int, day: date, exclude_sid=None) -> list[Card]:
        """حصص القسم في اليوم (النهارية) التي تتعارض مع «اليوم كاملاً»."""
        s, e = self.full_day_range(section_id)
        return [c for c in self.by_section.get(section_id, []) if c.day == day and c.sid != exclude_sid
                and c.status in ("planned", "done") and c.start < e and c.end > s]

    # ------------------------------------------------------------------ تجميع عمليات في خطوة تراجع واحدة
    def begin_group(self):
        self._group_mark = len(self.undo_stack)

    def end_group(self, label: str):
        mark = getattr(self, "_group_mark", None)
        self._group_mark = None
        if mark is None:
            return
        acts = self.undo_stack[mark:]
        if len(acts) > 1:
            del self.undo_stack[mark:]
            self.undo_stack.append({"op": "group", "acts": acts, "label": label})

    def check_card(self, card: Card, day: date, start: int, end: int) -> list[str]:
        return self.check(sections=card.sections, groups=card.groups, teacher=card.teacher, room=card.room,
                          subject=card.subject, shareable=card.shareable, kind=card.kind, day=day, start=start,
                          end=end, ignore_sid=card.sid)

    def check_tray(self, item: TrayItem, day: date, start: int, end: int) -> list[str]:
        return self.check(sections=[item.section], groups=item.groups, teacher=item.teacher, room=None,
                          subject=item.subject, shareable=item.shareable, kind=item.kind, day=day, start=start,
                          end=end, ignore_sid=item.sid)

    def check_free(self, item: TrayItem, section_id: int, day: date, start: int, end: int,
                   teacher: int | None = None) -> list[str]:
        g = self.whole_group.get(section_id)
        return self.check(sections=[section_id], groups={g} if g else set(), teacher=teacher, room=None,
                          subject=item.subject, shareable=item.shareable, kind=item.kind, day=day, start=start,
                          end=end)

    def checker_for(self, item, section_id: int):
        if isinstance(item, Card):
            return lambda d, s, e: self.check_card(item, d, s, e)
        if item.free:
            return lambda d, s, e: self.check_free(item, section_id, d, s, e)
        return lambda d, s, e: self.check_tray(item, d, s, e)

    def row_validity(self, minutes: int, section_id: int, checker, days: list[int], periods: list[int]):
        """{(day_idx, period): (ok, messages)} لتلوين الخانات بالأخضر/الأحمر."""
        out = {}
        for di in days:
            for p in periods:
                prop = self.proposal(minutes, section_id, di, p)
                if prop is None:
                    out[(di, p)] = (False, ["خارج فترات اليوم"])
                    continue
                msgs = checker(*prop)
                out[(di, p)] = (not msgs, msgs)
        return out

    # ------------------------------------------------------------------ الشريط السفلي
    def tray_items(self, section_ids: list[int] | None = None, include_requirements=True) -> list[TrayItem]:
        secs = set(section_ids) if section_ids else {s.id for s in self.sections}
        out = []
        for c in self.tray_cards.values():
            for s in c.sections[:1]:
                if s in secs:
                    out.append(TrayItem(f"t{c.sid}", s, c.subject, c.sname, c.sshort, c.color, c.category, c.teacher,
                                        c.tname, c.minutes, set(c.groups), sid=c.sid, requirement=c.requirement,
                                        shareable=c.shareable, kind=c.kind))
        if not include_requirements:
            return out
        imported_secs = {s for c in self.cards.values() if c.imported for s in c.sections}
        sched = defaultdict(int)
        for c in list(self.cards.values()) + list(self.tray_cards.values()):
            if c.status in ("planned", "done", "tray"):
                for g in c.groups:
                    sched[(g, c.subject)] += c.minutes
        rows = self.db.q("""SELECT r.*, sub.name sname, sub.short sshort, sub.color, COALESCE(sub.category,'specialty') cat,
                                   sub.shareable, t.full_name tname, t.rank trank, g.section_id
                            FROM requirements r JOIN subjects sub ON sub.id=r.subject_id JOIN groups_ g ON g.id=r.group_id
                            LEFT JOIN teachers t ON t.id=r.teacher_id WHERE r.weekly_hours>0""")
        for r in rows:
            s = r["section_id"]
            if s not in secs or s in imported_secs:
                continue
            rem = int(round(r["weekly_hours"] * 60)) - sched[(r["group_id"], r["subject_id"])]
            rem = int(rem // 30 * 30)
            dur = r["session_minutes"] or 120
            k = 0
            while rem >= 60:
                m = min(dur, rem)
                if rem - m < 60 and rem - m > 0:
                    m = rem if rem <= 240 else m
                out.append(TrayItem(f"r{r['id']}-{k}", s, r["subject_id"], r["sname"], r["sshort"] or r["sname"],
                                    r["color"] or "#CCC", r["cat"], r["teacher_id"],
                                    f"{r['trank'] or ''} {r['tname'] or ''}".strip(), m, {r["group_id"]},
                                    requirement=r["id"], shareable=bool(r["shareable"])))
                rem -= m
                k += 1
        return out

    # ------------------------------------------------------------------ بطاقات المواد الحرة
    def subject_history(self, section_id: int | None) -> dict[int, dict]:
        """{subject_id: {n, minutes(المدة المعتادة), teachers{tid: n}}} من كل الحصص السابقة للقسم."""
        out: dict[int, dict] = {}
        if not section_id:
            return out
        rows = self.db.q("""SELECT s.subject_id, s.end_min-s.start_min m, COALESCE(s.substitute_id, s.teacher_id) t
                            FROM sessions s JOIN session_groups sg ON sg.session_id=s.id JOIN groups_ g ON g.id=sg.group_id
                            WHERE g.section_id=? AND s.status IN ('planned','done') AND s.date<?""",
                         (section_id, iso(self.ws + timedelta(days=7))))
        for r in rows:
            h = out.setdefault(r["subject_id"], {"n": 0, "durs": defaultdict(int), "teachers": defaultdict(int)})
            h["n"] += 1
            h["durs"][r["m"]] += 1
            if r["t"]:
                h["teachers"][r["t"]] += 1
        for h in out.values():
            h["minutes"] = max(h["durs"].items(), key=lambda kv: kv[1])[0]
        return out

    def subject_items(self, section_id: int | None = None, only_section=False, history_first=True,
                      search: str = "", include_nonteach=False, left: dict[int, float] | None = None) -> list[TrayItem]:
        hist = self.subject_history(section_id)
        cur_subjects: set[int] = set()
        if section_id:
            sec = self.sec_by_id.get(section_id)
            if sec and sec.level_id:
                cur_subjects = {r[0] for r in self.db.q(
                    "SELECT subject_id FROM curriculum WHERE level_id=? AND specialty_id IN (0, COALESCE(?,0)) AND hours>0",
                    (sec.level_id, self.db.scalar("SELECT specialty_id FROM sections WHERE id=?", (section_id,))))}
            cur_subjects |= {r[0] for r in self.db.q("""SELECT DISTINCT r.subject_id FROM requirements r JOIN groups_ g
                                                       ON g.id=r.group_id WHERE g.section_id=?""", (section_id,))}
        own = set(hist) | cur_subjects
        q = search.strip()
        try:
            default_m = int(self.db.get_setting("default_minutes", "120") or 120)
        except ValueError:
            default_m = 120
        out = []
        for r in self.db.q("""SELECT id, name, short, color, COALESCE(category,'specialty') cat, COALESCE(kind,'teach') kind,
                                     shareable FROM subjects ORDER BY name"""):
            if r["kind"] == "nonteach" and not include_nonteach:
                continue
            if q and q not in r["name"] and q not in (r["short"] or ""):
                continue
            if only_section and section_id and r["id"] not in own and not q:
                continue
            h = hist.get(r["id"], {})
            out.append(TrayItem(f"f{r['id']}", None, r["id"], r["name"], r["short"] or r["name"], r["color"] or "#CCC",
                                r["cat"], None, "", h.get("minutes") or default_m, set(), shareable=bool(r["shareable"]),
                                kind=r["kind"], free=True, history=h.get("n", 0),
                                left_hours=(left or {}).get(r["id"])))
        if history_first:
            out.sort(key=lambda it: (-(it.history > 0), -it.history, it.sname))
        return out

    def teacher_candidates(self, section_id: int, subject_id: int, day: date | None = None, start: int = 0,
                           end: int = 0) -> list[dict]:
        """الأساتذة مرتبين: من درّس المادة لهذا القسم، ثم المؤهلون للمادة (اختصاص القسم أولاً)، ثم البقية."""
        hist = self.subject_history(section_id).get(subject_id, {}).get("teachers", {})
        qualified = {r[0] for r in self.db.q("SELECT teacher_id FROM teacher_subjects WHERE subject_id=?", (subject_id,))}
        spec = (self.sec_by_id[section_id].specialty if section_id in self.sec_by_id else "") or ""
        out = []
        for r in self.db.q("SELECT id, full_name, rank, specialty FROM teachers WHERE active=1 ORDER BY full_name"):
            tid = r["id"]
            if tid in hist:
                grp, order = "history", -hist[tid]
            elif tid in qualified:
                same = bool(spec and r["specialty"] and (r["specialty"] in spec or spec in r["specialty"]))
                grp, order = ("qualified_spec" if same else "qualified"), 0
            else:
                grp, order = "other", 0
            busy = []
            if day is not None and end > start:
                busy = [m for m in self.check(sections=[], groups=set(), teacher=tid, room=None, subject=subject_id,
                                              shareable=False, kind="teach", day=day, start=start, end=end)]
            out.append({"id": tid, "name": f"{r['rank'] or ''} {r['full_name']}".strip(), "group": grp, "order": order,
                        "busy": busy, "uses": hist.get(tid, 0)})
        rank = {"history": 0, "qualified_spec": 1, "qualified": 2, "other": 3}
        out.sort(key=lambda x: (rank[x["group"]], x["order"], bool(x["busy"]), x["name"]))
        return out

    def usual_teacher(self, section_id: int | None, subject_id: int) -> int | None:
        """الأستاذ الذي درّس المادة لهذا القسم أكثر من غيره في الأسابيع السابقة."""
        t = self.subject_history(section_id).get(subject_id, {}).get("teachers", {})
        return max(t.items(), key=lambda kv: kv[1])[0] if t else None

    def suggest_slots(self, item, section_id: int | None, limit: int = 6, teacher: int | None = None) -> list[dict]:
        """أقرب الأوقات في هذا الأسبوع التي يكون فيها القسم (والأستاذ) متفرغاً، بداية كل حصة.

        item: بطاقة من الشريط (TrayItem) أو حصة موجودة (Card). يعيد [{day, start, end, label, teacher}].
        """
        if section_id is None:
            return []
        minutes = item.minutes
        if isinstance(item, TrayItem) and item.free:
            teacher = teacher or self.usual_teacher(section_id, item.subject)
            check = lambda d, a, b: self.check_free(item, section_id, d, a, b, teacher=teacher)
        elif isinstance(item, Card):
            teacher = item.teacher
            check = lambda d, a, b: self.check_card(item, d, a, b)
        else:
            teacher = item.teacher
            check = lambda d, a, b: self.check_tray(item, d, a, b)
        sec = self.sec_by_id.get(section_id)
        rest = set()
        if sec:
            from ..utils import parse_rest_days
            rest = parse_rest_days(self.db.scalar("SELECT rest_days FROM formations WHERE id=?",
                                                  (sec.formation_id,), "5,6"))
        lunch = self.pm.lunch(section_id)
        ps = [p for p in self.pm.periods(section_id) if p.kind == "day" and p.idx != lunch]
        out = []
        for di in range(7):
            if di in rest:
                continue
            d = self.ws + timedelta(days=di)
            for p in ps:
                prop = self.proposal(minutes, section_id, di, p.idx)
                if prop is None:
                    continue
                _d, a, b = prop
                if isinstance(item, Card) and item.day == d and item.start == a:
                    continue
                if check(d, a, b):
                    continue
                out.append({"day": d, "start": a, "end": b, "teacher": teacher,
                            "past": d < self.today,
                            "label": f"{DAY_NAMES[di]} {d.strftime('%d/%m')} · الحصة {p.idx} · {hm_range(a, b)}"})
        out.sort(key=lambda x: (x["past"], x["day"], x["start"]))
        return out[:limit]

    def create_teacher(self, name: str, subject_id: int, section_id: int | None) -> int:
        """أستاذ جديد من نافذة الاختيار: يُضاف للقائمة، ويُعيَّن للمادة ولاختصاص القسم."""
        from ..importers.roz import split_rank
        rank, full = split_rank(name)
        spec = self.sec_by_id[section_id].specialty if section_id in self.sec_by_id else ""
        with self.db.tx():
            tid = self.db.execute("INSERT INTO teachers(full_name, rank, specialty, active) VALUES (?,?,?,1)",
                                  (full or name, rank or None, spec or None))
            self.db.execute("INSERT OR IGNORE INTO teacher_subjects VALUES (?,?)", (tid, subject_id))
            self.db.log("إضافة أستاذ من الجدول العام", "teachers", tid, {"name": name, "subject": subject_id})
        return tid

    def place_free(self, item: TrayItem, section_id: int, teacher_id: int | None, day: date, start: int, end: int) -> int:
        from .timetables import get_or_create_timetable
        sec = self.sec_by_id[section_id]
        g = self.whole_group.get(section_id)
        if not g:
            raise GridError("لا يوجد «فوج كامل» لهذا القسم.")
        tt = get_or_create_timetable(self.db, sec.formation_id, self.ws)
        self._guard(self.db.scalar("SELECT status FROM timetables WHERE id=?", (tt,), "draft"))
        req = self.db.scalar("""SELECT id FROM requirements WHERE group_id=? AND subject_id=?
                                AND COALESCE(teacher_id,0)=COALESCE(?,0)""", (g, item.subject, teacher_id)) \
            or self.db.scalar("SELECT id FROM requirements WHERE group_id=? AND subject_id=?", (g, item.subject))
        if teacher_id:
            self.db.execute("INSERT OR IGNORE INTO teacher_subjects VALUES (?,?)", (teacher_id, item.subject))
        data = {"timetable_id": tt, "requirement_id": req, "date": iso(day), "start_min": start, "end_min": end,
                "subject_id": item.subject, "teacher_id": teacher_id, "room_id": None, "status": "planned",
                "manual": 1, "groups": [g]}
        sid = self._insert(data)
        data["id"] = sid
        self._push({"op": "create", "sid": sid, "data": data, "label": "إضافة مادة"})
        return sid

    def resize(self, card: Card, start: int, end: int):
        self.move(card, card.day, start, end, label="تمديد/تقصير حصة")

    def set_teacher(self, card: Card, teacher_id: int | None):
        self._guard(card.tt_status)
        before = {"teacher_id": self.db.scalar("SELECT teacher_id FROM sessions WHERE id=?", (card.sid,))}
        after = {"teacher_id": teacher_id}
        if teacher_id:
            self.db.execute("INSERT OR IGNORE INTO teacher_subjects VALUES (?,?)", (teacher_id, card.subject))
        self._apply_update(card.sid, after)
        self._push({"op": "update", "sid": card.sid, "before": before, "after": after, "label": "تغيير الأستاذ"})

    # ------------------------------------------------------------------ عمليات (مع التراجع)
    def _guard(self, tt_status: str):
        if tt_status == "approved":
            raise GridError("الجدول معتمد؛ أعد فتحه كمسودة قبل التعديل.")

    def _row(self, sid: int) -> dict:
        r = dict(self.db.one("SELECT * FROM sessions WHERE id=?", (sid,)))
        r["groups"] = [x[0] for x in self.db.q("SELECT group_id FROM session_groups WHERE session_id=?", (sid,))]
        return r

    def _status_for(self, day: date) -> str:
        return "planned"

    def move(self, card: Card, day: date, start: int, end: int, label="نقل حصة"):
        self._guard(card.tt_status)
        before = {"date": iso(card.day), "start_min": card.start, "end_min": card.end}
        after = {"date": iso(day), "start_min": start, "end_min": end}
        self._apply_update(card.sid, after)
        self._push({"op": "update", "sid": card.sid, "before": before, "after": after, "label": label})

    def to_tray(self, card: Card):
        self._guard(card.tt_status)
        self._apply_update(card.sid, {"status": "tray"})
        self._push({"op": "update", "sid": card.sid, "before": {"status": card.status}, "after": {"status": "tray"},
                    "label": "إزالة إلى الشريط"})

    def set_status(self, card: Card, status: str):
        self._apply_update(card.sid, {"status": status})
        self._push({"op": "update", "sid": card.sid, "before": {"status": card.status}, "after": {"status": status},
                    "label": "تغيير الحالة"})

    def place(self, item: TrayItem, day: date, start: int, end: int) -> int:
        if item.sid:
            c = self.tray_cards.get(item.sid)
            self._guard(c.tt_status if c else "draft")
            after = {"date": iso(day), "start_min": start, "end_min": end, "status": self._status_for(day)}
            before = {"date": iso(c.day), "start_min": c.start, "end_min": c.end, "status": "tray"} if c else {}
            self._apply_update(item.sid, after)
            self._push({"op": "update", "sid": item.sid, "before": before, "after": after, "label": "وضع حصة"})
            return item.sid
        from .timetables import get_or_create_timetable
        sec = self.sec_by_id[item.section]
        tt = get_or_create_timetable(self.db, sec.formation_id, self.ws)
        self._guard(self.db.scalar("SELECT status FROM timetables WHERE id=?", (tt,), "draft"))
        data = {"timetable_id": tt, "requirement_id": item.requirement, "date": iso(day), "start_min": start,
                "end_min": end, "subject_id": item.subject, "teacher_id": item.teacher, "room_id": None,
                "status": "planned", "manual": 1, "groups": sorted(item.groups)}
        sid = self._insert(data)
        data["id"] = sid
        self._push({"op": "create", "sid": sid, "data": data, "label": "إضافة حصة"})
        return sid

    def delete(self, sid: int):
        data = self._row(sid)
        with self.db.tx():
            self.db.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.db.log("حذف حصة (الجدول العام)", "sessions", sid)
        self._push({"op": "delete", "sid": sid, "data": data, "label": "حذف حصة"})
        self.reload()

    def _insert(self, data: dict) -> int:
        d = {k: v for k, v in data.items() if k not in ("groups",)}
        with self.db.tx():
            sid = self.db.insert("sessions", **d)
            self.db.conn.executemany("INSERT INTO session_groups VALUES (?,?)", [(sid, g) for g in data["groups"]])
        self.reload()
        return sid

    def _apply_update(self, sid: int, fields: dict, reload=True):
        with self.db.tx():
            self.db.update("sessions", sid, manual=1, **fields)
            self.db.log("تعديل حصة (الجدول العام)", "sessions", sid, fields)
        if reload:
            self.reload()

    def _detail(self, act: dict) -> str:
        """وصف قصير لموضوع العملية: «المادة · القسم» (لقائمة التراجع)."""
        c = self.cards.get(act.get("sid")) or self.tray_cards.get(act.get("sid"))
        if c is not None:
            sec = self.sec_by_id.get(c.sections[0]) if c.sections else None
            return f"{c.sshort or c.sname}" + (f" · {sec.short}" if sec else "")
        data = act.get("data") or {}
        if data.get("subject_id"):
            nm = self.db.scalar("SELECT COALESCE(short, name) FROM subjects WHERE id=?", (data["subject_id"],), "")
            secs = {self.group_sec.get(g) for g in data.get("groups") or []} - {None}
            sec = self.sec_by_id.get(next(iter(secs))) if len(secs) == 1 else None
            return (nm or "") + (f" · {sec.short}" if sec else "")
        return ""

    def _push(self, act: dict):
        if act.get("op") != "group" and "detail" not in act:
            try:
                act["detail"] = self._detail(act)
            except Exception:
                act["detail"] = ""
        self.undo_stack.append(act)
        self.redo_stack.clear()
        del self.undo_stack[:-200]

    @staticmethod
    def op_text(a: dict) -> str:
        return a["label"] + (f": {a['detail']}" if a.get("detail") else "")

    def history(self, which: str = "undo", n: int = 20) -> list[str]:
        """آخر العمليات (الأحدث أولاً) لقائمة التراجع/الإعادة."""
        st = self.undo_stack if which == "undo" else self.redo_stack
        return [self.op_text(a) for a in reversed(st[-n:])]

    def undo_many(self, n: int) -> int:
        k = 0
        while k < n and self.undo() is not None:
            k += 1
        return k

    def redo_many(self, n: int) -> int:
        k = 0
        while k < n and self.redo() is not None:
            k += 1
        return k

    def undo(self) -> str | None:
        if not self.undo_stack:
            return None
        a = self.undo_stack.pop()
        self._revert(a, forward=False)
        self.redo_stack.append(a)
        return self.op_text(a)

    def redo(self) -> str | None:
        if not self.redo_stack:
            return None
        a = self.redo_stack.pop()
        self._revert(a, forward=True)
        self.undo_stack.append(a)
        return self.op_text(a)

    def _revert(self, a: dict, forward: bool):
        if a["op"] == "group":
            for x in (a["acts"] if forward else reversed(a["acts"])):
                self._revert(x, forward)
            return
        if a["op"] == "update":
            self._apply_update(a["sid"], a["after"] if forward else a["before"])
        elif a["op"] == "create":
            if forward:
                d = dict(a["data"])
                d.pop("id", None)
                a["sid"] = self._insert(d)
                a["data"]["id"] = a["sid"]
            else:
                with self.db.tx():
                    self.db.execute("DELETE FROM sessions WHERE id=?", (a["sid"],))
                self.reload()
        elif a["op"] == "delete":
            if forward:
                with self.db.tx():
                    self.db.execute("DELETE FROM sessions WHERE id=?", (a["sid"],))
                self.reload()
            else:
                d = dict(a["data"])
                d.pop("id", None)
                d["makeup_of"] = None
                a["sid"] = self._insert(d)

    # ------------------------------------------------------------------ الأصل المستورد
    def imported_snapshots(self) -> list[int]:
        return [r[0] for r in self.db.q("""SELECT sn.id FROM timetable_snapshots sn JOIN timetables t ON t.id=sn.timetable_id
                                          WHERE t.week_start=? AND sn.label='الأصل المستورد'""", (iso(self.ws),))]

    def revert_to_imported(self) -> int:
        from .timetables import restore_snapshot
        ids = self.imported_snapshots()
        for sn in ids:
            restore_snapshot(self.db, sn)
        self.undo_stack.clear()
        self.redo_stack.clear()
        self.reload()
        return len(ids)

    # ------------------------------------------------------------------ نصوص
    def describe(self, c: Card) -> dict:
        secs = [self.sec_by_id[s] for s in c.sections if s in self.sec_by_id]
        return {
            "subject": c.sname, "category": c.category,
            "sections": "، ".join(s.name for s in secs) or "—",
            "sections_short": "، ".join(s.short for s in secs) or "—",
            "teacher": c.tname or "—", "room": c.rname or "—",
            "time": f"{DAY_NAMES[c.wd]} {c.day.strftime('%d/%m/%Y')} — {hm_range(c.start, c.end)} ({c.minutes / 60:g} سا)",
            "status": c.status, "note": c.note,
        }
