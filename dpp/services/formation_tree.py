"""مخطط التكوين: الشجرة (تكوين ← شهادة ← سنة/طور ← اختصاص ← أقسام) ومراحل التكوين بالأسابيع.

مراحل الاحتياط (افتراضياً): استقبال أسبوع ← قاعدي مشترك 6 أسابيع ← إجازة أسبوع ← تخصصي (مدته حسب نوع التربص
في كل اختصاص). تُحوَّل المراحل إلى أسطر في المخطط الزمني لكل دفعة، فيعرف البرنامج المرحلة الحالية لكل قسم.
المخطط الزمني المستورد من Excel هو المرجع: لا يُستبدل إلا بطلب صريح.
"""
from __future__ import annotations

from datetime import timedelta

from ..db.database import Database
from ..utils import iso, to_date, week_start

PHASE_KINDS = {"reception": "استقبال", "basic": "تكوين قاعدي مشترك", "leave": "إجازة", "specialized": "تكوين تخصصي"}
RESERVE_DEFAULT = [("reception", "الاستقبال", 1), ("basic", "التكوين القاعدي المشترك", 6), ("leave", "الإجازة", 1),
                   ("specialized", "التكوين التخصصي", 8)]
GENERATED_LABEL = "مراحل DPP"

# الشهادة والسنة المعروفة لكل طور (قابلة للتعديل من الشجرة)
KNOWN = {"BMP1": (None, 1), "BMP2": (None, 2),
         "ESOC1": ("شهادة عسكرية مهنية درجة ثانية", 1), "ESOC2": ("شهادة عسكرية مهنية درجة ثانية", 2)}
YEAR_LABELS = {1: "السنة الأولى", 2: "السنة الثانية", 3: "السنة الثالثة"}


def ensure_defaults(db: Database) -> None:
    """يملأ الشهادة والسنة المعروفة للأطوار الفارغة، ومراحل الاحتياط الافتراضية إن لم توجد."""
    with db.tx():
        for code, (cert, year) in KNOWN.items():
            r = db.one("SELECT id, certificate, year_no FROM levels WHERE code=?", (code,))
            if not r:
                continue
            if cert and not r["certificate"]:
                db.execute("UPDATE levels SET certificate=? WHERE id=?", (cert, r["id"]))
            if year and not r["year_no"]:
                db.execute("UPDATE levels SET year_no=? WHERE id=?", (year, r["id"]))
        f = db.one("SELECT id FROM formations WHERE short='R'")
        if f and not db.scalar("SELECT COUNT(*) FROM formation_phases WHERE formation_id=?", (f["id"],), 0):
            for i, (k, lab, w) in enumerate(RESERVE_DEFAULT):
                db.execute("INSERT INTO formation_phases(formation_id, idx, kind, label, weeks) VALUES (?,?,?,?,?)",
                           (f["id"], i, k, lab, w))


def phases(db: Database, formation_id: int) -> list[dict]:
    return [dict(r) for r in db.q("SELECT * FROM formation_phases WHERE formation_id=? ORDER BY idx", (formation_id,))]


def save_phases(db: Database, formation_id: int, rows: list[tuple[str, str, int]]) -> None:
    with db.tx():
        db.execute("DELETE FROM formation_phases WHERE formation_id=?", (formation_id,))
        for i, (k, lab, w) in enumerate(rows):
            db.execute("INSERT INTO formation_phases(formation_id, idx, kind, label, weeks) VALUES (?,?,?,?,?)",
                       (formation_id, i, k, lab, int(w)))
        db.log("تعديل مراحل التكوين", "formations", formation_id, {"phases": rows})


def specialty_weeks(db: Database, specialty_id: int | None, default: int) -> int:
    if not specialty_id:
        return default
    w = db.scalar("SELECT weeks FROM specialties WHERE id=?", (specialty_id,), 0)
    return int(w) if w else default


def schedule(db: Database, formation_id: int, start, specialty_id: int | None = None) -> list[dict]:
    """تواريخ كل مرحلة ابتداءً من start (يُقرَّب إلى بداية الأسبوع): [{kind, label, weeks, start, end}]."""
    d = week_start(to_date(start))
    out = []
    for p in phases(db, formation_id):
        w = specialty_weeks(db, specialty_id, p["weeks"]) if p["kind"] == "specialized" else p["weeks"]
        if w <= 0:
            continue
        out.append({"kind": p["kind"], "label": p["label"], "weeks": w, "start": d,
                    "end": d + timedelta(days=7 * w - 1)})
        d += timedelta(days=7 * w)
    return out


