"""الهيكل: تكوين ← طور ← اختصاص ← دورة ← قسم، وأنواع المواد وقواعد المشاركة.

كل القيم هنا افتراضية قابلة للتعديل من الواجهة؛ تُستعمل عند الاستيراد الأول أو لإنشاء الهيكل.
"""
from __future__ import annotations

import re

from ..db.database import Database

# ------------------------------------------------------------------ التكوينات والأطوار
FORMATIONS = [
    # (اسم التكوين، الرمز، البداية، النهاية)
    ("الأهلية المهنية", "BMP", "2026-09-13", "2027-06-25"),
    ("الطلبة ضباط الصف المتعاقدين", "ESOC", "2026-09-13", "2027-06-25"),
    ("الاحتياط", "R", "2026-09-15", "2027-09-15"),
]

# code: (formation_short, full_name, short_name, color, lunch_period, profile, sort)
LEVELS = {
    "BMP2": ("BMP", "أهلية مهنية عسكرية درجة ثانية", "أ م ع د 2", "#2E86DE", 4, "standard", 1),
    "BMP1": ("BMP", "أهلية مهنية عسكرية درجة أولى", "أ م ع د 1", "#10AC84", 3, "standard", 2),
    "ESOC2": ("ESOC", "طالب ضابط صف متعاقد سنة ثانية", "ESOC 2", "#E15F41", 3, "standard", 3),
    "ESOC1": ("ESOC", "طالب ضابط صف متعاقد سنة أولى", "ESOC 1", "#C44569", 3, "basic_night", 4),
    "OF-R": ("R", "طالب ضابط احتياطي", "OF-R", "#6C5CE7", 3, "basic", 5),
    "ESO-R": ("R", "طالب ضابط صف احتياط", "ESO-R", "#F19066", 3, "basic", 6),
    "I-ESO-R": ("R", "طالب ضابط صف احتياط (العصاة)", "I-ESO-R", "#786FA6", 3, "basic", 7),
    "I-HDT-R": ("R", "طالب جندي احتياطي (العصاة)", "I-HDT-R", "#3DC1D3", 3, "basic", 8),
}

COHORTS = {
    "BMP2": [("الدورة 2026-2027", "2026-09-13", "2027-06-25")],
    "BMP1": [("الدورة الأولى", "2026-09-13", "2027-02-05"), ("الدورة الثانية", "2027-02-07", "2027-06-25")],
    "ESOC2": [("الدورة 2026-2027", "2026-09-13", "2027-06-25")],
    "ESOC1": [("المدنيون", "2026-09-13", "2027-06-25"), ("من الصفوف", "2027-02-02", "2027-06-25")],
    "OF-R": [("الدفعة 1", "2026-09-15", "2027-01-15"), ("الدفعة 2", "2027-01-15", "2027-05-15"),
             ("الدفعة 3", "2027-05-15", "2027-09-15")],
}
for _c in ("ESO-R", "I-ESO-R", "I-HDT-R"):
    COHORTS[_c] = COHORTS["OF-R"]


def classify_class(name: str) -> str | None:
    """يحدد رمز الطور من اسم القسم كما كُتب في aSc."""
    n = re.sub(r"\s+", " ", name)
    if "أ م ع د 2" in n:
        return "BMP2"
    if "أ م ع د 1" in n:
        return "BMP1"
    if "سنة ثانية" in n:
        return "ESOC2"
    if "سنة أولى" in n or "سنة اولى" in n:
        return "ESOC1"
    if "العصاة" in n and "جنود" in n:
        return "I-HDT-R"
    if "العصاة" in n:
        return "I-ESO-R"
    if "طلبة ضباط الصف" in n:
        return "ESO-R"
    if "طلبة ضباط" in n:
        return "OF-R"
    return None


ORDINALS = {"أولى": 1, "اولى": 1, "ثانية": 2, "ثالثة": 3, "رابعة": 4, "خامسة": 5, "سادسة": 6, "سابعة": 7,
            "ثامنة": 8, "تاسعة": 9, "عاشرة": 10, "الحادي عشر": 11, "الثاني عشر": 12, "الثالث عشر": 13,
            "الرابع عشر": 14, "الخامس عشر": 15}


def _ordinal(text: str) -> int | None:
    for k in sorted(ORDINALS, key=len, reverse=True):
        if k in text:
            return ORDINALS[k]
    return None


def split_class(name: str, code: str) -> tuple[str, str]:
    """(الاختصاص، الجزء: فصيلة/سرية) من اسم القسم."""
    inner = name[name.find("(") + 1:name.rfind(")")] if "(" in name else name
    inner = inner.strip()
    if code in ("BMP2", "BMP1"):
        spec = inner.split(":", 1)[1].strip() if ":" in inner else inner
        return spec, ""
    if code == "ESOC2":
        m = re.split(r"[:\-]\s*(فصيلة.*)$", inner)
        if len(m) >= 2:
            return m[0].strip(), m[1].strip()
        return inner, ""
    if code == "ESOC1":
        return "التكوين القاعدي المشترك", inner
    return LEVELS[code][1], ""


def section_short(code: str, spec: str, part: str, asc_short: str) -> str:
    """رمز مختصر مقروء للقسم في الجدول العام، مثل BMP2-فندقة أو ESOC2-مطبخ ف3."""
    s = asc_short or ""
    if "-" in s and len(s) < 40:
        s = s.split("-", 1)[1].strip()
    else:
        s = ""
    if not s:
        words = [w for w in re.split(r"[\s+\-]+", spec) if w and w not in ("و", "وصيانة")]
        s = " ".join(words[:2]) if code in ("BMP2", "BMP1", "ESOC2") else ""
    s = re.sub(r"\d+$", "", s).strip()
    out = code + (f"-{s}" if s else "")
    n = _ordinal(part) if part else None
    if n:
        out += (" ف" if "فصيلة" in part else " س") + str(n)
    return out


