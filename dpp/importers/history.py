"""استيراد الأسابيع السابقة من ملفات aSc (.roz) كتاريخ فعلي قابل للتعديل.

لكل ملف أسبوع: تُقرأ البطاقات (أماكن الحصص) وتتحول إلى حصص بتواريخ فعلية، مع:
  * مطابقة الأقسام بين الأسابيع بالاسم ثم بالترتيب (aSc يغيّر أحياناً اسم القسم)؛
  * أوقات الحصص حسب ملف فترات طور كل قسم (القاعدي المشترك: 13:00–14:30 و14:30–16:00)؛
  * دمج الحصص المشتركة (نفس المادة القابلة للمشاركة ونفس الأستاذ ونفس الوقت) في حصة واحدة؛
  * الحالة: «منجزة» لما قبل اليوم، «مبرمجة» لما بعده؛
  * لقطة «الأصل المستورد» لكل جدول أسبوعي للرجوع إليها؛
  * تجاهل التعارضات الموجودة أصلاً في الملفات (حسب طلبك)، مع بقاء أي تعارض جديد ظاهراً.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..db.database import Database
from ..services import conflicts as C
from ..services import structure as ST
from ..services.periods import PeriodMap
from ..services.timetables import snapshot
from ..utils import iso, make_abbrev, unique_abbrev
from .roz import RozData, parse_roz_file, split_rank
from .roz_import import _category_for

WEEK1 = date(2026, 9, 13)


@dataclass
class HistoryReport:
    weeks: list[int] = field(default_factory=list)
    sections: int = 0
    subjects: int = 0
    teachers: int = 0
    sessions: int = 0
    merged: int = 0
    ignored_conflicts: int = 0
    per_week: dict[int, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def text(self) -> str:
        lines = [f"الأسابيع المستوردة: {', '.join(map(str, self.weeks))}",
                 f"الأقسام: {self.sections} · المواد: {self.subjects} · الأساتذة: {self.teachers}",
                 f"الحصص: {self.sessions} (منها {self.merged} دمج حصص مشتركة)",
                 f"التعارضات الموجودة في الملفات وتم تجاهلها: {self.ignored_conflicts}"]
        lines += [f"  الأسبوع {w}: {n} حصة" for w, n in sorted(self.per_week.items())]
        return "\n".join(lines + self.warnings)


def week_start_of(week_no: int, week1: date = WEEK1) -> date:
    return week1 + timedelta(days=7 * (week_no - 1))


def _norm(s: str) -> str:
    return " ".join(s.split())


def import_history(db: Database, files: dict[int, str], week1: date = WEEK1, today: date | None = None,
                   replace=True, progress=None) -> HistoryReport:
    """files = {رقم الأسبوع: مسار ملف .roz}."""
    today = today or date.today()
    rep = HistoryReport(weeks=sorted(files))
    datas: dict[int, RozData] = {}
    for w in sorted(files):
        datas[w] = parse_roz_file(files[w])
        rep.warnings += [f"الأسبوع {w}: {x}" for x in datas[w].warnings]
        if progress:
            progress(f"قراءة الأسبوع {w}")
    levels = ST.ensure_structure(db)
    latest = datas[max(datas)]
    with db.tx():
        # ------------------------------------------------ الأقسام (من أحدث أسبوع)
        sec_by_pos: dict[int, int] = {}
        sec_by_name: dict[str, int] = {}
        shorts = {r[0] for r in db.q("SELECT short FROM sections WHERE short IS NOT NULL")}
        used_k = defaultdict(set)  # موضع المجموعة في القسم المستعمل في أي أسبوع
        for d in datas.values():
            used = {g for l in d.lessons for g in l.groups}
            for ci, (_, _, gl) in enumerate(d.classes):
                for k, gi in enumerate(gl):
                    if gi in used:
                        used_k[ci].add(k)
        for ci, (name, asc_short, gl) in enumerate(latest.classes):
            code = ST.classify_class(name)
            if code is None:
                rep.warnings.append(f"لم يُعرف طور القسم: {name} — أُلحق بـ BMP2، عدّله من الهيكل.")
                code = "BMP2"
            lid = levels[code]
            lev = db.one("SELECT * FROM levels WHERE id=?", (lid,))
            spec, part = ST.split_class(name, code)
            sp = db.one("SELECT id FROM specialties WHERE level_id=? AND name=?", (lid, spec))
            spid = sp["id"] if sp else db.insert("specialties", level_id=lid, name=spec, short=make_abbrev(spec)[:20])
            coh = db.scalar("SELECT id FROM cohorts WHERE level_id=? ORDER BY start_date LIMIT 1", (lid,))
            ex = db.one("SELECT id FROM sections WHERE name=? AND level_id=?", (name, lid)) \
                or db.one("SELECT id FROM sections WHERE asc_index=? AND level_id=?", (ci, lid))
            if ex:
                sid = ex["id"]
                db.execute("UPDATE sections SET asc_index=?, specialty_id=COALESCE(specialty_id, ?) WHERE id=?",
                           (ci, spid, sid))
            else:
                short = unique_abbrev(ST.section_short(code, spec, part, asc_short), shorts)
                shorts.add(short)
                sid = db.insert("sections", formation_id=lev["formation_id"], level_id=lid, name=name, short=short,
                                specialty_id=spid, cohort_id=coh, asc_index=ci, sort=ci)
                rep.sections += 1
            sec_by_pos[ci] = sid
            sec_by_name[_norm(name)] = sid
        # المجموعات: الفوج الكامل دائماً + المجموعات المستعملة فعلاً
        group_of: dict[tuple[int, int], int] = {}   # (section_id, k) -> group_id
        for ci, (_, _, gl) in enumerate(latest.classes):
            sid = sec_by_pos[ci]
            for k, gi in enumerate(gl):
                if k != 0 and k not in used_k[ci]:
                    continue
                gname = (latest.groups[gi] if gi < len(latest.groups) else "") or ("الفوج الكامل" if k == 0 else f"مجموعة {k}")
                gname = _norm(gname)
                if k == 0:
                    gname = "الفوج الكامل"
                ex = db.one("SELECT id FROM groups_ WHERE section_id=? AND name=?", (sid, gname))
                group_of[(sid, k)] = ex["id"] if ex else db.insert("groups_", section_id=sid, name=gname,
                                                                   short=make_abbrev(gname)[:8], is_whole=int(k == 0))

        # ------------------------------------------------ المواد والأساتذة والقاعات
        subj_id: dict[str, int] = {r["name"]: r["id"] for r in db.q("SELECT id, name FROM subjects")}
        sshorts = {r[0] for r in db.q("SELECT short FROM subjects WHERE short IS NOT NULL")}
        teach_id: dict[tuple[str, str], int] = {(r["full_name"], r["rank"] or ""): r["id"]
                                                for r in db.q("SELECT id, full_name, rank FROM teachers")}
        room_id: dict[str, int] = {r["name"]: r["id"] for r in db.q("SELECT id, name FROM rooms")}
        for d in datas.values():
            used_s = {l.subject for l in d.lessons}
            for si, (name, short) in enumerate(d.subjects):
                name = name.strip()
                if si not in used_s:
                    continue
                if name and name not in subj_id:
                    ab = unique_abbrev(ST.arabic_short(short if short and short != name else name), sshorts)
                    sshorts.add(ab)
                    subj_id[name] = db.insert("subjects", name=name, short=ab)
                    ST.classify_subject(db, subj_id[name], name, force=True)
                    rep.subjects += 1
            for full, _ in d.teachers:
                rank, nm = split_rank(full)
                if (nm, rank) not in teach_id:
                    teach_id[(nm, rank)] = db.insert("teachers", full_name=nm, rank=rank,
                                                     category_id=_category_for(db, rank, full))
                    rep.teachers += 1
            for name, short in d.rooms:
                if name not in room_id:
                    room_id[name] = db.insert("rooms", name=name, short=(short or name)[:20])

        pm = PeriodMap(db)
        tt_ids: dict[tuple[int, int], int] = {}
        lunch_votes = defaultdict(Counter)
        req_acc = defaultdict(lambda: {"min": 0, "durs": Counter(), "weeks": set()})
        sess_req: list[tuple[int, tuple]] = []
        lunch_sid = subj_id.get("وجبة الغذاء")

        for w, d in sorted(datas.items()):
            ws = week_start_of(w, week1)
            # مطابقة أقسام هذا الأسبوع
            cmap = {}
            for ci, (name, _, _) in enumerate(d.classes):
                cmap[ci] = sec_by_name.get(_norm(name)) or sec_by_pos.get(ci)
            gmap: dict[int, int] = {}
            for ci, (_, _, gl) in enumerate(d.classes):
                for k, gi in enumerate(gl):
                    sid = cmap.get(ci)
                    if sid is not None:
                        g = group_of.get((sid, k)) or group_of.get((sid, 0))
                        if g:
                            gmap[gi] = g
            g2sec = {g: s for (s, _k), g in group_of.items()}
            lessons = {l.index: l for l in d.lessons}
            if replace:
                for f in {r[0] for r in db.q("SELECT id FROM formations")}:
                    db.execute("DELETE FROM sessions WHERE timetable_id IN (SELECT id FROM timetables WHERE formation_id=? "
                               "AND week_start=? AND source='roz')", (f, iso(ws)))
            # تجميع: (التاريخ، البداية، النهاية، المادة، الأستاذ، القاعة) -> أفواج
            slots: dict[tuple, set[int]] = defaultdict(set)
            shared_cache: dict[int, bool] = {r[0]: bool(r[1]) for r in db.q("SELECT id, shareable FROM subjects")}
            kind_cache: dict[int, str] = {r[0]: r[1] for r in db.q("SELECT id, COALESCE(kind,'teach') FROM subjects")}
            dropped = 0
            extra_teachers: dict[tuple, list[str]] = {}
            for c in d.cards:
                l = lessons.get(c.lesson)
                if not l:
                    continue
                sname = d.subjects[l.subject][0].strip()
                sub = subj_id.get(sname)
                if sub is None:
                    continue
                tid = None
                if l.teachers:
                    rank, nm = split_rank(d.teachers[l.teachers[0]][0])
                    tid = teach_id.get((nm, rank))
                rid = room_id.get(d.rooms[l.rooms[0]][0]) if l.rooms and l.rooms[0] < len(d.rooms) else None
                day = ws + timedelta(days=c.day)
                for gi in l.groups:
                    g = gmap.get(gi)
                    if g is None:
                        continue
                    sec = g2sec[g]
                    span = pm.span_minutes(sec, c.period, c.period + c.extra)
                    if span is None:
                        dropped += 1
                        continue
                    if sub == lunch_sid and c.extra == 0:
                        lunch_votes[sec][c.period] += 1
                    # المادة المشتركة: تُدمج عبر الدروس؛ غير الدراسية: قسم لكل حصة؛ غيرها: حسب الدرس
                    if kind_cache.get(sub) == "nonteach":
                        origin = ("sec", sec)
                    elif shared_cache.get(sub):
                        origin = ("shared",)
                    else:
                        origin = ("lesson", c.lesson)
                    key = (iso(day), span[0], span[1], sub, tid, rid, origin)
                    if len(l.teachers) > 1:
                        extra_teachers[key] = [split_rank(d.teachers[t][0])[1] for t in l.teachers[1:]]
                    slots[key].add(g)
            n_week = 0
            for key, groups in slots.items():
                ds, s, e, sub, tid, rid, origin = key
                group_sets = [groups]
                if len({g2sec[g] for g in groups}) > 1:
                    rep.merged += 1
                for gs in group_sets:
                    fid = db.scalar("SELECT formation_id FROM sections WHERE id=?", (g2sec[min(gs)],))
                    tkey = (fid, w)
                    if tkey not in tt_ids:
                        ex = db.one("SELECT id FROM timetables WHERE formation_id=? AND week_start=? AND source='roz'",
                                    (fid, iso(ws)))
                        tt_ids[tkey] = ex["id"] if ex else db.insert(
                            "timetables", formation_id=fid, week_start=iso(ws), status="draft", source="roz",
                            imported_week=w, note=f"مستورد من aSc — الأسبوع {w}")
                    status = "done" if date.fromisoformat(ds) < today else "planned"
                    note = ("مع: " + "، ".join(extra_teachers[key])) if key in extra_teachers else None
                    sid_ = db.insert("sessions", timetable_id=tt_ids[tkey], date=ds, start_min=s, end_min=e,
                                     subject_id=sub, teacher_id=tid, room_id=rid, status=status, manual=0,
                                     imported=1, note=note)
                    db.conn.executemany("INSERT INTO session_groups VALUES (?,?)", [(sid_, g) for g in gs])
                    n_week += 1
                    if tid and kind_cache.get(sub) != "nonteach":
                        for g in gs:
                            acc = req_acc[(g, sub, tid)]
                            acc["min"] += e - s
                            acc["durs"][e - s] += 1
                            acc["weeks"].add(w)
                        sess_req.append((sid_, (min(gs), sub, tid)))
            if dropped:
                rep.warnings.append(f"الأسبوع {w}: {dropped} بطاقة خارج فترات الطور لم تُستورد.")
            rep.per_week[w] = n_week
            rep.sessions += n_week
            if progress:
                progress(f"الأسبوع {w}: {n_week} حصة")

        # ------------------------------------------------ فترة الغداء لكل قسم (من بطاقات «وجبة الغذاء»)
        for sec, votes in lunch_votes.items():
            p, _ = votes.most_common(1)[0]
            if p != pm.lunch(sec):
                db.execute("UPDATE sections SET lunch_period=? WHERE id=?", (p, sec))

        # ------------------------------------------------ المتطلبات المرجعية (نفس الأساتذة) والأهلية
        nweeks = max(1, len(datas))
        fid_of_group = {r[0]: r[1] for r in db.q("SELECT g.id, s.formation_id FROM groups_ g JOIN sections s ON s.id=g.section_id")}
        req_ids = {}
        for (g, sub, tid), acc in req_acc.items():
            db.execute("INSERT OR IGNORE INTO teacher_subjects VALUES (?,?)", (tid, sub))
            ex = db.one("SELECT id FROM requirements WHERE group_id=? AND subject_id=? AND COALESCE(teacher_id,0)=?",
                        (g, sub, tid))
            dur = acc["durs"].most_common(1)[0][0]
            weekly = round(acc["min"] / 60 / nweeks, 2)
            share = f"S{sub}-T{tid}" if shared_cache.get(sub) else None
            if ex:
                req_ids[(g, sub, tid)] = ex["id"]
                db.execute("UPDATE requirements SET weekly_hours=?, session_minutes=?, share_code=COALESCE(share_code, ?) "
                           "WHERE id=?", (weekly, dur, share, ex["id"]))
            else:
                req_ids[(g, sub, tid)] = db.insert("requirements", formation_id=fid_of_group[g], group_id=g,
                                                   subject_id=sub, teacher_id=tid, weekly_hours=weekly,
                                                   total_hours=0, session_minutes=dur, share_code=share)
        db.conn.executemany("UPDATE sessions SET requirement_id=? WHERE id=?",
                            [(req_ids[k], sid_) for sid_, k in sess_req if k in req_ids])

        # ------------------------------------------------ اللقطة الأصلية
        for tt in set(tt_ids.values()):
            db.execute("DELETE FROM timetable_snapshots WHERE timetable_id=? AND label='الأصل المستورد'", (tt,))
            snapshot(db, tt, "الأصل المستورد")

    # ------------------------------------------------ تجاهل التعارضات الموجودة في الملفات
    if datas:
        first, last = week_start_of(min(datas), week1), week_start_of(max(datas), week1) + timedelta(days=6)
        cs = [c for c in C.find_conflicts(db, first, last) if not c.ignored]
        C.ignore(db, [c.key for c in cs], "موجود في ملف aSc المستورد")
        rep.ignored_conflicts = len(cs)
    db.set_setting("week1_start", iso(week1))
    db.log("استيراد الأسابيع السابقة", "import", None, {"weeks": rep.weeks, "sessions": rep.sessions})
    return rep
