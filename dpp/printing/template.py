"""قوالب الطباعة: بنية JSON بإصدار، القالب الافتراضي، التوريث (افتراضي ← طور ← فرع)، والحقول التلقائية.

القالب يحمل التخطيط والمظهر فقط، ولا يخزن ولا يغير بيانات الجدول.
الإحداثيات بالمليمتر من الزاوية العليا اليسرى للورقة.
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpp.models import PrintTemplate, Section, Week
from dpp.services import settings as cfg
from dpp.services import structure

VERSION = 1
PAGE_SIZES = {"A4": (210, 297), "A3": (297, 420), "Letter": (216, 279), "A5": (148, 210)}

FIELDS = {
    "institution": "اسم المؤسسة",
    "training": "التكوين",
    "certificate": "الشهادة",
    "level": "الطور",
    "specialty": "الاختصاص",
    "section": "الفرع",
    "headcount": "التعداد",
    "week": "رقم الأسبوع",
    "week_start": "بداية الأسبوع",
    "week_end": "نهاية الأسبوع",
    "phase": "المرحلة",
    "print_date": "تاريخ الطباعة",
    "page": "رقم الصفحة",
    "pages": "عدد الصفحات",
}
FIELD_RE = re.compile(r"\{(\w+)\}")


def new_id() -> str:
    return uuid.uuid4().hex[:8]


def text_item(text, x, y, w, h, size=11, bold=False, align="center", **kw) -> dict:
    d = {"type": "text", "id": new_id(), "x": x, "y": y, "w": w, "h": h, "text": text, "font": "Tahoma",
         "size": size, "bold": bold, "italic": False, "color": "#000000", "align": align, "valign": "middle",
         "border": 0.0, "border_color": "#000000", "bg": "", "rotation": 0, "padding": 1.0}
    d.update(kw)
    return d


def table_item(x, y, w, h) -> dict:
    return {"type": "table", "id": "table", "x": x, "y": y, "w": w, "h": h,
            "header_h": 9.0, "day_col_w": 22.0, "col_weights": {}, "row_weights": {},
            "hidden_cols": [], "hidden_days": [], "extra_cols": [],
            "border": 0.3, "border_color": "#333333", "header_bg": "#E8EEF4", "day_bg": "#F3F4F6",
            "font": "Tahoma", "header_size": 9, "day_size": 10, "cell_size": 8.5,
            "show_teacher": True, "show_time": False, "use_colors": True, "lunch_label": "استراحة الغداء",
            "merges": []}


def default_layout(kind: str = "section_week") -> dict:
    w, h = 297, 210  # A4 أفقي
    items = [
        text_item("{institution}", 197, 8, 90, 8, 11, True, "right"),
        text_item("{training}", 10, 8, 90, 8, 10, False, "left"),
        text_item("الجدول الزمني الأسبوعي — {section}", 60, 15, 177, 10, 17, True, "center"),
        text_item("{level} — {specialty} — الأسبوع {week}: من {week_start} إلى {week_end}", 40, 25, 217, 7, 11,
                  False, "center"),
        table_item(10, 35, 277, 150),
        text_item("المدير", 10, 188, 60, 14, 11, True, "center", border=0.3),
        text_item("طُبع في {print_date} — صفحة {page}/{pages}", 197, 192, 90, 6, 8, False, "right",
                  color="#555555"),
    ]
    return {"version": VERSION, "kind": kind, "name": "القالب الافتراضي",
            "page": {"size": "A4", "orientation": "landscape", "margins": [10, 10, 10, 10]},
            "grid": {"size": 5.0, "snap": True, "show": True}, "items": items}


def page_mm(layout: dict) -> tuple[float, float]:
    pw, ph = PAGE_SIZES.get(layout["page"].get("size", "A4"), PAGE_SIZES["A4"])
    if layout["page"].get("orientation") == "landscape":
        pw, ph = ph, pw
    return float(pw), float(ph)


def upgrade(layout: dict) -> dict:
    """ترقية القوالب القديمة إلى الإصدار الحالي (حقول ناقصة تأخذ القيم الافتراضية)."""
    base = default_layout(layout.get("kind", "section_week"))
    out = copy.deepcopy(layout)
    out.setdefault("version", VERSION)
    out.setdefault("page", base["page"])
    out.setdefault("grid", base["grid"])
    out.setdefault("items", base["items"])
    for it in out["items"]:
        ref = text_item("", 0, 0, 0, 0) if it.get("type") == "text" else table_item(0, 0, 0, 0)
        for k, v in ref.items():
            it.setdefault(k, v)
    out["version"] = VERSION
    return out


def find_item(layout: dict, item_id: str) -> dict | None:
    return next((i for i in layout["items"] if i["id"] == item_id), None)


# ------------------------------------------------------------------ التخزين والتوريث
def _row(s: Session, level_id=None, section_id=None, kind="section_week") -> PrintTemplate | None:
    q = select(PrintTemplate).where(PrintTemplate.name == kind)
    q = q.where(PrintTemplate.level_id == level_id) if level_id else q.where(PrintTemplate.level_id.is_(None))
    q = q.where(PrintTemplate.section_id == section_id) if section_id else q.where(PrintTemplate.section_id.is_(None))
    return s.scalar(q)


def load(s: Session, level_id=None, section_id=None, kind="section_week") -> dict | None:
    row = _row(s, level_id, section_id, kind)
    return upgrade(json.loads(row.layout_json)) if row else None


def save(s: Session, layout: dict, level_id=None, section_id=None, kind="section_week") -> None:
    row = _row(s, level_id, section_id, kind)
    if row is None:
        row = PrintTemplate(name=kind, level_id=level_id, section_id=section_id)
        s.add(row)
    row.layout_json = json.dumps(layout, ensure_ascii=False)
    s.commit()


def remove(s: Session, level_id=None, section_id=None, kind="section_week") -> None:
    row = _row(s, level_id, section_id, kind)
    if row:
        s.delete(row)
        s.commit()


def effective(s: Session, section: Section | None, kind="section_week") -> tuple[dict, str]:
    """القالب الفعلي للفرع ومصدره: section / level / default / builtin."""
    if section is not None:
        lay = load(s, section.level.id, section.id, kind)
        if lay:
            return lay, "section"
        lay = load(s, section.level.id, None, kind)
        if lay:
            return lay, "level"
    lay = load(s, None, None, kind)
    if lay:
        return lay, "default"
    return default_layout(kind), "builtin"


SOURCE_LABELS = {"section": "خاص بالفرع", "level": "موروث من قالب الطور", "default": "موروث من القالب الافتراضي",
                 "builtin": "القالب المدمج في البرنامج"}


# ------------------------------------------------------------------ الحقول
def field_values(s: Session, section: Section | None, week: Week | None, page: int = 1, pages: int = 1) -> dict:
    v = {k: "" for k in FIELDS}
    v["institution"] = cfg.get(s, "institution_name", "")
    v["print_date"] = dt.date.today().strftime("%d/%m/%Y")
    v["page"], v["pages"] = str(page), str(pages)
    if section is not None:
        t = section.training
        v.update(training=t.name, certificate=t.certificate_name, level=section.level.name,
                 specialty=section.specialty.name, section=section.name,
                 headcount=str(section.headcount) if section.headcount else "")
        if week is not None:
            v["week"] = str(week.number)
            v["week_start"] = week.start_date.strftime("%d/%m/%Y")
            v["week_end"] = (week.start_date + dt.timedelta(days=6)).strftime("%d/%m/%Y")
            ph = structure.phase_for_week(t, week.number, section.level.id, section.specialty_id)
            v["phase"] = ph.name if ph else ""
    return v


def fill(text: str, values: dict) -> tuple[str, list[str]]:
    """يستبدل الحقول ويعيد قائمة الحقول الفارغة (لا تُطبع فارغة بصمت: تظهر كتنبيه)."""
    missing: list[str] = []

    def rep(m):
        key = m.group(1)
        if key not in values:
            return m.group(0)
        val = values.get(key, "")
        if not val:
            missing.append(key)
            return f"[{FIELDS.get(key, key)}؟]"
        return val
    return FIELD_RE.sub(rep, text), missing


def missing_fields(layout: dict, values: dict) -> list[str]:
    out: list[str] = []
    for it in layout["items"]:
        if it["type"] == "text":
            out.extend(fill(it["text"], values)[1])
    return sorted(set(out))
