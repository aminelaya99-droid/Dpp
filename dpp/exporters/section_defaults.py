"""القوالب الافتراضية لأوراق الأقسام (الإصدار 1.9).

مستنتجة من 39 ورقة برنامج أسبوعي للمؤسسة مطبوعة من aSc: كل الأوراق الرسمية تشترك في تصميم واحد
(مواضع العناصر كنسبة من الورقة متطابقة، وA3 = A4 مكبّرة) وتختلف في النصوص فقط. لذلك:

* **القالب العام** = ذلك التصميم المشترك (`GENERAL`) — يُطبَّق على أي قسم ليس له قالب.
* **قالب الطور** = سطرا الطور، حجم الورق، المقرر الغالب، ظهور الملاحظة (من ملف الأصول).
* **قالب القسم** = القاعة والمقرر وما يخالف فيه القسم طوره.

لا يُكتب شيء في قاعدة البيانات: القوالب طبقة تحت قوالب المستخدم (`layout._with_builtin`)، وتُطبَّق تلقائياً
على الأقسام التي لم يعدّل المستخدم تصميمها. المطابقة بالاسم (اسم القسم = اسم الصف في aSc) ويمكن تصحيحها
يدوياً من شاشة المراجعة (`ui/section_tpl_ui.py`).
"""
from __future__ import annotations

import copy
import difflib
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from ..db.database import Database

ASSET = Path(__file__).resolve().parent.parent / "assets" / "print_templates" / "sections.json"
_SET_ON = "section_tpl_on"        # «0» يعطّل القوالب الافتراضية كلها
_SET_MAP = "section_tpl_map"      # {رقم القسم: {"key": مفتاح القالب | "" (بلا قالب قسم), "mode": auto|on|off}}

# ------------------------------------------------------------------ القالب العام (قياسات A4 أفقي بالنقطة)
# مأخوذة من قياس أوراق aSc: الجدول من 180.5 إلى 507.3، عمود الأيام 67، رأس الجدول 31،
# نصوص الترويسة 10.7، المصادقة 13.3، أسماء الأيام 14.7، اسم المادة 10.7، الأستاذ 8، التوقيت 10.
GENERAL = {
    "page": {"paper": "A4", "orientation": "landscape", "margins": [20.0, 30.0, 20.0, 26.0]},
    "font": "Times New Roman",
    "approval_box": [16.5, 68.5, 240.0, 105.0],
    "base_styles": {
        "republic": {"size": 10.7, "dx": 47.0, "dy": -12.5},
        "right_block": {"size": 10.7, "dx": 24.0, "dy": -20.0, "line_h": 1.12, "align": "right"},
        "left_block": {"size": 10.7, "dx": 14.0, "dy": -11.0, "line_h": 1.0, "align": "right"},
        "approval": {"size": 13.3, "dy": -4.0},
        "center_block": {"size": 10.7, "dx": 1.0, "dy": 16.0, "w": 436.0, "h": 112.0, "line_h": 1.56},
        "note": {"size": 9.9, "underline": False, "dx": 69.0, "dy": -5.0, "align": "right"},
        "created": {"size": 5.3, "dy": -5.5, "align": "right"},
        "sign_right": {"size": 10.7, "dx": 53.0, "dy": -10.0, "w": 160.0, "align": "center"},
        "sign_center": {"size": 10.7, "dx": -27.0, "dy": -6.5},
        "sign_left": {"size": 10.7, "dx": 10.0, "dy": -18.0, "w": 120.0, "align": "center"},
    },
    "table": {"top": 180.5, "bottom_gap": 88.0, "day_w": 67.0, "head_h": 31.0, "head_pad": 7.5, "head_pt": 10.0,
              "day_pt": 14.7, "title_pt": 10.7, "sub_pt": 8.0, "label_pt": 6.7, "fit_text": True},
}
# أوراق الاحتياط: عنوان كبير ثم الجدول يملأ الصفحة (بلا ترويسة ولا توقيعات)
SIMPLE = {
    "page": {"paper": "A4", "orientation": "landscape", "margins": [12.0, 14.0, 12.0, 14.0]},
    "font": "Times New Roman",
    "hidden_fields": ["republic", "right_block", "left_block", "approval", "center_block", "note",
                      "sign_right", "sign_center", "sign_left"],
    "boxes": [{"id": "tpl-title", "text": "{target}", "x": 60.0, "y": 8.0, "w": 722.0, "h": 46.0,
               "align": "center", "valign": "middle", "font": "", "size": 30.0, "bold": True, "italic": False,
               "underline": False, "color": "#000000", "frame_w": 0.0, "frame_color": "#000000", "padding": 3.0,
               "rotation": 0.0}],
    "table": {"top": 70.0, "bottom_gap": 32.0, "day_w": 86.0, "head_h": 36.0, "head_pt": 15.3, "day_pt": 22.7,
              "title_pt": 16.0, "sub_pt": 12.0, "label_pt": 10.7, "fit_text": True, "compact": True},
}
LEVEL_LABELS = {"ESOC2": "شهادة مهنية عسكرية د2 — سنة ثانية", "ESOC1": "شهادة مهنية عسكرية د2 — سنة أولى",
                "BMP2": "أهلية مهنية عسكرية د2", "BMP1": "أهلية مهنية عسكرية د1", "RESERVE": "الاحتياط (عنوان + جدول)"}


