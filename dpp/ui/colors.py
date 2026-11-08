"""ألوان المواد: كل نوع له عائلة لون، وكل مادة لها درجتها الخاصة داخل عائلتها.

* عسكرية (وتشمل التربية البدنية والنظام المنظم): أخضر.
* اختصاص: أزرق.
* عامة: عسلي.
* غير دراسية: رمادي.

الدرجة ثابتة لكل مادة (تُحسب من رقمها)، فتبقى المادة بنفس اللون في الجدول والشريط والطباعة.

ألوان البطاقات قابلة للضبط (الإعدادات ← الجدول العام، المفتاح card_colors):
* لوحة جاهزة: الأصلية، فاتحة، باردة، حارة، زاهية، رمادية، تباين عالٍ.
* الشدة (0–100، 50 = اللوحة كما هي): تزيد الإشباع وتُغمق قليلاً، أو العكس.
* لون لكل عائلة يختاره المستخدم (عسكرية/اختصاص/عامة) يحل محل تدرج اللوحة، وتبقى درجة لكل مادة.
* لون الكتابة: تلقائي (حسب سطوع البطاقة)، أسود، أو أبيض.
"""
from __future__ import annotations

import colorsys

from PySide6.QtGui import QColor

FAMILY = {"military": "military", "pe": "military", "drill": "military",
          "specialty": "specialty", "general": "general", "nonteach": "nonteach"}
# (تدرج اللون، الإشباع الأدنى، الإشباع الأعلى)
HUES = {"military": (0.27, 0.30, 0.52), "specialty": (0.585, 0.38, 0.62), "general": (0.11, 0.55, 0.80),
        "nonteach": (0.55, 0.04, 0.10)}
FAMILY_LABELS = {"military": "عسكرية", "specialty": "اختصاص", "general": "عامة", "nonteach": "غير دراسية"}
# لون العائلة الأساسي (للمفاتيح والأشرطة والرسوم)
FAMILY_BASE = {"military": "#4F7A2A", "specialty": "#2B5C9B", "general": "#A26B0F", "nonteach": "#7A8790"}

_GOLD = 0.61803398875

# اللوحات: لكل عائلة (التدرج، الإشباع الأدنى، الأعلى)، ومجال السطوع (الأدنى، المدى)
PRESETS = {
    "default": {"label": "الأصلية", "hues": HUES, "light": (0.70, 0.16)},
    "light": {"label": "فاتحة", "hues": {"military": (0.27, 0.25, 0.42), "specialty": (0.585, 0.32, 0.52),
                                         "general": (0.11, 0.45, 0.70), "nonteach": (0.55, 0.03, 0.08)},
              "light": (0.82, 0.10)},
    "cool": {"label": "باردة", "hues": {"military": (0.43, 0.30, 0.50), "specialty": (0.60, 0.40, 0.62),
                                        "general": (0.74, 0.28, 0.48), "nonteach": (0.58, 0.05, 0.10)},
             "light": (0.70, 0.15)},
    "warm": {"label": "حارة", "hues": {"military": (0.20, 0.40, 0.60), "specialty": (0.01, 0.45, 0.65),
                                       "general": (0.09, 0.60, 0.85), "nonteach": (0.08, 0.06, 0.12)},
             "light": (0.70, 0.15)},
    "vivid": {"label": "زاهية", "hues": {"military": (0.30, 0.60, 0.85), "specialty": (0.58, 0.65, 0.90),
                                         "general": (0.10, 0.75, 0.95), "nonteach": (0.55, 0.08, 0.15)},
              "light": (0.58, 0.14)},
    "gray": {"label": "رمادية", "hues": {"military": (0.30, 0.00, 0.06), "specialty": (0.60, 0.00, 0.06),
                                         "general": (0.10, 0.00, 0.06), "nonteach": (0.55, 0.00, 0.03)},
             "light": (0.64, 0.24)},
    "contrast": {"label": "تباين عالٍ", "hues": {"military": (0.30, 0.65, 0.85), "specialty": (0.60, 0.65, 0.85),
                                                 "general": (0.07, 0.75, 0.95), "nonteach": (0.55, 0.05, 0.10)},
                 "light": (0.30, 0.10)},
}
DEFAULT_CONFIG = {"preset": "default", "intensity": 50, "families": {}, "text": "auto"}
CONFIG = dict(DEFAULT_CONFIG)


def load_config(db) -> dict:
    """يقرأ card_colors ويجعله الإعداد الحالي لكل الرسم."""
    import json
    o = dict(DEFAULT_CONFIG)
    try:
        o.update(json.loads(db.get_setting("card_colors", "") or "{}"))
    except Exception:
        pass
    if o.get("preset") not in PRESETS:
        o["preset"] = "default"
    CONFIG.clear()
    CONFIG.update(o)
    return o


def save_config(db, o: dict) -> None:
    import json
    db.set_setting("card_colors", json.dumps(o, ensure_ascii=False))
    CONFIG.clear()
    CONFIG.update({**DEFAULT_CONFIG, **o})


def text_for(bg: QColor, cfg: dict | None = None) -> QColor:
    """لون الكتابة على بطاقة: تلقائي حسب السطوع، أو أسود/أبيض حسب الإعداد."""
    mode = (cfg or CONFIG).get("text", "auto")
    if mode == "black":
        return QColor("#111418")
    if mode == "white":
        return QColor("#FFFFFF")
    lum = 0.299 * bg.red() + 0.587 * bg.green() + 0.114 * bg.blue()
    return QColor("#1B1F24") if lum > 150 else QColor("#FFFFFF")


def family(category: str | None) -> str:
    return FAMILY.get(category or "specialty", "specialty")


def subject_shade(category: str | None, subject_id: int | None, cfg: dict | None = None) -> QColor:
    """لون مميز للمادة داخل عائلة نوعها، حسب اللوحة والشدة ولون العائلة المختار."""
    cfg = cfg or CONFIG
    pr = PRESETS.get(cfg.get("preset", "default"), PRESETS["default"])
    fam = family(category)
    h0, s_lo, s_hi = pr["hues"][fam]
    l0, lr = pr["light"]
    custom = (cfg.get("families") or {}).get(fam)
    if custom and QColor(custom).isValid():
        ch, cs, cl, _ = QColor(custom).getHslF()
        h0 = ch if ch >= 0 else h0
        s_lo, s_hi = max(0.0, cs * 0.75), min(1.0, cs * 1.05)
        l0, lr = max(0.25, cl - 0.06), 0.16
    k = ((subject_id or 0) * _GOLD) % 1.0
    k2 = ((subject_id or 0) * 0.38196601125 + 0.17) % 1.0
    h = (h0 + (k - 0.5) * 0.07) % 1.0
    light = l0 + lr * k2
    sat = s_lo + (s_hi - s_lo) * k
    t = (float(cfg.get("intensity", 50)) - 50) / 50.0            # -1 … +1
    sat = min(1.0, max(0.0, sat * (1 + 0.6 * t)))
    light = min(0.95, max(0.18, light - 0.12 * t))
    r, g, b = colorsys.hls_to_rgb(h, light, sat)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def family_color(category: str | None) -> QColor:
    return QColor(FAMILY_BASE[family(category)])
