"""تصدير أسبوع إلى صيغة aSc Timetables (XML) — الطريق المعاكس للاستيراد من ‎.roz‎.

لماذا XML وليس ‎.roz‎ مباشرة؟ ملف ‎.roz‎ صيغة ثنائية مغلقة؛ قارئ البرنامج
(`dpp/importers/roz.py`) استُخرج بالهندسة العكسية ويقرأ ما يلزمنا فقط، فكتابة ملف
‎.roz‎ جديد من الصفر تنتج ملفاً ناقصاً يرفضه aSc. أما **XML فهي صيغة الاستيراد
الرسمية في aSc**: في aSc اختر «ملف ← استيراد ← XML» ثم احفظ باسم ‎.roz‎، فتكون
دورة كاملة: ‎.roz‎ ← DPP ← XML ← ‎.roz‎.

ما يُصدَّر لأسبوع واحد: الأيام، الفترات، المواد، الأساتذة، القاعات، الأقسام،
الأفواج، الدروس (lessons) والبطاقات (cards) بمواضعها الفعلية.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

from ..db.database import Database
from ..utils import hm, iso, make_abbrev, parse_rest_days, to_date, week_days, week_start

DAY_NAMES = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]


def _esc(v) -> str:
    return "" if v is None else str(v)


def _periods(db: Database, profile: str = "default") -> list[dict]:
    """فترات الملف الزمني؛ إن لم تُعرَّف، تُشتق من حصص الأسبوع نفسه."""
    rows = db.q("SELECT idx, label, start_min, end_min FROM periods WHERE profile=? ORDER BY idx", (profile,))
    return [{"idx": r[0], "label": r[1], "start": r[2], "end": r[3]} for r in rows]


def _periods_from_sessions(sess: list[dict]) -> list[dict]:
    spans = sorted({(s["start_min"], s["end_min"]) for s in sess})
    return [{"idx": i + 1, "label": str(i + 1), "start": a, "end": b} for i, (a, b) in enumerate(spans)]


def collect(db: Database, ws, formation_ids: list[int] | None = None) -> dict:
    """يجمع كل ما يلزم تصديره لأسبوع واحد."""
    ws = week_start(to_date(ws))
    days = week_days(ws)
    d0, d1 = iso(days[0]), iso(days[-1])
    where, args = "s.date BETWEEN ? AND ?", [d0, d1]
    if formation_ids:
        qs = ",".join("?" * len(formation_ids))
        where += f" AND t.formation_id IN ({qs})"
        args += list(formation_ids)
    rows = db.q(f"""SELECT s.id, s.date, s.start_min, s.end_min, s.subject_id, s.teacher_id, s.room_id,
                           t.formation_id
                    FROM sessions s JOIN timetables t ON t.id=s.timetable_id
                    WHERE {where} ORDER BY s.date, s.start_min, s.id""", tuple(args))
    sess = [{"id": r[0], "date": to_date(r[1]), "start_min": r[2], "end_min": r[3], "subject_id": r[4],
             "teacher_id": r[5], "room_id": r[6], "formation_id": r[7]} for r in rows]
    gmap: dict[int, list[int]] = {}
    for sid, gid in db.q("""SELECT sg.session_id, sg.group_id FROM session_groups sg
                            JOIN sessions s ON s.id=sg.session_id
                            JOIN timetables t ON t.id=s.timetable_id
                            WHERE s.date BETWEEN ? AND ?""", (d0, d1)):
        gmap.setdefault(sid, []).append(gid)
    for s in sess:
        s["groups"] = gmap.get(s["id"], [])
    return {"ws": ws, "days": days, "sessions": sess}


def build_xml(db: Database, ws, formation_ids: list[int] | None = None, profile: str = "default") -> ET.Element:
    data = collect(db, ws, formation_ids)
    sess, days = data["sessions"], data["days"]

    periods = _periods(db, profile) or _periods_from_sessions(sess)
    pidx = {}
    for p in periods:
        pidx[(p["start"], p["end"])] = p["idx"]

    def period_of(s) -> tuple[int, int]:
        """(رقم الفترة، عدد الفترات الإضافية) لحصة قد تغطي عدة فترات."""
        start = min((p["idx"] for p in periods if p["start"] <= s["start_min"] < p["end"]), default=None)
        if start is None:
            start = pidx.get((s["start_min"], s["end_min"]), 1)
        covered = [p for p in periods if p["start"] >= s["start_min"] and p["end"] <= s["end_min"]]
        return start, max(1, len(covered))

    # أيام العمل: أيام الأسبوع كلها ما لم تكن كل التكوينات تستريح في يوم
    rest: set[int] = set()
    frows = db.q("SELECT id, rest_days FROM formations") if _has_col(db, "formations", "rest_days") else []
    if frows:
        sets = [parse_rest_days(r[1]) for r in frows
                if not formation_ids or r[0] in formation_ids]
        if sets:
            rest = set.intersection(*sets) if len(sets) > 1 else sets[0]
    work_days = [i for i in range(7) if i not in rest] or list(range(7))

    used_subj = {s["subject_id"] for s in sess}
    used_teach = {s["teacher_id"] for s in sess if s["teacher_id"]}
    used_room = {s["room_id"] for s in sess if s["room_id"]}
    used_group = {g for s in sess for g in s["groups"]}

    root = ET.Element("timetable", {"importtype": "database", "options": "idprefix:dpp,separator:,",
                                    "defaultexport": "xml"})
    ET.SubElement(root, "descr").text = f"DPP — الأسبوع {iso(data['ws'])}"

    # ---- الأيام والفترات ----
    pe = ET.SubElement(root, "periods")
    for p in periods:
        ET.SubElement(pe, "period", {"name": p["label"], "short": p["label"], "period": str(p["idx"]),
                                     "starttime": hm(p["start"]), "endtime": hm(p["end"])})
    dd = ET.SubElement(root, "daysdefs", {"options": "canadd,canremove,canupdate,silent", "columns": "name,short,days"})
    for i, di in enumerate(work_days):
        bits = ["0"] * len(work_days)
        bits[i] = "1"
        ET.SubElement(dd, "daysdef", {"id": f"dpp_day{di}", "name": DAY_NAMES[di], "short": DAY_NAMES[di][:3],
                                      "days": "".join(bits)})
    ET.SubElement(dd, "daysdef", {"id": "dpp_anyday", "name": "أي يوم", "short": "*",
                                  "days": ",".join("".join("1" if j == i else "0" for j in range(len(work_days)))
                                                   for i in range(len(work_days)))})
    wd = ET.SubElement(root, "weeksdefs", {"options": "canadd,canremove,canupdate,silent", "columns": "name,short,weeks"})
    ET.SubElement(wd, "weeksdef", {"id": "dpp_wholeyear", "name": "كل الأسابيع", "short": "كل", "weeks": "1"})
    td = ET.SubElement(root, "termsdefs", {"options": "canadd,canremove,canupdate,silent", "columns": "name,short,terms"})
    ET.SubElement(td, "termsdef", {"id": "dpp_wholeyear", "name": "كل السنة", "short": "كل", "terms": "1"})

    # ---- الكيانات ----
    se = ET.SubElement(root, "subjects", {"options": "canadd,canremove,canupdate,silent", "columns": "name,short"})
    for sid, name, short in db.q("SELECT id, name, COALESCE(short, '') FROM subjects ORDER BY id"):
        if sid in used_subj:
            ET.SubElement(se, "subject", {"id": f"dpp_s{sid}", "name": _esc(name), "short": _esc(short or name)[:12]})

    te = ET.SubElement(root, "teachers", {"options": "canadd,canremove,canupdate,silent", "columns": "name,short"})
    for tid, name in db.q("SELECT id, full_name FROM teachers ORDER BY id"):
        if tid in used_teach:
            ET.SubElement(te, "teacher", {"id": f"dpp_t{tid}", "name": _esc(name),
                                          "short": make_abbrev(_esc(name), 12)})

    re_ = ET.SubElement(root, "classrooms", {"options": "canadd,canremove,canupdate,silent", "columns": "name,short"})
    for rid, name, short in db.q("SELECT id, name, COALESCE(short, '') FROM rooms ORDER BY id"):
        if rid in used_room:
            ET.SubElement(re_, "classroom", {"id": f"dpp_r{rid}", "name": _esc(name), "short": _esc(short or name)[:12]})

    sections = db.q("""SELECT DISTINCT sec.id, sec.name, COALESCE(sec.short, '') FROM sections sec
                       JOIN groups_ g ON g.section_id=sec.id ORDER BY sec.id""")
    sec_used = {}
    for gid, secid in db.q("SELECT id, section_id FROM groups_"):
        if gid in used_group:
            sec_used[secid] = True
    ce = ET.SubElement(root, "classes", {"options": "canadd,canremove,canupdate,silent", "columns": "name,short"})
    for secid, name, short in sections:
        if secid in sec_used:
            ET.SubElement(ce, "class", {"id": f"dpp_c{secid}", "name": _esc(name), "short": _esc(short or name)[:12]})

    ge = ET.SubElement(root, "groups", {"options": "canadd,canremove,canupdate,silent",
                                        "columns": "classid,name,entireclass"})
    for gid, secid, name, whole in db.q("SELECT id, section_id, name, COALESCE(is_whole, 0) FROM groups_ ORDER BY id"):
        if gid in used_group:
            ET.SubElement(ge, "group", {"id": f"dpp_g{gid}", "classid": f"dpp_c{secid}", "name": _esc(name),
                                        "entireclass": "1" if whole else "0"})

    # ---- الدروس والبطاقات ----
    # درس واحد لكل (مادة، أستاذ، أفواج): aSc يربط البطاقات بالدروس
    lessons: dict[tuple, dict] = {}
    for s in sess:
        key = (s["subject_id"], s["teacher_id"], tuple(sorted(s["groups"])))
        lessons.setdefault(key, {"id": f"dpp_l{len(lessons) + 1}", "cards": []})["cards"].append(s)

    le = ET.SubElement(root, "lessons", {"options": "canadd,canremove,canupdate,silent",
                                         "columns": "classids,subjectid,teacherids,groupids,durationperiods,"
                                                    "periodsperweek,daysdefid,weeksdefid,termsdefid"})
    for (subj, teach, groups), lz in lessons.items():
        secs = sorted({r[0] for r in db.q(
            f"SELECT section_id FROM groups_ WHERE id IN ({','.join('?' * len(groups))})", groups)}) if groups else []
        dur = max((period_of(c)[1] for c in lz["cards"]), default=1)
        ET.SubElement(le, "lesson", {
            "id": lz["id"],
            "classids": ",".join(f"dpp_c{i}" for i in secs),
            "subjectid": f"dpp_s{subj}",
            "teacherids": f"dpp_t{teach}" if teach else "",
            "groupids": ",".join(f"dpp_g{g}" for g in groups),
            "durationperiods": str(dur),
            "periodsperweek": str(sum(period_of(c)[1] for c in lz["cards"])),
            "daysdefid": "dpp_anyday", "weeksdefid": "dpp_wholeyear", "termsdefid": "dpp_wholeyear"})

    cards_el = ET.SubElement(root, "cards", {"options": "canadd,canremove,canupdate,silent",
                                       "columns": "lessonid,period,days,weeks,terms,classroomids"})
    for lz in lessons.values():
        for c in lz["cards"]:
            di = (c["date"] - data["ws"]).days
            if di not in work_days:
                continue
            bits = ["0"] * len(work_days)
            bits[work_days.index(di)] = "1"
            ET.SubElement(cards_el, "card", {
                "lessonid": lz["id"], "period": str(period_of(c)[0]), "days": "".join(bits),
                "weeks": "1", "terms": "1",
                "classroomids": f"dpp_r{c['room_id']}" if c["room_id"] else ""})
    return root


def _has_col(db: Database, table: str, col: str) -> bool:
    try:
        return any(r[1] == col for r in db.q(f"PRAGMA table_info({table})"))
    except Exception:
        return False


def export_week_xml(db: Database, ws, path: str | Path, formation_ids: list[int] | None = None,
                    profile: str = "default") -> dict:
    """يكتب ملف XML يستورده aSc، ويعيد ملخّص ما صُدِّر."""
    root = build_xml(db, ws, formation_ids, profile)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, "  ")
    ET.ElementTree(root).write(path, encoding="UTF-8", xml_declaration=True)
    count = {t: len(root.findall(f"{p}/{t}")) for p, t in
             (("subjects", "subject"), ("teachers", "teacher"), ("classrooms", "classroom"),
              ("classes", "class"), ("groups", "group"), ("lessons", "lesson"), ("cards", "card"))}
    count["path"] = str(path)
    return count


def default_name(db: Database, ws) -> str:
    ws = week_start(to_date(ws))
    try:
        from ..services.grid import week_number
        n = week_number(db, ws)
    except Exception:
        n = None
    return f"الأسبوع {n} — {iso(ws)}.xml" if n else f"{iso(ws)}.xml"
