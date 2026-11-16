"""تخطيط ورقة الطباعة (القالب البصري): الورقة، الهوامش، مربعات النص الحرة، وشكل الجدول.

* القالب يحفظ الشكل فقط، ولا يحفظ بيانات الجدول أبداً.
* الوراثة: قالب نوع الورقة (لكل الأطوار) ← قالب الطور ← قالب القسم. القسم بلا قالب خاص يأخذ قالب طوره.
* التخزين: إعداد JSON واحد (official_layout) فيه {النطاق: تخطيط جزئي}، مع رقم إصدار.
* لا يعتمد على Qt (يُستعمل في الاختبارات والتصدير).
"""
from __future__ import annotations

import copy
import json
import re

from ..db.database import Database

VERSION = 1
_KEY = "official_layout"

# مقاسات الورق بالنقطة (عرض × ارتفاع في الوضع العمودي)
PAPERS = {"A4": (595.28, 841.89), "A3": (841.89, 1190.55), "A5": (419.53, 595.28), "Letter": (612.0, 792.0),
          "Legal": (612.0, 1008.0)}
PAPER_LABELS = {"A4": "A4", "A3": "A3", "A5": "A5", "Letter": "Letter (رسالة)", "Legal": "Legal"}

# الحقول التي تُملأ تلقائياً داخل النصوص الحرة
PLACEHOLDERS = {
    "institution": "اسم المؤسسة", "target": "اسم القسم / الأستاذ / القاعة", "section": "القسم",
    "level": "الطور", "specialty": "الاختصاص", "week": "رقم الأسبوع", "week_words": "الأسبوع بالحروف",
    "d0": "بداية الأسبوع", "d1": "نهاية الأسبوع", "year": "السنة الدراسية", "formation": "التكوين",
    "today": "تاريخ الطباعة", "page": "رقم الصفحة", "pages": "عدد الصفحات", "decree": "رقم المقرر",
    "hours": "الحجم الساعي (للأستاذ)",
}

DEFAULT_LAYOUT = {
    "version": VERSION,
    "page": {"paper": "A4", "orientation": "landscape", "margins": [20.0, 20.0, 20.0, 20.0]},   # أعلى، يمين، أسفل، يسار
    "boxes": [],            # مربعات النص الحرة (انظر new_box)
    "removed_boxes": [],    # مربعات موروثة حُذفت في هذا النطاق
    "hidden_fields": [],    # نصوص القالب الأصلية المخفية (مثل «republic»)
    "field_styles": {},     # تنسيق نصوص القالب نفسها: {مفتاح النص أو صنفه: {font, size, bold, …, dx, dy, w, h}}
    "cell_styles": {},      # تنسيق خانة بعينها لهذا الأسبوع فقط (لا يُحفظ في القالب؛ انظر save_cell_styles)
    "table": {
        "border_w": 0.6, "outer_w": 1.2, "border_color": "#000000",
        "head_fill": "", "day_fill": "", "cell_fill": "",
        "head_pt": None, "day_pt": 12.5, "title_pt": None, "sub_pt": None,
        "day_w": 64.0, "head_h": 30.0,
        "col_weights": {},      # {فهرس الحصة: وزن العرض} (1 = عادي)
        "row_weights": {},      # {فهرس اليوم: وزن الارتفاع}
        "hidden_cols": [],      # فهارس الحصص المخفية
        "hidden_days": [],      # 0 = الأحد … 6 = السبت
        "notes_col": False, "notes_title": "ملاحظات", "notes_w": 1.0,
        "merges": [],           # [{"day", "c0", "c1", "text"}] خلايا مدمجة بنص للطباعة فقط
        "cell_texts": {},       # {"day:col": نص} نص للطباعة فقط داخل خانة فارغة
        "top": 172.0, "bottom_gap": 80.0,
    },
}

ALIGNS = ("right", "center", "left", "justify")
VALIGNS = ("top", "middle", "bottom")


def new_box(x: float, y: float, text: str = "نص جديد", w: float = 200.0, h: float = 24.0) -> dict:
    import uuid
    return {"id": uuid.uuid4().hex[:10], "text": text, "x": x, "y": y, "w": w, "h": h, "align": "center",
            "valign": "middle", "font": "", "size": 11.0, "bold": False, "italic": False, "underline": False,
            "color": "#000000", "frame_w": 0.0, "frame_color": "#000000", "padding": 3.0, "rotation": 0.0,
            "fill": "", "kashida": False, "justify_last": False}