@lru_cache(maxsize=1)
def load() -> dict:
    """ملف القوالب (فارغ إذا غاب الملف: البرنامج يعمل بالقالب العام فقط)."""
    try:
        return json.loads(ASSET.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 0, "levels": {}, "sections": []}


def entries() -> list[dict]:
    return load().get("sections", [])


def entry(key: str) -> dict | None:
    return next((e for e in entries() if e["key"] == key), None)


_DROP = re.compile(r"[\sـً-ْ:\-–—()+.،,/_]+")


def norm(s: str) -> str:
    """تطبيع الاسم للمطابقة: بلا فراغات ولا تشكيل ولا ترقيم، وتوحيد الألف والتاء المربوطة والياء."""
    s = (s or "").lower()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه"), ("ؤ", "و"), ("ئ", "ي")):
        s = s.replace(a, b)
    return _DROP.sub("", s)


def level_key(code: str | None) -> str | None:
    """رمز الطور في البرنامج ← مفتاح قالب الطور."""
    lv = load().get("levels", {})
    if code in lv:
        return code
    if code and code in (lv.get("RESERVE") or {}).get("codes", []):
        return "RESERVE"
    return None


# ------------------------------------------------------------------ الإعدادات
def enabled(db: Database) -> bool:
    return (db.get_setting(_SET_ON, "1") or "1") != "0"


def set_enabled(db: Database, on: bool) -> None:
    db.set_setting(_SET_ON, "1" if on else "0")
    db.log("القوالب الافتراضية للأقسام", "templates", None, {"enabled": bool(on)})


def _choices(db: Database) -> dict:
    try:
        d = json.loads(db.get_setting(_SET_MAP, "") or "{}")
        return d if isinstance(d, dict) else {}
    except ValueError:
        return {}


def set_choice(db: Database, section_id: int, key: str | None = None, mode: str | None = None) -> None:
    """اختيار يدوي: key = مفتاح قالب، "" = بلا قالب قسم، None = مطابقة آلية. mode: auto | on | off."""
    d = _choices(db)
    cur = dict(d.get(str(section_id)) or {})
    if key is None:
        cur.pop("key", None)
    else:
        cur["key"] = key
    if mode in (None, "auto"):
        cur.pop("mode", None)
    else:
        cur["mode"] = mode
    if cur:
        d[str(section_id)] = cur
    else:
        d.pop(str(section_id), None)
    db.set_setting(_SET_MAP, json.dumps(d, ensure_ascii=False))
    db.log("قالب القسم الافتراضي", "templates", section_id, cur)


# ------------------------------------------------------------------ المطابقة
@dataclass
class Match:
    section_id: int
    entry: dict | None            # قالب القسم (None = لا قالب خاص)
    how: str                      # manual | exact | approx | none
    level: str | None             # مفتاح قالب الطور (None = القالب العام)
    mode: str = "auto"            # auto | on | off
    score: float = 0.0
    flags: list = field(default_factory=list)

    @property
    def source(self) -> str:
        """أي قالب يُستعمل فعلاً: section | level | general."""
        return "section" if self.entry else ("level" if self.level else "general")


def _section_row(db: Database, section_id: int):
    return db.one("""SELECT s.id, s.name, s.short, s.level_id, l.code lcode FROM sections s
                     LEFT JOIN levels l ON l.id=s.level_id WHERE s.id=?""", (section_id,))


def match(db: Database, section_id: int, row=None) -> Match:
    row = row or _section_row(db, section_id)
    if not row:
        return Match(section_id, None, "none", None)
    ch = _choices(db).get(str(section_id)) or {}
    mode = ch.get("mode") or "auto"
    lk = level_key(row["lcode"])
    if "key" in ch:                                   # اختيار المستخدم
        e = entry(ch["key"]) if ch["key"] else None
        return Match(section_id, e, "manual", level_key(e["level"]) if e else lk, mode, 1.0,
                     list((e or {}).get("flags", [])))
    names = [n for n in (norm(row["name"]), norm(row["short"] or "")) if n]
    best, score = None, 0.0
    for e in entries():
        keys = [norm(e["name"]), norm(e["key"])]
        if any(n == k for n in names for k in keys):
            return Match(section_id, e, "exact", level_key(e["level"]) or lk, mode, 1.0, list(e.get("flags", [])))
        if lk and level_key(e["level"]) != lk:
            continue                                  # التقريب داخل نفس الطور فقط
        s = max(difflib.SequenceMatcher(None, n, k).ratio() for n in names for k in keys) if names else 0.0
        if s > score:
            best, score = e, s
    if best is not None and score >= 0.9:
        return Match(section_id, best, "approx", level_key(best["level"]) or lk, mode, score,
                     list(best.get("flags", [])))
    return Match(section_id, None, "none", lk, mode, score)


