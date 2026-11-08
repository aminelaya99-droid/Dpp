"""قوالب الطباعة والتقارير (تُحفظ JSON في قاعدة البيانات)."""
from __future__ import annotations

import copy
import json

from ..db.database import Database

KINDS = {
    "week_section": "جدول أسبوعي للقسم", "week_teacher": "جدول الأستاذ", "week_all": "جدول جميع الأقسام",
    "period_plan": "مخطط فترة التكوين", "progress": "تقرير إنجاز المواد", "teacher_hours": "كشف ساعات الأستاذ",
    "absences": "تقرير الغيابات", "exams": "رزنامة الامتحانات", "generic": "تقرير عام",
}

DEFAULT = {
    "paper": "A4",                  # A4 | A3
    "orientation": "landscape",     # landscape | portrait
    "margins_mm": [12, 12, 12, 12],  # أعلى، يمين، أسفل، يسار
    "font_size": 10,
    "title_size": 15,
    "header_bg": "#DCE6F1",
    "border_color": "#555555",
    "use_subject_colors": True,
    "show": {"institution": True, "logo": True, "formation": True, "section": True, "week": True,
             "subject": True, "teacher": True, "room": True, "time": True, "notes": False,
             "print_date": True, "page_number": True},
    "header_lines": [],
    "footer_text": "",
    "signatures": ["رئيس دائرة التعليم", "المدير"],
    "col_width": 0,                 # 0 = تلقائي
    "row_height": 0,
}


def default_template(kind: str) -> dict:
    t = copy.deepcopy(DEFAULT)
    if kind in ("progress", "teacher_hours", "absences", "exams", "generic"):
        t["orientation"] = "portrait"
        t["use_subject_colors"] = False
    if kind == "week_all":
        t["paper"] = "A3"
    return t


def merged(data: dict, kind: str = "generic") -> dict:
    base = default_template(kind)
    for k, v in (data or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = base[k] | v
        else:
            base[k] = v
    return base


def ensure_defaults(db: Database):
    for kind, label in KINDS.items():
        if not db.one("SELECT id FROM templates WHERE kind=?", (kind,)):
            db.insert("templates", name=label, kind=kind, data=json.dumps(default_template(kind), ensure_ascii=False))


def list_templates(db: Database, kind: str | None = None) -> list[dict]:
    rows = db.q("SELECT * FROM templates WHERE (? IS NULL OR kind=?) ORDER BY name", (kind, kind))
    return [dict(r) | {"data": merged(json.loads(r["data"]), r["kind"])} for r in rows]


def get_template(db: Database, template_id: int | None, kind: str) -> dict:
    if template_id:
        r = db.one("SELECT * FROM templates WHERE id=?", (template_id,))
        if r:
            return merged(json.loads(r["data"]), r["kind"])
    r = db.one("SELECT * FROM templates WHERE kind=? ORDER BY id LIMIT 1", (kind,))
    return merged(json.loads(r["data"]), kind) if r else default_template(kind)


def save_template(db: Database, name: str, kind: str, data: dict, template_id: int | None = None) -> int:
    payload = json.dumps(merged(data, kind), ensure_ascii=False)
    if template_id:
        db.update("templates", template_id, name=name, kind=kind, data=payload)
        return template_id
    return db.insert("templates", name=name, kind=kind, data=payload)


def migrate_to_layout(db: Database) -> bool:
    """مرة واحدة: نقل ما عدّله المستخدم في المصمم القديم إلى محرر الطباعة الواحد.
    الهوامش والورق والاتجاه والألوان ← قالب «كل التقارير»؛ أسطر الرأس والتذييل والتوقيعات ← نصوص التقارير.
    القوالب القديمة تبقى في قاعدة البيانات (لا يُحذف شيء)."""
    if db.get_setting("templates_migrated_v1", "") == "1":
        return False
    from ..exporters import layout as L
    from ..exporters import official as O
    changed = False
    try:
        rows = db.q("SELECT kind, data FROM templates ORDER BY id")
    except Exception:
        rows = []
    best = None
    for r in rows:
        try:
            d = merged(json.loads(r["data"] or "{}"), r["kind"])
        except ValueError:
            continue
        if d != default_template(r["kind"]):
            best = (r["kind"], d)
            if r["kind"] in ("progress", "generic", "teacher_hours"):
                break
    if best:
        kind, d = best
        lay, _ = L.effective(db, "report")
        lay["page"]["paper"] = d.get("paper", "A4")
        lay["page"]["orientation"] = d.get("orientation", "portrait")
        lay["page"]["margins"] = [round(float(x) * 2.835, 1) for x in d.get("margins_mm", [12] * 4)]
        lay["table"]["head_fill"] = d.get("header_bg") or ""
        lay["table"]["border_color"] = d.get("border_color") or "#000000"
        lay["table"]["title_pt"] = float(d.get("font_size") or 9)
        L.save(db, "kind:report", lay, "report")
        fields = {}
        if d.get("header_lines"):
            fields["center_block"] = "{title}\n" + "\n".join(d["header_lines"]) + "\n{info}"
        if d.get("footer_text"):
            fields["note"] = d["footer_text"]
        sig = d.get("signatures") or []
        if sig:
            fields["sign_right"] = sig[0]
            if len(sig) > 2:
                fields["sign_center"] = sig[1]
            fields["sign_left"] = sig[-1] if len(sig) > 1 else ""
        if fields:
            O.save_template_fields(db, "report", fields)
        changed = True
    db.set_setting("templates_migrated_v1", "1")
    return changed