# ------------------------------------------------------------------ تنسيق نصوص القالب (1.9)
# نصوص الورقة المبنية (الترويسة، العنوان، التوقيعات…) كانت مكتوبة الشكل والموضع في الكود.
# الآن لكل نص مفرد تنسيقه وموضعه، ونصوص الجدول تُنسَّق كصنف (اسم المادة في كل الخانات)،
# مع إمكانية تنسيق خانة بعينها لأسبوع واحد.
FIELD_LABELS = {
    "republic": "عنوان الجمهورية", "right_block": "الترويسة اليمنى", "left_block": "الترويسة اليسرى",
    "approval": "خانة المصادقة", "center_block": "العنوان الأوسط", "note": "الملاحظة",
    "created": "تاريخ الإنشاء", "sign_right": "التوقيع الأيمن", "sign_center": "التوقيع الأوسط",
    "sign_left": "التوقيع الأيسر", "notes_title": "عنوان عمود الملاحظات", "rpt_title": "عنوان التقرير",
    "pageno": "رقم الصفحة",
}
CLASS_LABELS = {
    "cls:title": "اسم المادة", "cls:sub": "الأستاذ", "cls:corner": "القاعة في الخانة",
    "cls:cnote": "ملاحظة الخانة", "cls:day": "أسماء الأيام", "cls:ph_time": "توقيت الحصص",
    "cls:ph_label": "أسماء الحصص", "cls:merge": "نص الخلايا المدمجة", "cls:ctext": "نص الخانات الفارغة",
}
STYLE_PROPS = ("font", "size", "bold", "italic", "underline", "color", "align", "valign", "line_h")
GEO_PROPS = ("dx", "dy", "w", "h")          # الإزاحة وحيّز النص: للنصوص المفردة فقط
_CELL_SUFFIX = {"title": "cls:title", "sub": "cls:sub", "corner": "cls:corner", "note": "cls:cnote"}


def field_class(key: str) -> str | None:
    """صنف نص الجدول الذي ينتمي إليه المفتاح، أو None للنص المفرد."""
    if key.startswith("ph:"):
        return "cls:ph_label" if key.endswith(":label") else "cls:ph_time"
    if key.startswith("day:"):
        return "cls:day"
    if key.startswith("cell:"):
        return _CELL_SUFFIX.get(key.rsplit(":", 1)[-1])
    if key.startswith("merge:"):
        return "cls:merge"
    if key.startswith("ctext:"):
        return "cls:ctext"
    return None


def is_stylable(key: str) -> bool:
    return key in FIELD_LABELS or field_class(key) is not None


def field_label(key: str) -> str:
    cls = field_class(key)
    return CLASS_LABELS.get(cls, "") if cls else FIELD_LABELS.get(key, key)


def field_style(layout: dict, key: str) -> dict:
    """التنسيق الفعلي لنص: صنفه، ثم النص نفسه (القالب)، ثم الخانة بعينها (هذا الأسبوع)."""
    fs = layout.get("field_styles") or {}
    out: dict = {}
    cls = field_class(key)
    if cls:
        out.update(fs.get(cls) or {})
        out.update((layout.get("cell_styles") or {}).get(key) or {})
    else:
        out.update(fs.get(key) or {})
    return {a: b for a, b in out.items() if b is not None}


def style_target(key: str, cell_only: bool = False) -> tuple[str, str]:
    """(اسم المخزن، المفتاح) الذي يُكتب فيه تنسيق هذا النص."""
    cls = field_class(key)
    if cls and cell_only:
        return "cell_styles", key
    return "field_styles", (cls or key)


def set_field_style(layout: dict, key: str, cell_only: bool = False, **kv) -> None:
    """يضبط خصائص تنسيق نص. القيمة None تحذف الخاصية فترجع موروثة."""
    store, k = style_target(key, cell_only)
    if field_class(key):                      # نصوص الجدول: شكل فقط، بلا إزاحة ولا حيّز
        kv = {a: b for a, b in kv.items() if a in STYLE_PROPS}
    d = layout.setdefault(store, {}).setdefault(k, {})
    for a, b in kv.items():
        if b is None:
            d.pop(a, None)
        else:
            d[a] = b
    if not d:
        layout[store].pop(k, None)


def clear_field_style(layout: dict, key: str, cell_only: bool = False) -> None:
    """إرجاع النص إلى الأصل (أو إلى الموروث من النطاق الأعم)."""
    store, k = style_target(key, cell_only)
    (layout.get(store) or {}).pop(k, None)


_CELL_KEY = "official_cell_styles"


def _sheet_key(kind: str, target_id, ws) -> str:
    return f"{kind}:{target_id}|{ws.isoformat() if hasattr(ws, 'isoformat') else ws}"


