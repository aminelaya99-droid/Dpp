"""محرك الجدولة المبني على OR-Tools CP-SAT.

النموذج زمني منفصل: اليوم مقسم إلى خانات (30 دقيقة افتراضياً). كل حصة
(meeting) لها متغير منطقي لكل (يوم، خانة بداية) ممكنة. القيود الإلزامية
تُفرض كقيود صلبة، والتفضيلات تدخل في دالة الهدف بأوزان قابلة للضبط.

الحصة المشتركة: متطلبات بنفس share_code ونفس المادة (القابلة للمشاركة)
ونفس الأستاذ تُدمج في حصة واحدة تخص عدة أفواج، فيبقى قيد "الأستاذ لا
يدرّس حصتين في وقت واحد" صالحاً دون استثناء.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from ortools.sat.python import cp_model

from ..db.database import Database
from ..services.calendar import blocked_dates
from ..utils import FULL_DAY, hm, iso, to_date, week_days, weekday_sun0

UNPLACED_PENALTY = 10_000


@dataclass
class Meeting:
    key: int
    requirement_ids: list[int]
    subject_id: int
    teacher_id: int | None
    group_ids: list[int]
    room_id: int | None
    needs_room: bool
    minutes: int              # 0 = يوم كامل
    label: str = ""
    size: int = 0


@dataclass
class Placement:
    meeting: Meeting
    day: date
    start_min: int
    end_min: int
    room_id: int | None = None


@dataclass
class Unplaced:
    meeting: Meeting
    reason: str


@dataclass
class ScheduleResult:
    week_start: date
    placements: list[Placement] = field(default_factory=list)
    unplaced: list[Unplaced] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)   # مشاكل في البيانات (لا أستاذ مؤهل…)
    status: str = ""
    objective: float = 0.0
    days: list[date] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.unplaced and not self.problems

    def summary(self) -> str:
        n, u = len(self.placements), len(self.unplaced)
        s = f"تمت برمجة {n} حصة"
        if u:
            s += f"، وتعذرت برمجة {u}"
        if self.problems:
            s += f"، مع {len(self.problems)} مشكلة في البيانات"
        return s + "."


class DayGrid:
    def __init__(self, db: Database):
        self.slot = max(15, db.get_int("slot_minutes"))
        self.start = db.get_int("day_start")
        self.end = db.get_int("day_end")
        self.lunch = (db.get_int("lunch_start"), db.get_int("lunch_end"))
        # عند وجود فترات حسب الطور، الغداء ونهاية اليوم يُحجبان لكل قسم على حدة (انظر _unavailable)
        if db.scalar("SELECT COUNT(*) FROM periods", (), 0) and db.get_setting("per_section_lunch", "1") == "1":
            self.lunch = (0, 0)
        self.n = (self.end - self.start) // self.slot

    def t(self, slot_idx: int) -> int:
        return self.start + slot_idx * self.slot

    def slot_of(self, minute: int) -> int:
        return (minute - self.start) // self.slot

    def slots_for(self, minutes: int) -> int:
        return self.n if minutes == FULL_DAY else math.ceil(minutes / self.slot)

    def valid_starts(self, minutes: int) -> list[int]:
        if minutes == FULL_DAY:
            return [0]
        L = self.slots_for(minutes)
        ls, le = self.lunch
        out = []
        for s in range(0, self.n - L + 1):
            a, b = self.t(s), self.t(s + L)
            if ls < le and a < le and b > ls:   # لا تقطع استراحة الغداء
                continue
            out.append(s)
        return out


# ---------------------------------------------------------------------------
class Scheduler:
    def __init__(self, db: Database, time_limit: float = 30.0, workers: int = 8):
        self.db = db
        self.time_limit = time_limit
        self.workers = workers
        self.grid = DayGrid(db)

    # ------------------------------------------------------------------ data
    def _group_units(self, group_ids: set[int]) -> dict[int, list[tuple]]:
        """لكل فوج: الوحدات الذرية التي يشغلها (الكامل يشغل كل مجموعاته)."""
        units: dict[int, list[tuple]] = {}
        sec_of = {}
        for r in self.db.q("SELECT id, section_id, is_whole FROM groups_"):
            sec_of[r["id"]] = (r["section_id"], r["is_whole"])
        subs = defaultdict(list)
        for gid, (sec, whole) in sec_of.items():
            if not whole:
                subs[sec].append(gid)
        for gid, (sec, whole) in sec_of.items():
            if whole and subs[sec]:
                units[gid] = [("g", sg) for sg in subs[sec]]
            else:
                units[gid] = [("g", gid)]
        return units

    def _pick_teacher(self, subject_id: int, load: dict[int, float]) -> int | None:
        rows = self.db.q("""SELECT t.id FROM teachers t JOIN teacher_subjects ts ON ts.teacher_id=t.id
                            WHERE ts.subject_id=? AND t.active=1""", (subject_id,))
        if not rows:
            return None
        return min((r["id"] for r in rows), key=lambda t: (load.get(t, 0), t))

    def build_meetings(self, formation_id: int, group_ids: list[int] | None,
                       hours_override: dict[int, float] | None, existing: dict[int, float],
                       problems: list[str]) -> list[Meeting]:
        sql = """SELECT r.*, s.name AS sname, s.shareable, g.name AS gname, g.size AS gsize,
                        sec.short AS sec_short, sec.name AS sec_name
                 FROM requirements r JOIN subjects s ON s.id=r.subject_id
                 JOIN groups_ g ON g.id=r.group_id JOIN sections sec ON sec.id=g.section_id
                 WHERE r.formation_id=?"""
        reqs = [dict(r) for r in self.db.q(sql, (formation_id,))]
        if group_ids is not None:
            gs = set(group_ids)
            reqs = [r for r in reqs if r["group_id"] in gs]
        load: dict[int, float] = defaultdict(float)
        for r in reqs:
            if r["teacher_id"]:
                load[r["teacher_id"]] += r["weekly_hours"] or 0

        # تحديد الساعات المطلوبة هذا الأسبوع
        need = []
        for r in reqs:
            h = hours_override.get(r["id"], 0.0) if hours_override is not None else (r["weekly_hours"] or 0)
            h -= existing.get(r["id"], 0.0)
            if h <= 1e-6:
                continue
            if not r["teacher_id"]:
                t = self._pick_teacher(r["subject_id"], load)
                if t is None:
                    problems.append(f"لا يوجد أستاذ مؤهل لمادة «{r['sname']}» ({r['sec_short'] or r['sec_name']} / {r['gname']}).")
                    continue
                r["teacher_id"] = t
                load[t] += h
            r["_hours"] = h
            need.append(r)

        # دمج الحصص المشتركة
        buckets: dict[tuple, list[dict]] = defaultdict(list)
        for r in need:
            if r["share_code"] and r["shareable"]:
                buckets[("S", r["share_code"], r["subject_id"], r["teacher_id"])].append(r)
            else:
                if r["share_code"] and not r["shareable"]:
                    problems.append(f"المادة «{r['sname']}» غير مفعلة كمادة قابلة للمشاركة؛ "
                                    f"تمت برمجة فوج {r['gname']} بشكل منفصل.")
                buckets[("R", r["id"])].append(r)

        meetings: list[Meeting] = []
        key = 0
        for b in buckets.values():
            r0 = b[0]
            hours = max(x["_hours"] for x in b)
            mins = int(r0["session_minutes"] or 120)
            total = int(round(hours * 60))
            lens = []
            if mins == FULL_DAY:
                day_len = self.grid.end - self.grid.start - max(0, self.grid.lunch[1] - self.grid.lunch[0])
                n = max(1, round(total / day_len))
                lens = [FULL_DAY] * n
            else:
                n, rem = divmod(total, mins)
                lens = [mins] * n
                rem = (rem // self.grid.slot) * self.grid.slot
                if rem >= 60:
                    lens.append(rem)
            room = next((x["room_id"] for x in b if x["room_id"]), None)
            for L in lens:
                meetings.append(Meeting(
                    key=key, requirement_ids=[x["id"] for x in b], subject_id=r0["subject_id"],
                    teacher_id=r0["teacher_id"], group_ids=sorted({x["group_id"] for x in b}),
                    room_id=room, needs_room=any(x["needs_room"] for x in b) or bool(room), minutes=L,
                    label=f"{r0['sname']} — " + "، ".join(f"{x['sec_short'] or x['sec_name']}/{x['gname']}" for x in b),
                    size=sum(x["gsize"] or 0 for x in b)))
                key += 1
        return meetings

    def _occupancy(self, days: list[date], exclude_timetable: int | None):
        """الحصص القائمة (من كل التكوينات) خارج الجدول الجاري إنشاؤه."""
        occ = defaultdict(set)   # resource -> {(date, slot)}
        if not days:
            return occ
        rows = self.db.q("""SELECT s.*, GROUP_CONCAT(sg.group_id) AS gids FROM sessions s
                            LEFT JOIN session_groups sg ON sg.session_id=s.id
                            WHERE s.date>=? AND s.date<=? AND s.status IN ('planned','done')
                            AND (? IS NULL OR s.timetable_id IS NULL OR s.timetable_id<>? OR s.manual=1
                                 OR s.status='done')
                            GROUP BY s.id""", (iso(days[0]), iso(days[-1]), exclude_timetable, exclude_timetable))
        units = self._group_units(set())
        for r in rows:
            d = to_date(r["date"])
            s0 = max(0, self.grid.slot_of(r["start_min"]))
            s1 = min(self.grid.n, math.ceil((r["end_min"] - self.grid.start) / self.grid.slot))
            res = []
            t = r["substitute_id"] or r["teacher_id"]
            if t:
                res.append(("t", t))
            if r["room_id"]:
                res.append(("r", r["room_id"]))
            for g in (r["gids"] or "").split(","):
                if g:
                    res += units.get(int(g), [("g", int(g))])
            for x in res:
                for s in range(s0, s1):
                    occ[x].add((d, s))
        return occ

    def _unavailable(self, days: list[date]):
        hard, soft = defaultdict(set), defaultdict(set)
        units = self._group_units(set())
        for r in self.db.q("SELECT * FROM unavailability"):
            kind = {"teacher": "t", "room": "r", "group": "g"}.get(r["kind"])
            if not kind:
                continue
            for d in days:
                if r["date"] and to_date(r["date"]) != d:
                    continue
                if r["weekday"] is not None and r["date"] is None and weekday_sun0(d) != r["weekday"]:
                    continue
                s0 = max(0, self.grid.slot_of(r["start_min"]))
                s1 = min(self.grid.n, math.ceil((r["end_min"] - self.grid.start) / self.grid.slot))
                keys = units.get(r["ref_id"], [("g", r["ref_id"])]) if kind == "g" else [(kind, r["ref_id"])]
                for k in keys:
                    for s in range(s0, s1):
                        (hard if r["hard"] else soft)[k].add((d, s))
        # الغداء ونهاية اليوم حسب الطور/القسم
        if self.grid.lunch == (0, 0):
            from ..services.periods import PeriodMap
            pm = PeriodMap(self.db)
            whole = {r[0]: r[1] for r in self.db.q("SELECT section_id, id FROM groups_ WHERE is_whole=1")}
            for sec, gid in whole.items():
                ps = [p for p in pm.periods(sec) if p.kind == "day"]
                if not ps:
                    continue
                lp = next((p for p in ps if p.idx == pm.lunch(sec)), None)
                spans = [(ps[-1].end, self.grid.end)]
                if lp:
                    spans.append((lp.start, lp.end))
                keys = units.get(gid, [("g", gid)])
                for a, b in spans:
                    s0 = max(0, self.grid.slot_of(a))
                    s1 = min(self.grid.n, math.ceil((b - self.grid.start) / self.grid.slot))
                    for d in days:
                        for k in keys:
                            for sl in range(s0, s1):
                                hard[k].add((d, sl))
        # الأساتذة الغائبون
        for r in self.db.q("SELECT teacher_id, start_date, end_date FROM absences"):
            for d in days:
                if to_date(r["start_date"]) <= d <= to_date(r["end_date"]):
                    for s in range(self.grid.n):
                        hard[("t", r["teacher_id"])].add((d, s))
        return hard, soft

    # ------------------------------------------------------------------ solve
    def schedule_week(self, formation_id: int, week_start, group_ids: list[int] | None = None,
                      hours_override: dict[int, float] | None = None,
                      exclude_timetable: int | None = None, subtract_existing: bool = True,
                      from_date=None, rules: dict | None = None) -> ScheduleResult:
        """rules (اختياري، من أولويات البرمجة): day_hours ساعات الدراسة القصوى للفوج في اليوم،
        max_per_day حد حصص نفس المادة للفوج في اليوم، morning مواد لا تُبرمج إلا قبل morning_end."""
        rules = rules or {}
        ws = to_date(week_start)
        if exclude_timetable is None:   # الجدول الحالي لهذا الأسبوع سيُستبدل جزؤه المولد آلياً
            exclude_timetable = self.db.scalar(
                "SELECT id FROM timetables WHERE formation_id=? AND week_start=? ORDER BY version DESC LIMIT 1",
                (formation_id, iso(ws)))
        blocked = blocked_dates(self.db, formation_id, ws, week_days(ws)[-1])
        days = [d for d in week_days(ws) if d not in blocked and (from_date is None or d >= to_date(from_date))]
        res = ScheduleResult(week_start=ws, days=days)

        # الساعات المبرمجة مسبقاً هذا الأسبوع والتي ستبقى (جداول أخرى، يدوية، منجزة)
        existing = defaultdict(float)
        if subtract_existing:
            for r in self.db.q("""SELECT rq.id, SUM(s.end_min-s.start_min) m FROM sessions s
                                  JOIN session_groups sg ON sg.session_id=s.id
                                  JOIN requirements rq ON rq.group_id=sg.group_id AND rq.subject_id=s.subject_id
                                  WHERE rq.formation_id=? AND s.date>=? AND s.date<=? AND s.status IN ('planned','done')
                                  AND (? IS NULL OR s.timetable_id IS NULL OR s.timetable_id<>? OR s.manual=1
                                       OR s.status='done')
                                  GROUP BY rq.id""",
                               (formation_id, iso(ws), iso(week_days(ws)[-1]), exclude_timetable, exclude_timetable)):
                existing[r["id"]] = r["m"] / 60.0

        meetings = self.build_meetings(formation_id, group_ids, hours_override, existing, res.problems)
        if not meetings:
            res.status = "EMPTY"
            return res
        if not days:
            res.unplaced = [Unplaced(m, "لا توجد أيام دراسة متاحة هذا الأسبوع (عطلة أو راحة).") for m in meetings]
            res.status = "NO_DAYS"
            return res

        units = self._group_units({g for m in meetings for g in m.group_ids})
        occ = self._occupancy(days, exclude_timetable)
        hard, soft = self._unavailable(days)
        rooms = [dict(r) for r in self.db.q("SELECT id, capacity FROM rooms")]
        g = self.grid

        model = cp_model.CpModel()
        x: dict[tuple, cp_model.IntVar] = {}
        cover = defaultdict(list)      # (resource, day, slot) -> [var]
        room_load = defaultdict(list)  # (day, slot) -> [var] للحصص التي تحتاج قاعة
        reasons: dict[int, str] = {}
        obj = []

        w_spread = self.db.get_int("w_spread")
        w_compact = self.db.get_int("w_compact")
        w_pref = self.db.get_int("w_teacher_pref")

        for m in meetings:
            L = g.slots_for(m.minutes)
            res_keys = [("t", m.teacher_id)] if m.teacher_id else []
            if m.room_id:
                res_keys.append(("r", m.room_id))
            for gid in m.group_ids:
                res_keys += units.get(gid, [("g", gid)])
            starts = g.valid_starts(m.minutes)
            if m.subject_id in set(rules.get("morning") or []) and m.minutes:
                mend = int(rules.get("morning_end") or 720)
                starts = [s for s in starts if g.t(s + L) <= mend] or starts
            if not starts:
                reasons[m.key] = "مدة الحصة أطول من اليوم الدراسي أو تتعارض مع استراحة الغداء."
            cand = 0
            blockers = defaultdict(int)
            for d in days:
                for s in starts:
                    span = range(s, s + L)
                    bad = None
                    for k in res_keys:
                        if any((d, t) in hard[k] for t in span):
                            bad = ("unav", k)
                            break
                        if any((d, t) in occ[k] for t in span):
                            bad = ("occ", k)
                            break
                    if bad:
                        blockers[bad] += 1
                        continue
                    v = model.NewBoolVar(f"x{m.key}_{d.toordinal()}_{s}")
                    x[(m.key, d, s)] = v
                    cand += 1
                    for k in res_keys:
                        for t in span:
                            cover[(k, d, t)].append(v)
                    if m.needs_room and not m.room_id:
                        for t in span:
                            room_load[(d, t)].append(v)
                    obj.append(v * (w_compact * s))
                    if m.teacher_id and any((d, t) in soft[("t", m.teacher_id)] for t in span):
                        obj.append(v * (w_pref * 10))
            if cand == 0 and m.key not in reasons:
                if blockers:
                    (kind, k), _ = max(blockers.items(), key=lambda kv: kv[1])
                    who = {"t": "الأستاذ", "r": "القاعة", "g": "الفوج"}[k[0]]
                    reasons[m.key] = (f"{who} غير متاح في كل الأوقات الممكنة هذا الأسبوع."
                                      if kind == "unav" else f"{who} مشغول بحصص أخرى في كل الأوقات الممكنة.")
                else:
                    reasons[m.key] = "لا توجد خانة زمنية ممكنة."

        placed_flag = {}
        for m in meetings:
            vs = [v for (k, d, s), v in x.items() if k == m.key]
            p = model.NewBoolVar(f"p{m.key}")
            if vs:
                model.Add(sum(vs) == p)
            else:
                model.Add(p == 0)
            placed_flag[m.key] = p
            obj.append((1 - p) * UNPLACED_PENALTY)

        for vs in cover.values():
            if len(vs) > 1:
                model.AddAtMostOne(vs)
        free_rooms = len([r for r in rooms])
        if free_rooms:
            for (d, t), vs in room_load.items():
                fixed_busy = sum(1 for r in rooms if (d, t) in occ[("r", r["id"])] or (d, t) in hard[("r", r["id"])])
                cap = max(0, free_rooms - fixed_busy)
                model.Add(sum(vs) <= cap)
        else:
            for m in meetings:
                if m.needs_room and not m.room_id:
                    res.problems.append("لا توجد قاعات مسجلة بينما بعض المواد تتطلب قاعة.")
                    break

        # قواعد اليوم من الأولويات
        mpd = int(rules.get("max_per_day") or 0)
        if mpd:
            by_gsd = defaultdict(list)
            mmap = {m.key: m for m in meetings}
            for (k, d, s), v in x.items():
                m = mmap[k]
                for gid in m.group_ids:
                    by_gsd[(gid, m.subject_id, d)].append(v)
            for vs in by_gsd.values():
                if len(vs) > mpd:
                    model.Add(sum(vs) <= mpd)
        dh = float(rules.get("day_hours") or 0)
        if dh:
            teach = defaultdict(float)
            for r in self.db.q("""SELECT sg.group_id, s.date, SUM(s.end_min-s.start_min) m FROM sessions s
                                  JOIN session_groups sg ON sg.session_id=s.id JOIN subjects sub ON sub.id=s.subject_id
                                  WHERE s.date>=? AND s.date<=? AND s.status IN ('planned','done')
                                  AND COALESCE(sub.kind,'teach')<>'nonteach'
                                  AND (? IS NULL OR s.timetable_id IS NULL OR s.timetable_id<>? OR s.manual=1
                                       OR s.status='done')
                                  GROUP BY sg.group_id, s.date""",
                               (iso(days[0]), iso(days[-1]), exclude_timetable, exclude_timetable)):
                teach[(r["group_id"], to_date(r["date"]))] += r["m"]
            mmap = {m.key: m for m in meetings}
            by_gd = defaultdict(list)
            for (k, d, s), v in x.items():
                m = mmap[k]
                for gid in m.group_ids:
                    by_gd[(gid, d)].append((v, m.minutes or int(dh * 60)))
            for (gid, d), lst in by_gd.items():
                cap = int(dh * 60 - teach.get((gid, d), 0))
                model.Add(sum(v * mins for v, mins in lst) <= max(0, cap))

        # توزيع حصص المتطلب نفسه على أيام مختلفة
        by_req = defaultdict(list)
        for m in meetings:
            by_req[tuple(m.requirement_ids)].append(m.key)
        for keys in by_req.values():
            if len(keys) < 2:
                continue
            for d in days:
                vs = [v for (k, dd, s), v in x.items() if k in keys and dd == d]
                if len(vs) > 1:
                    extra = model.NewIntVar(0, len(vs), "")
                    model.Add(extra >= sum(vs) - 1)
                    obj.append(extra * (w_spread * 20))

        model.Minimize(sum(obj))
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.num_workers = self.workers
        st = solver.Solve(model)
        res.status = solver.StatusName(st)
        if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            res.unplaced = [Unplaced(m, reasons.get(m.key, "تعذر إيجاد حل ضمن المهلة المحددة.")) for m in meetings]
            return res
        res.objective = solver.ObjectiveValue()

        mby = {m.key: m for m in meetings}
        for (k, d, s), v in x.items():
            if solver.Value(v):
                m = mby[k]
                L = g.slots_for(m.minutes)
                res.placements.append(Placement(m, d, g.t(s), g.t(s + L) if m.minutes else g.end, m.room_id))
        placed = {p.meeting.key for p in res.placements}
        for m in meetings:
            if m.key not in placed:
                res.unplaced.append(Unplaced(m, reasons.get(m.key) or self._capacity_reason(m, days, units, occ, hard)))
        self._assign_rooms(res, rooms, occ, hard)
        res.placements.sort(key=lambda p: (p.day, p.start_min))
        return res

    def _capacity_reason(self, m: Meeting, days, units, occ, hard) -> str:
        g = self.grid
        total = len(days) * g.n
        for gid in m.group_ids:
            for k in units.get(gid, [("g", gid)]):
                busy = sum(1 for d in days for s in range(g.n) if (d, s) in occ[k] or (d, s) in hard[k])
                if busy >= total:
                    return "الفوج لا يملك أي وقت حر هذا الأسبوع."
        if m.teacher_id:
            return ("تعارض الموارد: الأستاذ أو الفوج أو القاعات مشغولة في كل الخانات المتبقية؛ "
                    "الحجم الساعي المطلوب يتجاوز الوقت المتاح هذا الأسبوع.")
        return "تعارض الموارد في كل الخانات المتبقية."

    def _assign_rooms(self, res: ScheduleResult, rooms, occ, hard):
        """إسناد القاعات للحصص التي تحتاج قاعة بلا قاعة محددة (تلوين فترات جشع)."""
        g = self.grid
        busy = defaultdict(set)
        for r in rooms:
            busy[r["id"]] = set(occ[("r", r["id"])]) | set(hard[("r", r["id"])])
        for p in res.placements:
            if p.room_id:
                s0, s1 = g.slot_of(p.start_min), g.slot_of(p.end_min)
                busy[p.room_id] |= {(p.day, s) for s in range(s0, s1)}
        need = [p for p in res.placements if p.meeting.needs_room and not p.room_id]
        need.sort(key=lambda p: (p.day, p.start_min, -(p.meeting.size or 0)))
        for p in need:
            s0, s1 = g.slot_of(p.start_min), max(g.slot_of(p.start_min) + 1, g.slot_of(p.end_min))
            span = {(p.day, s) for s in range(s0, s1)}
            options = sorted((r for r in rooms if not (busy[r["id"]] & span)
                              and (not r["capacity"] or r["capacity"] >= (p.meeting.size or 0))),
                             key=lambda r: (r["capacity"] or 10**6))
            if not options:
                options = [r for r in rooms if not (busy[r["id"]] & span)]
                if options:
                    res.problems.append(f"لا توجد قاعة بسعة كافية لـ «{p.meeting.label}»؛ أُسندت أقرب قاعة متاحة.")
            if options:
                p.room_id = options[0]["id"]
                busy[p.room_id] |= span
            else:
                res.problems.append(f"لم تُسند قاعة لـ «{p.meeting.label}» ({iso(p.day)} {hm(p.start_min)}).")