# ------------------------------------------------------------------ المواد
NONTEACH_KEYS = ("وجبة الغذاء", "عطلة نهاية الأسبوع", "تحت تصرف", "إفتتاح", "افتتاح", "اجازة", "إجازة",
                 "خفارة", "خدمات", "ذكرى", "حفل", "استراحة", "عطلة")
PE_KEYS = ("تربية بدنية", "العدو الريفي", "السباق")
DRILL_KEYS = ("نظام منظم",)
MILITARY_KEYS = ("رمي", "نظام الخدمة", "قتال", "طبوغرافيا", "أسلحة", "الإشارة", "القضاء العسكري", "فن القيادة",
                 "أمن الجيش", "تدريب هندسي", "أخلاقيات عسكرية", "الإرهاب", "المراسلات العسكرية", "مراسلة عسكرية",
                 "تكتيك", "الأعمال الهدامة", "القانون الدولي الإنساني", "هندسة القتال", "التعبئة", "الإستطلاع",
                 "استطلاع", "محاضرة", "محاضرات", "وقاية وأمن", "السيبيراني", "السيبراني", "إسعاف", "الأجنبية",
                 "العسكري", "إيصال ، إعلام", "الجيش الوطني")
GENERAL_KEYS = ("لغة", "إعلام آلي", "تاريخ الجزائر", "علم النفس", "بيداغوجية", "هندسة التكوين",
                "تقنيات الإتصال", "البيئة", "الإحصاء", "إتصال والعلاقات")
SHARED_KEYS_EXACT = ("تربية بدنية عسكرية", "العدو الريفي", "محاضرات وندوات")

CATEGORY_LABELS = {"military": "عسكرية", "general": "عامة", "specialty": "اختصاص", "pe": "تربية بدنية",
                   "drill": "نظام منظم", "nonteach": "غير دراسية"}
CATEGORY_COLORS = {"military": "#F4A9A2", "general": "#FBE08A", "specialty": "#F8C38E", "pe": "#F5BFD8",
                   "drill": "#9FD9E6", "nonteach": "#DDE4E6"}


def normalize(name: str) -> str:
    return " ".join(name.replace("ـ", "").split())


def arabic_short(name: str, limit: int = 18) -> str:
    """اسم مختصر مقروء للبطاقة: الكلمات الأولى حتى ~18 حرفاً."""
    words = normalize(name).replace("محاضرة بعنوان", "محاضرة").replace(":", " ").split()
    out = ""
    for w in words:
        if out and len(out) + 1 + len(w) > limit:
            break
        out = f"{out} {w}".strip()
    return out or normalize(name)[:limit]


def subject_category(name: str) -> str:
    name = normalize(name)
    if any(name.startswith(k) for k in NONTEACH_KEYS):
        return "nonteach"
    if any(k in name for k in DRILL_KEYS):
        return "drill"
    if any(k in name for k in PE_KEYS):
        return "pe"
    if any(k in name for k in MILITARY_KEYS):
        return "military"
    if any(k in name for k in GENERAL_KEYS):
        return "general"
    return "specialty"


def is_shared_subject(name: str) -> bool:
    """المواد المشتركة: الرمي، التربية البدنية، العدو الريفي، النظام المنظم، المحاضرات."""
    n = name.strip()
    return ("رمي" in n or n.startswith("محاضرة") or n.startswith("محاضرات") or "نظام منظم" in n
            or n in SHARED_KEYS_EXACT)


def classify_subject(db: Database, subject_id: int, name: str, force=False):
    row = db.one("SELECT kind, category FROM subjects WHERE id=?", (subject_id,))
    if row and not force and row["category"] not in (None, "", "specialty"):
        return
    cat = subject_category(name)
    db.execute("UPDATE subjects SET category=?, kind=?, shareable=?, color=? WHERE id=?",
               (cat, "nonteach" if cat == "nonteach" else "teach", int(is_shared_subject(name)),
                CATEGORY_COLORS[cat], subject_id))


# ------------------------------------------------------------------ إنشاء الهيكل
def ensure_structure(db: Database) -> dict[str, int]:
    """ينشئ التكوينات الثلاثة والأطوار الثمانية ودوراتها إن لم توجد. يعيد {رمز الطور: level_id}."""
    out = {}
    with db.tx():
        fids = {}
        for name, short, s, e in FORMATIONS:
            r = db.one("SELECT id FROM formations WHERE short=?", (short,))
            fids[short] = r["id"] if r else db.insert("formations", name=name, short=short, start_date=s,
                                                      end_date=e, rest_days="5,6")
        for code, (fs, full, short, color, lunch, prof, sort) in LEVELS.items():
            r = db.one("SELECT id FROM levels WHERE code=?", (code,))
            if r:
                out[code] = r["id"]
                continue
            lid = db.insert("levels", formation_id=fids[fs], name=full, short=short, code=code, color=color,
                            lunch_period=lunch, profile=prof, sort=sort, full_name=full)
            out[code] = lid
            for cname, cs, ce in COHORTS.get(code, []):
                db.insert("cohorts", level_id=lid, name=cname, start_date=cs, end_date=ce,
                          week_mode="first_full" if fs == "R" else "start")
    return out


def level_of_section(db: Database, section_id: int):
    return db.one("""SELECT l.* FROM sections s JOIN levels l ON l.id=s.level_id WHERE s.id=?""", (section_id,))