def cell_styles(db: Database, kind: str, target_id, ws) -> dict:
    """تنسيق الخانات المحفوظ لورقة أسبوع بعينه."""
    try:
        st = json.loads(db.get_setting(_CELL_KEY, "") or "{}")
    except ValueError:
        st = {}
    v = st.get(_sheet_key(kind, target_id, ws)) if isinstance(st, dict) else None
    return copy.deepcopy(v) if isinstance(v, dict) else {}


def save_cell_styles(db: Database, kind: str, target_id, ws, styles: dict) -> None:
    try:
        st = json.loads(db.get_setting(_CELL_KEY, "") or "{}")
    except ValueError:
        st = {}
    if not isinstance(st, dict):
        st = {}
    k = _sheet_key(kind, target_id, ws)
    styles = {a: b for a, b in (styles or {}).items() if b}
    if styles == (st.get(k) or {}):
        return
    if styles:
        st[k] = styles
    else:
        st.pop(k, None)
    db.set_setting(_CELL_KEY, json.dumps(st, ensure_ascii=False))


def _store(db: Database) -> dict:
    try:
        st = json.loads(db.get_setting(_KEY, "") or "{}")
        return st if isinstance(st, dict) else {}
    except ValueError:
        return {}


REPORT_NAMES = {
    "report": "كل التقارير", "progress_simple": "المقرر والمنجز", "progress_compare": "مقارنة أقسام الطور",
    "progress_sections": "تقدم كل قسم", "progress_full": "التقرير الشامل لتقدم الدروس",
    "progress": "تقرير إنجاز المواد", "teacher_hours": "كشف ساعات الأساتذة", "absences": "الغيابات والاستخلاف",
    "status": "الحصص المؤجلة والملغاة", "exams": "الامتحانات والمواعيد", "summary": "ملخص التكوين",
    "period_plan": "مخطط فترة التكوين", "week_all": "جدول جميع الأقسام", "duty": "جدول المناوبات",
}


def is_report(kind: str) -> bool:
    return kind.startswith("report")


def scope_chain(kind: str, level_id: int | None = None, section_id: int | None = None) -> list[str]:
    """النطاقات من العام إلى الخاص: نوع الورقة ← الطور ← القسم (والتقارير: كل التقارير ← هذا التقرير)."""
    if is_report(kind):
        return ["kind:report"] + ([f"kind:{kind}"] if kind != "report" else [])
    out = [f"kind:{kind}"]
    if kind == "section" and level_id:
        out.append(f"level:{level_id}")
    if kind == "section" and section_id:
        out.append(f"section:{section_id}")
    return out


def scope_label(db: Database, scope: str) -> str:
    k, _, v = scope.partition(":")
    if k == "kind":
        if is_report(v):
            key = v[len("report_"):] if v.startswith("report_") else "report"
            return REPORT_NAMES["report"] if key == "report" else "تقرير: " + REPORT_NAMES.get(key, key)
        return {"section": "كل الأطوار (أوراق الأقسام)", "teacher": "كل أوراق الأساتذة", "room": "كل أوراق القاعات"}.get(v, v)
    if k == "level":
        return "الطور " + (db.scalar("SELECT COALESCE(code, name) FROM levels WHERE id=?", (int(v),)) or v)
    if k == "section":
        return "القسم " + (db.scalar("SELECT COALESCE(short, name) FROM sections WHERE id=?", (int(v),)) or v)
    return scope


def _live_styles(fs: dict | None) -> dict:
    """تنسيقات النصوص بلا علامات الإلغاء (None = «أرجِع هذه الخاصية إلى الأصل» في نطاق أخص)."""
    out = {}
    for k, d in (fs or {}).items():
        d = {a: b for a, b in (d or {}).items() if b is not None}
        if d:
            out[k] = d
    return out


def _diff_styles(base: dict, full: dict) -> dict:
    """فرق تنسيقات النصوص؛ ما أُرجع إلى الأصل في النطاق الأخص يُحفظ None حتى لا يعود موروثاً."""
    out = {}
    for k in list(dict.fromkeys(list(base) + list(full))):
        b = {a: v for a, v in (base.get(k) or {}).items() if v is not None}
        f = full.get(k) or {}
        d = {a: copy.deepcopy(v) for a, v in f.items() if b.get(a) != v}
        d.update({a: None for a in b if a not in f})
        if d:
            out[k] = d
    return out


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if k == "boxes":
            by = {b["id"]: b for b in out.get("boxes", [])}
            for b in v:
                by[b["id"]] = copy.deepcopy(b)
            out["boxes"] = list(by.values())
        elif k in ("removed_boxes", "hidden_fields"):
            out[k] = list(dict.fromkeys(list(out.get(k, [])) + list(v)))
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def effective(db: Database, kind: str, level_id: int | None = None, section_id: int | None = None) -> tuple[dict, list]:
    """(التخطيط الفعلي، النطاقات التي ساهمت فيه من العام إلى الخاص)."""
    st = _store(db)
    lay = base_layout(kind)
    used = []
    for sc in scope_chain(kind, level_id, section_id):
        if sc in st:
            lay = _merge(lay, st[sc])
            used.append(sc)
    removed = set(lay.get("removed_boxes", []))
    lay["boxes"] = [b for b in lay.get("boxes", []) if b["id"] not in removed]
    lay["field_styles"] = _live_styles(lay.get("field_styles"))
    return lay, used


