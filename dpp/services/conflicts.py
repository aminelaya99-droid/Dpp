"""كشف التعارضات وقواعد المشاركة.

القواعد:
  * الأستاذ: حصتان متداخلتان لنفس الأستاذ (أو مستخلفه) = تعارض، إلا إذا كانت المادة نفسها وقابلة للمشاركة
    (الرمي، التربية البدنية، العدو الريفي، النظام المنظم، المحاضرات) فهي حصة مشتركة.
  * القسم/الفوج: حصتان متداخلتان لنفس الفوج (الفوج الكامل يشمل مجموعاته) = تعارض.
  * القاعة: نفس القاعة في نفس الوقت = تعارض، إلا الحصة المشتركة.
كل تعارض له مفتاح ثابت مبني على محتواه (لا على أرقام الحصص)، فيبقى «التجاهل» صالحاً بعد الاستعادة،
ويظهر التعارض من جديد إذا تغيّر الوقت أو المادة.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from ..db.database import Database
from ..utils import hm_range, iso, to_date


@dataclass
class Conflict:
    kind: str                 # teacher | group | room
    key: str
    session_ids: list[int]
    date: str
    message: str
    ignored: bool = False
    resource: str = ""


@dataclass
class _S:
    id: int
    date: str
    start: int
    end: int
    subject: int
    sname: str
    shareable: bool
    teacher: int | None
    room: int | None
    groups: set[int] = field(default_factory=set)


def _units(db: Database) -> tuple[dict[int, set[int]], dict[int, int]]:
    rows = db.q("SELECT id, section_id, is_whole FROM groups_")
    subs = defaultdict(set)
    sec = {}
    for r in rows:
        sec[r["id"]] = r["section_id"]
        if not r["is_whole"]:
            subs[r["section_id"]].add(r["id"])
    units = {}
    for r in rows:
        units[r["id"]] = (subs[r["section_id"]] | {r["id"]}) if r["is_whole"] else {r["id"]}
    # الفوج الكامل يتعارض مع كل مجموعة، والمجموعة تتعارض مع الفوج الكامل
    whole = {r["section_id"]: r["id"] for r in rows if r["is_whole"]}
    for r in rows:
        if not r["is_whole"] and r["section_id"] in whole:
            units[r["id"]] = {r["id"], whole[r["section_id"]]}
    return units, sec


def _sig(s: _S) -> str:
    return f"{s.start}-{s.end}:{s.subject}:{','.join(map(str, sorted(s.groups)))}"


def load_sessions(db: Database, start, end) -> list[_S]:
    rows = db.q("""SELECT s.id, s.date, s.start_min, s.end_min, s.subject_id, sub.name sname, sub.shareable,
                          COALESCE(s.substitute_id, s.teacher_id) t, s.room_id
                   FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                   WHERE s.date BETWEEN ? AND ? AND s.status IN ('planned','done')""",
                (iso(to_date(start)), iso(to_date(end))))
    out = {r["id"]: _S(r["id"], r["date"], r["start_min"], r["end_min"], r["subject_id"], r["sname"],
                       bool(r["shareable"]), r["t"], r["room_id"]) for r in rows}
    if out:
        for r in db.q("""SELECT sg.session_id, sg.group_id FROM session_groups sg JOIN sessions s ON s.id=sg.session_id
                         WHERE s.date BETWEEN ? AND ?""", (iso(to_date(start)), iso(to_date(end)))):
            if r[0] in out:
                out[r[0]].groups.add(r[1])
    return list(out.values())


def find_conflicts(db: Database, start, end, sessions: list[_S] | None = None) -> list[Conflict]:
    sessions = sessions if sessions is not None else load_sessions(db, start, end)
    units, _sec = _units(db)
    ignored = {r[0] for r in db.q("SELECT key FROM conflict_ignores")}
    tnames = {r[0]: r[1] for r in db.q("SELECT id, full_name FROM teachers")}
    gnames = {r[0]: f"{r[2] or r[3]} / {r[1]}" for r in db.q(
        "SELECT g.id, g.name, s.short, s.name FROM groups_ g JOIN sections s ON s.id=g.section_id")}
    rnames = {r[0]: r[1] for r in db.q("SELECT id, name FROM rooms")}
    by_day = defaultdict(list)
    for s in sessions:
        by_day[s.date].append(s)
    out: list[Conflict] = []
    for day, lst in by_day.items():
        lst.sort(key=lambda s: s.start)
        for i, a in enumerate(lst):
            for b in lst[i + 1:]:
                if b.start >= a.end:
                    break
                shared = a.subject == b.subject and a.shareable
                pair = sorted((_sig(a), _sig(b)))
                when = hm_range(max(a.start, b.start), min(a.end, b.end))
                if a.teacher and a.teacher == b.teacher and not shared:
                    k = f"t:{a.teacher}:{day}:{pair[0]}|{pair[1]}"
                    out.append(Conflict("teacher", k, [a.id, b.id], day,
                                        f"الأستاذ {tnames.get(a.teacher, '')} في حصتين ({a.sname} / {b.sname}) {when}",
                                        k in ignored, tnames.get(a.teacher, "")))
                ua = set().union(*(units.get(g, {g}) for g in a.groups)) if a.groups else set()
                common = ua & b.groups
                if common:
                    k = f"g:{day}:{pair[0]}|{pair[1]}"
                    g = gnames.get(min(common), "")
                    out.append(Conflict("group", k, [a.id, b.id], day,
                                        f"القسم {g} في حصتين ({a.sname} / {b.sname}) {when}", k in ignored, g))
                if a.room and a.room == b.room and not shared:
                    k = f"r:{a.room}:{day}:{pair[0]}|{pair[1]}"
                    out.append(Conflict("room", k, [a.id, b.id], day,
                                        f"القاعة {rnames.get(a.room, '')} محجوزة مرتين {when}", k in ignored,
                                        rnames.get(a.room, "")))
    return out


def active_conflicts(db: Database, start, end) -> list[Conflict]:
    return [c for c in find_conflicts(db, start, end) if not c.ignored]


def ignore(db: Database, keys: list[str], note: str = ""):
    with db.tx():
        for k in keys:
            db.execute("INSERT OR IGNORE INTO conflict_ignores(key, note) VALUES (?,?)", (k, note))


def unignore(db: Database, keys: list[str]):
    with db.tx():
        for k in keys:
            db.execute("DELETE FROM conflict_ignores WHERE key=?", (k,))


def conflicts_for_session(conflicts: list[Conflict]) -> dict[int, list[Conflict]]:
    out = defaultdict(list)
    for c in conflicts:
        for sid in c.session_ids:
            out[sid].append(c)
    return out
