"""استيراد الأقسام والأساتذة والمواد والقاعات من Excel مع مطابقة الأعمدة والتحقق."""
from __future__ import annotations

from dataclasses import dataclass, field

from openpyxl import load_workbook

from ..db.database import Database
from ..utils import make_abbrev, unique_abbrev

ENTITIES = {
    "teachers": {"label": "الأساتذة", "fields": {"full_name": "الاسم واللقب*", "rank": "الرتبة", "category": "التصنيف",
                                                 "specialty": "التخصص"}},
    "subjects": {"label": "المواد", "fields": {"name": "اسم المادة*", "short": "الاختصار", "shareable": "قابلة للمشاركة"}},
    "rooms": {"label": "القاعات", "fields": {"name": "اسم القاعة*", "short": "الاختصار", "capacity": "السعة",
                                             "kind": "النوع"}},
    "sections": {"label": "الأقسام", "fields": {"name": "اسم القسم*", "short": "الاختصار", "size": "العدد"}},
}
TRUE = {"1", "نعم", "yes", "oui", "true", "x", "✓"}


@dataclass
class RowIssue:
    row: int
    message: str


@dataclass
class ExcelResult:
    added: int = 0
    skipped: int = 0
    issues: list[RowIssue] = field(default_factory=list)


def read_sheet(path: str, sheet: str | None = None) -> tuple[list[str], list[list]]:
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[sheet] if sheet else wb.active
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        return [], []
    headers = [str(c).strip() if c is not None else f"عمود {i + 1}" for i, c in enumerate(rows[0])]
    return headers, rows[1:]


def guess_mapping(entity: str, headers: list[str]) -> dict[str, int | None]:
    out = {}
    for key, label in ENTITIES[entity]["fields"].items():
        lab = label.rstrip("*")
        idx = next((i for i, h in enumerate(headers) if lab in h or h in lab or h.lower() == key), None)
        out[key] = idx
    return out


def validate(entity: str, mapping: dict[str, int | None], rows: list[list]) -> list[RowIssue]:
    issues = []
    required = [k for k, v in ENTITIES[entity]["fields"].items() if v.endswith("*")]
    for k in required:
        if mapping.get(k) is None:
            issues.append(RowIssue(0, f"العمود الإلزامي «{ENTITIES[entity]['fields'][k]}» غير مطابق."))
    if issues:
        return issues
    seen = set()
    for n, r in enumerate(rows, start=2):
        for k in required:
            v = r[mapping[k]] if mapping[k] < len(r) else None
            if v in (None, ""):
                issues.append(RowIssue(n, "قيمة إلزامية فارغة."))
        key = str(r[mapping[required[0]]]).strip() if mapping[required[0]] < len(r) else ""
        if key in seen:
            issues.append(RowIssue(n, f"سجل مكرر في الملف: {key}"))
        seen.add(key)
        for numf in ("capacity", "size"):
            if mapping.get(numf) is not None and mapping[numf] < len(r) and r[mapping[numf]] not in (None, ""):
                try:
                    int(float(r[mapping[numf]]))
                except (TypeError, ValueError):
                    issues.append(RowIssue(n, "قيمة رقمية غير صالحة."))
    return issues


def import_rows(db: Database, entity: str, mapping: dict[str, int | None], rows: list[list],
                formation_id: int | None = None) -> ExcelResult:
    res = ExcelResult()
    res.issues = validate(entity, mapping, rows)
    if any(i.row == 0 for i in res.issues):
        return res
    bad_rows = {i.row for i in res.issues if "فارغة" in i.message or "رقمية" in i.message}

    def get(r, k):
        i = mapping.get(k)
        if i is None or i >= len(r) or r[i] is None:
            return None
        v = r[i]
        return v.strip() if isinstance(v, str) else v

    with db.tx():
        for n, r in enumerate(rows, start=2):
            if n in bad_rows:
                res.skipped += 1
                continue
            if entity == "teachers":
                name = str(get(r, "full_name"))
                if db.one("SELECT id FROM teachers WHERE full_name=?", (name,)):
                    res.skipped += 1
                    continue
                cat = get(r, "category")
                cid = None
                if cat:
                    cid = db.scalar("SELECT id FROM teacher_categories WHERE name=?", (cat,)) or \
                        db.insert("teacher_categories", name=str(cat))
                db.insert("teachers", full_name=name, rank=get(r, "rank"), category_id=cid, specialty=get(r, "specialty"))
            elif entity == "subjects":
                name = str(get(r, "name"))
                if db.one("SELECT id FROM subjects WHERE name=?", (name,)):
                    res.skipped += 1
                    continue
                shorts = {x[0] for x in db.q("SELECT short FROM subjects")}
                short = unique_abbrev(str(get(r, "short") or make_abbrev(name)), shorts)
                db.insert("subjects", name=name, short=short, shareable=int(str(get(r, "shareable") or "").lower() in TRUE))
            elif entity == "rooms":
                name = str(get(r, "name"))
                if db.one("SELECT id FROM rooms WHERE name=?", (name,)):
                    res.skipped += 1
                    continue
                db.insert("rooms", name=name, short=get(r, "short"), capacity=int(float(get(r, "capacity") or 0)),
                          kind=get(r, "kind"))
            elif entity == "sections":
                if not formation_id:
                    raise ValueError("اختر التكوين قبل استيراد الأقسام.")
                name = str(get(r, "name"))
                if db.one("SELECT id FROM sections WHERE formation_id=? AND name=?", (formation_id, name)):
                    res.skipped += 1
                    continue
                shorts = {x[0] for x in db.q("SELECT short FROM sections WHERE formation_id=?", (formation_id,))}
                short = unique_abbrev(str(get(r, "short") or make_abbrev(name)), shorts)
                sid = db.insert("sections", formation_id=formation_id, name=name, short=short,
                                size=int(float(get(r, "size") or 0)))
                db.insert("groups_", section_id=sid, name="الفوج الكامل", is_whole=1, size=int(float(get(r, "size") or 0)))
            res.added += 1
        db.log("استيراد Excel", entity, None, {"added": res.added, "skipped": res.skipped})
    return res