def scope_layout(db: Database, scope: str) -> dict | None:
    return copy.deepcopy(_store(db).get(scope))


def diff(base: dict, full: dict) -> dict:
    """ما يختلف في full عن base (لحفظ التعديلات فقط في النطاق الخاص، وترك الباقي موروثاً)."""
    out = {}
    for k, v in full.items():
        if k == "boxes":
            bb = {b["id"]: b for b in base.get("boxes", [])}
            ch = [b for b in v if bb.get(b["id"]) != b]
            if ch:
                out["boxes"] = ch
            gone = [i for i in bb if i not in {b["id"] for b in v}]
            if gone:
                out["removed_boxes"] = gone
        elif k in ("removed_boxes", "cell_styles"):
            continue
        elif k == "field_styles":
            d = _diff_styles(base.get(k) or {}, v or {})
            if d:
                out[k] = d
        elif isinstance(v, dict) and isinstance(base.get(k), dict):
            d = diff(base[k], v)
            if d:
                out[k] = d
        elif base.get(k) != v:
            out[k] = copy.deepcopy(v)
    return out


def save(db: Database, scope: str, full_layout: dict, kind: str, level_id=None, section_id=None) -> None:
    """يحفظ في النطاق ما يختلف عن قالب النطاقات الأعم منه فقط."""
    chain = scope_chain(kind, level_id, section_id)
    upto = chain[:chain.index(scope)] if scope in chain else chain[:-1]
    st = _store(db)
    base = base_layout(kind)
    for sc in upto:
        if sc in st:
            base = _merge(base, st[sc])
    d = diff(base, full_layout)
    d["version"] = VERSION
    st[scope] = d
    db.set_setting(_KEY, json.dumps(st, ensure_ascii=False))
    db.log("حفظ قالب الطباعة", "templates", None, {"scope": scope})


def reset(db: Database, scope: str) -> None:
    st = _store(db)
    if st.pop(scope, None) is not None:
        db.set_setting(_KEY, json.dumps(st, ensure_ascii=False))
        db.log("إرجاع قالب الطباعة إلى الموروث", "templates", None, {"scope": scope})


def copy_scope(db: Database, src: str, dst: str) -> None:
    st = _store(db)
    if src in st:
        st[dst] = copy.deepcopy(st[src])
        db.set_setting(_KEY, json.dumps(st, ensure_ascii=False))


def saved_scopes(db: Database) -> list[str]:
    return sorted(_store(db))


# ------------------------------------------------------------------ الحقول التلقائية
_PH = re.compile(r"\{(\w+)\}")


def fill_text(text: str, values: dict) -> tuple[str, list[str]]:
    """يملأ {الحقول}. يعيد (النص، الحقول المعروفة التي لا قيمة لها) — لا تُطبع فارغة دون تنبيه."""
    missing = []

    def sub(m):
        k = m.group(1)
        v = values.get(k)
        if v in (None, ""):
            if k in PLACEHOLDERS:
                missing.append(k)
                return f"[{PLACEHOLDERS[k]}؟]"
            return m.group(0)
        return str(v)
    return _PH.sub(sub, text or ""), missing


def paper_size(layout: dict) -> tuple[float, float]:
    """(العرض، الارتفاع) بالنقطة حسب الورق والاتجاه."""
    w, h = PAPERS.get(layout["page"].get("paper", "A4"), PAPERS["A4"])
    return (h, w) if layout["page"].get("orientation", "landscape") == "landscape" else (w, h)


def effective_default() -> dict:
    return copy.deepcopy(DEFAULT_LAYOUT)


def base_layout(kind: str) -> dict:
    """التصميم الافتراضي لنوع الورقة: التقارير عمودية، والجدول يبدأ بعد رأس أقصر."""
    lay = copy.deepcopy(DEFAULT_LAYOUT)
    if is_report(kind):
        lay["page"]["orientation"] = "portrait"
        lay["page"]["margins"] = [22.0, 22.0, 22.0, 22.0]
        lay["table"].update(top=150.0, bottom_gap=70.0, head_pt=8.5, title_pt=8.0, row_h=0.0, cell_align="center")
    return lay
