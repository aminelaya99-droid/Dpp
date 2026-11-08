"""الأسابيع المبرمجة: سطر لكل أسبوع فيه حصص — المعلومات الأساسية، الحالة، التعارضات، نسب التنفيذ،
آخر تعديل ومن قام به، وملاحظة حرة (محفوظة في week_notes)."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import timedelta

from ..db.database import Database
from ..utils import iso, to_date, week_start
from . import conflicts as CF


def notes(db: Database) -> dict:
    try:
        return json.loads(db.get_setting("week_notes", "") or "{}")
    except Exception:
        return {}


def set_note(db: Database, ws, text: str) -> None:
    n = notes(db)
    key = iso(week_start(ws))
    if text.strip():
        n[key] = text.strip()
    else:
        n.pop(key, None)
    db.set_setting("week_notes", json.dumps(n, ensure_ascii=False))


def weeks(db: Database, formation_ids: list[int] | None = None, with_conflicts: bool = True) -> list[dict]:
    from ..exporters.official import week_number
    fsql, fp = "", []
    if formation_ids:
        fsql = f" AND t.formation_id IN ({','.join('?' * len(formation_ids))})"
        fp = list(formation_ids)
    rows = db.q(f"""SELECT s.id, s.date, s.status, s.imported, s.end_min-s.start_min m, t.formation_id, t.id tt,
                           t.status tts, COALESCE(sub.kind,'teach') kind
                    FROM sessions s JOIN timetables t ON t.id=s.timetable_id JOIN subjects sub ON sub.id=s.subject_id
                    JOIN formations f ON f.id=t.formation_id
                    WHERE s.status<>'tray' AND f.archived=0 {fsql}""", fp)
    if not rows:
        return []
    by_week: dict[str, dict] = {}
    sids_week: dict[int, str] = {}
    for r in rows:
        ws = iso(week_start(to_date(r["date"])))
        w = by_week.setdefault(ws, {"ws": ws, "sessions": 0, "teach": 0, "done": 0, "postponed": 0, "cancelled": 0,
                                    "imported": 0, "tts": {}, "minutes": 0})
        w["sessions"] += 1
        w["minutes"] += r["m"] or 0
        if r["imported"]:
            w["imported"] += 1
        if r["kind"] != "nonteach":
            w["teach"] += 1
            if r["status"] in ("done", "postponed", "cancelled"):
                w[r["status"]] += 1
        w["tts"][r["tt"]] = r["tts"]
        sids_week[r["id"]] = ws
    # الأقسام
    sec_rows = db.q(f"""SELECT DISTINCT s.date, g.section_id FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                        JOIN groups_ g ON g.id=sg.group_id JOIN timetables t ON t.id=s.timetable_id
                        WHERE s.status NOT IN ('tray','cancelled') {fsql}""", fp)
    secs = defaultdict(set)
    for r in sec_rows:
        secs[iso(week_start(to_date(r["date"])))].add(r["section_id"])
    # آخر تعديل: من سجل العمليات (الحصص والجداول)
    tt_week = {tt: ws for ws, w in by_week.items() for tt in w["tts"]}
    last: dict[str, tuple[str, str]] = {}
    for a in db.q("""SELECT entity, entity_id, MAX(ts) ts, username FROM audit_log
                     WHERE entity IN ('sessions','timetables') AND entity_id IS NOT NULL
                     GROUP BY entity, entity_id"""):
        ws = sids_week.get(a["entity_id"]) if a["entity"] == "sessions" else tt_week.get(a["entity_id"])
        if ws and (ws not in last or a["ts"] > last[ws][0]):
            last[ws] = (a["ts"], a["username"] or "")
    conf = defaultdict(int)
    if with_conflicts:
        d0 = min(to_date(w) for w in by_week)
        d1 = max(to_date(w) for w in by_week) + timedelta(days=6)
        for c in CF.find_conflicts(db, d0, d1):
            if not c.ignored:
                conf[iso(week_start(to_date(c.date)))] += 1
    nts = notes(db)
    out = []
    for ws in sorted(by_week):
        w = by_week[ws]
        st = list(w["tts"].values())
        status = ("approved" if st and all(x == "approved" for x in st) else
                  "partial" if any(x == "approved" for x in st) else "draft")
        t = max(1, w["teach"])
        lt = last.get(ws, ("", ""))
        out.append({"ws": ws, "number": week_number(db, to_date(ws)), "we": iso(to_date(ws) + timedelta(days=6)),
                    "sessions": w["sessions"], "sections": len(secs.get(ws, ())), "hours": round(w["minutes"] / 60, 1),
                    "status": status, "imported": w["imported"] > 0, "conflicts": conf.get(ws, 0),
                    "done_pct": round(w["done"] / t * 100), "postponed_pct": round(w["postponed"] / t * 100),
                    "cancelled_pct": round(w["cancelled"] / t * 100), "last": lt[0], "by": lt[1],
                    "note": nts.get(ws, ""), "timetables": sorted(w["tts"])})
    return out


STATUS_LABELS = {"approved": "معتمد", "partial": "معتمد جزئياً", "draft": "مسودة"}


def approve_week(db: Database, ws, formation_ids: list[int] | None = None) -> int:
    from . import timetables as T
    n = 0
    for w in weeks(db, formation_ids, with_conflicts=False):
        if w["ws"] == iso(week_start(ws)):
            for tt in w["timetables"]:
                if T.timetable_status(db, tt) != "approved":
                    T.approve(db, tt)
                    n += 1
    return n


def reopen_week(db: Database, ws, formation_ids: list[int] | None = None) -> int:
    from . import timetables as T
    n = 0
    for w in weeks(db, formation_ids, with_conflicts=False):
        if w["ws"] == iso(week_start(ws)):
            for tt in w["timetables"]:
                if T.timetable_status(db, tt) == "approved":
                    T.reopen(db, tt)
                    n += 1
    return n


def copy_week(db: Database, src_ws, dst_ws, formation_ids: list[int] | None = None, force=False) -> tuple[int, list[str]]:
    """ينسخ الأسبوع لكل تكوين فيه حصص. يعيد (عدد الحصص المنسوخة، ما لم يُنسخ وسببه)."""
    from . import timetables as T
    fids = sorted({r[0] for r in db.q("""SELECT DISTINCT t.formation_id FROM sessions s JOIN timetables t
                                        ON t.id=s.timetable_id WHERE s.date BETWEEN ? AND ?""",
                                     (iso(week_start(src_ws)), iso(week_start(src_ws) + timedelta(days=6))))})
    if formation_ids:
        fids = [f for f in fids if f in formation_ids]
    total, skipped = 0, []
    for f in fids:
        try:
            n, sk = T.copy_week(db, f, src_ws, dst_ws, force=force)
        except T.ConflictError as e:
            skipped += list(e.conflicts)
            continue
        total += n
        skipped += sk
    db.log("نسخ أسبوع", "timetables", None, {"from": iso(week_start(src_ws)), "to": iso(week_start(dst_ws)),
                                              "sessions": total})
    return total, skipped