def generate_timeline(db: Database, formation_id: int, replace_imported: bool = False) -> dict:
    """يكتب مراحل التكوين في المخطط الزمني لكل طور × اختصاص × دفعة من التكوين.

    الأطوار التي لها مخطط مستورد من Excel تُترك كما هي إلا إذا طُلب الاستبدال صراحة.
    """
    levels = db.q("SELECT id, code FROM levels WHERE formation_id=? AND code IS NOT NULL", (formation_id,))
    f = db.one("SELECT start_date FROM formations WHERE id=?", (formation_id,))
    written, skipped = 0, []
    with db.tx():
        for lv in levels:
            imported = db.scalar("SELECT COUNT(*) FROM timeline WHERE level_code=? AND row_label<>?",
                                 (lv["code"], GENERATED_LABEL), 0)
            if imported and not replace_imported:
                skipped.append(lv["code"])
                continue
            db.execute("DELETE FROM timeline WHERE level_code=?" + ("" if replace_imported else " AND row_label=?"),
                       (lv["code"],) if replace_imported else (lv["code"], GENERATED_LABEL))
            starts = [r["start_date"] for r in db.q("SELECT start_date FROM cohorts WHERE level_id=? ORDER BY start_date",
                                                    (lv["id"],)) if r["start_date"]] or [f["start_date"]]
            specs = db.q("SELECT id, name FROM specialties WHERE level_id=?", (lv["id"],)) or [None]
            for sp in specs:
                for st in starts:
                    w0 = week_start(to_date(starts[0]))
                    for ph in schedule(db, formation_id, st, sp["id"] if sp else None):
                        d = ph["start"]
                        while d <= ph["end"]:
                            db.execute("""INSERT INTO timeline(row_label, level_code, specialty_like, week_no, week_start,
                                          kind) VALUES (?,?,?,?,?,?)""",
                                       (GENERATED_LABEL, lv["code"], sp["name"] if sp and len(specs) > 1 else None,
                                        (d - w0).days // 7 + 1, iso(d), ph["kind"]))
                            written += 1
                            d += timedelta(days=7)
        db.log("توليد المخطط الزمني من المراحل", "timeline", formation_id, {"weeks": written, "skipped": skipped})
    return {"weeks": written, "skipped": skipped}


# ------------------------------------------------------------------ الشجرة
def tree(db: Database) -> list[dict]:
    """[{formation, certificates: [{name, levels: [{level, specialties: [{specialty, sections: [...]}]}]}]}]
    مع الأعداد: الأقسام، المواد المقررة، الساعات المقررة."""
    cur_n = {(r[0], r[1]): (r[2], r[3]) for r in db.q(
        "SELECT level_id, specialty_id, COUNT(DISTINCT subject_id), SUM(hours) FROM curriculum GROUP BY 1, 2")}
    out = []
    for f in db.q("SELECT * FROM formations WHERE archived=0 ORDER BY id"):
        fd = {"id": f["id"], "name": f["name"], "start": f["start_date"], "end": f["end_date"], "certificates": []}
        certs: dict[str, dict] = {}
        for lv in db.q("SELECT * FROM levels WHERE formation_id=? ORDER BY COALESCE(sort, 99), id", (f["id"],)):
            cert = lv["certificate"] or ""
            c = certs.setdefault(cert, {"name": cert, "levels": []})
            ld = {"id": lv["id"], "code": lv["code"] or "", "name": lv["name"], "year": lv["year_no"],
                  "color": lv["color"] or "#888", "specialties": []}
            specs = [dict(r) for r in db.q("SELECT * FROM specialties WHERE level_id=? ORDER BY name", (lv["id"],))]
            for sp in specs + [{"id": None, "name": "بلا اختصاص", "internship": None, "weeks": 0}]:
                secs = [dict(r) for r in db.q(
                    "SELECT id, short, name FROM sections WHERE level_id=? AND " +
                    ("specialty_id=?" if sp["id"] else "specialty_id IS NULL") + " ORDER BY sort, id",
                    (lv["id"], sp["id"]) if sp["id"] else (lv["id"],))]
                if sp["id"] is None and not secs:
                    continue
                n, h = cur_n.get((lv["id"], sp["id"] or 0), (0, 0))
                ld["specialties"].append({"id": sp["id"], "name": sp["name"], "internship": sp.get("internship"),
                                          "weeks": sp.get("weeks") or 0, "sections": secs,
                                          "subjects": n, "hours": h or 0})
            c["levels"].append(ld)
        fd["certificates"] = list(certs.values())
        out.append(fd)
    return out


def move_section(db: Database, section_id: int, level_id: int, specialty_id: int | None) -> None:
    with db.tx():
        db.execute("UPDATE sections SET level_id=?, specialty_id=? WHERE id=?", (level_id, specialty_id, section_id))
        db.log("نقل قسم في مخطط التكوين", "sections", section_id, {"level": level_id, "specialty": specialty_id})


def section_impact(db: Database, section_id: int) -> dict:
    return {"sessions": db.scalar("""SELECT COUNT(DISTINCT sg.session_id) FROM session_groups sg JOIN groups_ g
                                     ON g.id=sg.group_id WHERE g.section_id=?""", (section_id,), 0)}
