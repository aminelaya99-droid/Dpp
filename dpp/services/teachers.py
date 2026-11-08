"""ملف الأستاذ: ساعاته في كل أسبوع، الأقسام والمواد التي درّسها، غياباته وتعويضاته."""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from ..db.database import Database
from ..utils import iso, to_date, week_start


def profile(db: Database, teacher_id: int, today=None) -> dict:
    today = to_date(today or date.today())
    t = db.one("""SELECT t.*, c.name cat FROM teachers t LEFT JOIN teacher_categories c ON c.id=t.category_id
                  WHERE t.id=?""", (teacher_id,))
    if not t:
        return {}
    rows = db.q("""SELECT s.id, s.date, s.start_min, s.end_min, s.status, s.teacher_id, s.substitute_id,
                          sub.name sname, COALESCE(sub.kind,'teach') kind,
                          GROUP_CONCAT(DISTINCT sec.short) secs, GROUP_CONCAT(DISTINCT sec.id) sec_ids
                   FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                   LEFT JOIN session_groups sg ON sg.session_id=s.id LEFT JOIN groups_ g ON g.id=sg.group_id
                   LEFT JOIN sections sec ON sec.id=g.section_id
                   WHERE (s.teacher_id=? OR s.substitute_id=?) AND s.status IN ('planned','done','postponed')
                   GROUP BY s.id ORDER BY s.date, s.start_min""", (teacher_id, teacher_id))
    weeks: dict[str, dict] = defaultdict(lambda: {"planned": 0.0, "done": 0.0, "as_sub": 0.0, "replaced": 0.0,
                                                  "postponed": 0.0, "sections": set(), "subjects": set()})
    pairs: dict[tuple, dict] = defaultdict(lambda: {"total": 0.0, "done": 0.0, "weeks": set(), "last": ""})
    for r in rows:
        if r["kind"] == "nonteach":
            continue
        h = (r["end_min"] - r["start_min"]) / 60
        w = iso(week_start(to_date(r["date"])))
        wk = weeks[w]
        mine = (r["substitute_id"] or r["teacher_id"]) == teacher_id
        if not mine:                 # عوّضه أستاذ آخر
            wk["replaced"] += h
            continue
        if r["status"] == "postponed":
            wk["postponed"] += h
            continue
        if r["substitute_id"] == teacher_id:
            wk["as_sub"] += h
        wk["planned"] += h
        if r["status"] == "done":
            wk["done"] += h
        secs = [x for x in (r["secs"] or "").split(",") if x]
        wk["sections"].update(secs)
        wk["subjects"].add(r["sname"])
        for sec in secs or ["—"]:
            p = pairs[(sec, r["sname"])]
            p["total"] += h
            if r["status"] == "done":
                p["done"] += h
            p["weeks"].add(w)
            p["last"] = max(p["last"], r["date"])
    week_list = [{"week": w, **{k: (round(v, 2) if isinstance(v, float) else sorted(v)) for k, v in d.items()}}
                 for w, d in sorted(weeks.items())]
    pair_list = sorted(({"section": k[0], "subject": k[1], "total": round(v["total"], 2), "done": round(v["done"], 2),
                         "weeks": len(v["weeks"]), "last": v["last"]} for k, v in pairs.items()),
                       key=lambda d: (d["section"], d["subject"]))
    cur = iso(week_start(today))
    worked = [w for w in week_list if w["planned"] > 0]
    done_total = sum(w["done"] for w in week_list)
    absences = [dict(a) for a in db.q("SELECT * FROM absences WHERE teacher_id=? ORDER BY start_date DESC",
                                      (teacher_id,))]
    return {
        "teacher": dict(t), "weeks": week_list, "pairs": pair_list, "absences": absences,
        "this_week": next((w["planned"] for w in week_list if w["week"] == cur), 0.0),
        "done_total": round(done_total, 2),
        "planned_future": round(sum(w["planned"] - w["done"] for w in week_list if w["week"] >= cur), 2),
        "avg_week": round(done_total / max(1, len([w for w in worked if w["week"] < cur])), 2),
        "sections": sorted({p["section"] for p in pair_list if p["section"] != "—"}),
        "subjects": sorted({p["subject"] for p in pair_list}),
        "as_sub_total": round(sum(w["as_sub"] for w in week_list), 2),
        "replaced_total": round(sum(w["replaced"] for w in week_list), 2),
        "absent_today": next((a for a in absences if a["start_date"] <= iso(today) <= a["end_date"]), None),
    }


# ---------------------------------------------------------------- الاسم المختصر على البطاقات
SURNAME_SUFFIX = {"الله", "الدين", "الرحمان", "الرحمن", "القادر", "الحق", "النور"}
SURNAME_PREFIX = {"بن", "ابن", "بو", "عبد", "آيت", "ايت", "أيت", "ولد", "سي", "أبو", "ابو", "آل", "بني"}


def surname_parts(full_name: str) -> tuple[str, str]:
    """(اللقب، الاسم) من «اللقب الاسم»؛ اللقب المركب (بن هادي، عبد الله، آيت…) كلمتان."""
    words = (full_name or "").split()
    if not words:
        return "", ""
    n = 2 if len(words) > 2 and (words[0] in SURNAME_PREFIX or words[1] in SURNAME_SUFFIX) else 1
    return " ".join(words[:n]), " ".join(words[n:])


def short_names(db: Database) -> dict[int, str]:
    """اسم الأستاذ على البطاقة: اللقب فقط، ويُضاف أول حرف من الاسم إذا تشابه لقبان («يحياوي م.»).
    الأسماء التي ليست لأشخاص (بلا رتبة و3 كلمات فأكثر، مثل «قائد المجموعة الفرعية…») تبقى كاملة."""
    rows = db.q("SELECT id, full_name, COALESCE(rank,'') rank FROM teachers")
    parts, out = {}, {}
    for r in rows:
        name = (r["full_name"] or "").strip()
        if not r["rank"] and len(name.split()) >= 3:
            out[r["id"]] = name
            continue
        parts[r["id"]] = surname_parts(name)
    count: dict[str, int] = defaultdict(int)
    for sur, _g in parts.values():
        count[sur] += 1
    for tid, (sur, given) in parts.items():
        out[tid] = f"{sur} {given[0]}." if count[sur] > 1 and given else sur
    # إذا بقي تشابه بعد الحرف الأول (نفس اللقب ونفس أول حرف) نضيف الاسم كاملاً
    seen: dict[str, list[int]] = defaultdict(list)
    for tid in parts:
        seen[out[tid]].append(tid)
    for lab, tids in seen.items():
        if len(tids) > 1:
            for tid in tids:
                sur, given = parts[tid]
                out[tid] = f"{sur} {given}".strip()
    return out