def _props(m: Match) -> dict:
    """خصائص القالب الفعلية للقسم: الطور ثم ما يخالفه فيه القسم."""
    out = dict(load().get("levels", {}).get(m.level or "", {}))
    out.update({k: v for k, v in (m.entry or {}).items() if k not in ("key", "name", "level", "flags")})
    return out


# ------------------------------------------------------------------ ما تأخذه الورقة
def values(db: Database, section_id: int, current: dict) -> dict:
    """نصوص قالب القسم: سطرا الطور والقاعة، والمقرر إذا لم يُحدَّد للاختصاص في البرنامج."""
    if not enabled(db):
        return {}
    m = match(db, section_id)
    if m.mode == "off" or m.source == "general":
        return {}
    p = _props(m)
    out = {}
    for k in ("level_line", "spec_line", "room"):
        if p.get(k):
            out[k] = p[k]
    if not current.get("decree") and p.get("decree"):
        out["decree"], out["decree_date"] = p["decree"], p.get("decree_date", "")
    return out


def layout_layers(db: Database, level_id, section_id, customised: bool) -> list[tuple[str, dict]]:
    """طبقات التصميم الافتراضية [(الاسم، التخطيط)] من العام إلى الخاص؛ فارغة إذا عدّل المستخدم تصميم القسم."""
    if not enabled(db):
        return []
    m = match(db, section_id) if section_id else Match(0, None, "none", None)
    if not section_id and level_id:
        m.level = level_key(db.scalar("SELECT code FROM levels WHERE id=?", (level_id,)))
    if m.mode == "off" or (customised and m.mode != "on"):
        return []
    p = _props(m)
    if p.get("simple"):
        return [("builtin:simple", copy.deepcopy(SIMPLE))]
    out = [("builtin:general", copy.deepcopy(GENERAL))]
    lay: dict = {}
    if p.get("paper") and p["paper"] != "A4":
        lay["page"] = {"paper": p["paper"], "scale_from": "A4"}       # A3 = نفس التصميم مكبّراً
    if p.get("note") is False:
        lay["hidden_fields"] = ["note"]
    if lay:
        out.append((f"builtin:{m.source}", lay))
    return out


# ------------------------------------------------------------------ شاشة المراجعة
def overview(db: Database, formation_id: int | None = None) -> list[dict]:
    """سطر لكل قسم: أي قالب يأخذه، كيف طوبق، وهل تصميمه معدّل من المستخدم."""
    from . import layout as L
    sql = """SELECT s.id, s.name, s.short, s.level_id, l.code lcode FROM sections s
             LEFT JOIN levels l ON l.id=s.level_id"""
    rows = db.q(sql + (" WHERE s.formation_id=?" if formation_id else "") + " ORDER BY l.code, s.short, s.name",
                (formation_id,) if formation_id else ())
    store = L._store(db)
    out = []
    for r in rows:
        m = match(db, r["id"], r)
        saved = [sc for sc in L.scope_chain("section", r["level_id"], r["id"]) if sc in store]
        custom = [sc for sc in saved if not store[sc].get("on_builtin")]      # تصميم محفوظ قبل القوالب الافتراضية
        applied = enabled(db) and m.mode != "off" and (not custom or m.mode == "on")
        out.append({"id": r["id"], "name": r["name"], "short": r["short"] or "", "level_code": r["lcode"] or "",
                    "match": m, "props": _props(m), "custom": custom, "saved": saved, "applied": applied})
    return out


def summary(rows: list[dict]) -> dict:
    c = {"section": 0, "level": 0, "general": 0, "approx": 0, "custom": 0, "flags": 0}
    for r in rows:
        c[r["match"].source] += 1
        c["approx"] += r["match"].how == "approx"
        c["custom"] += bool(r["custom"])
        c["flags"] += bool(r["match"].flags)
    return c


__all__ = ["GENERAL", "SIMPLE", "LEVEL_LABELS", "Match", "load", "entries", "entry", "norm", "level_key", "enabled",
           "set_enabled", "set_choice", "match", "values", "layout_layers", "overview", "summary"]
