"""استيراد المقرر (الحجم الساعي المقرر لكل مادة) من تقرير «نسبة تنفيذ برامج التكوين» (Excel).

الملف: كتل متتالية، كل كتلة تبدأ بسطر «الفئة : … الإختصاص : …» ثم أسطر: الرقم | المادة | المقرر | المنفذ …
نأخذ «المقرر» فقط. كل كتلة تُربط بطور واختصاص (تخمين آلي يمكن تغييره قبل الإدخال)، وكل مادة تُربط بمادة
البرنامج بالاسم. ما لم يُعرف (مادة غير موجودة، اختصاص غير معروف، قيمتان مختلفتان لنفس المادة) يُحفظ في
«مشاكل المقرر» لتعدّله وتدخله يدوياً من صفحة «المقرر».
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..db.database import Database

SKIP_KEYS = ("متحانات", "حتياط", "أيام العطل", "ايام العطل", "تغطية", "العطل", "مختلفات", "نقطاعات")
# أسماء الاختصاصات في التقرير ↔ أسماؤها في البرنامج
SPEC_SYNONYMS = {"إدارة عقابية": "كتابة الضبط", "تموين وتسيير": "تمويين وتسيير", "خياطة": "خياط",
                 "تبريد وتسخين": "تسخين وتبريد", "مطبخ إطعام وإيواء": "مطبخ وإطعام وإيواء",
                 "فندقة مكونين": "فندقة-تكويين مكونين", "فندقة عادية": "فندقة+تكوين مكونين"}


# أخطاء كتابة متكررة في التقارير ↔ الصواب
TYPOS = {"مراككز": "مراكز", "تسييير": "تسيير", "طبغرافيا": "طبوغرافيا", "طبوغرافية": "طبوغرافيا", "وسائ ": "وسائل ",
         "المبادى": "المبادئ", "بكترولوجية": "بيولوجية", "كميائية": "كيميائية", "منضم": "منظم", "أنجليزية": "إنجليزية"}


def norm(s: str) -> str:
    s = (s or "").replace("ـ", "")
    for a, b in TYPOS.items():
        s = s.replace(a, b)
    s = re.sub(r"^\s*لغة\s+", "", s)                 # «لغة فرنسية» = «فرنسية»
    s = re.sub("[إأآا]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\bبال(?=\w{3,})", "", s)         # «الإسناد بالمعتمدية» = «الإسناد المعتمدية»
    s = re.sub(r"\bال(?=\w{3,})", "", s)
    s = re.sub(r"يا\b", "يه", s)                   # «بيداغوجيا» = «بيداغوجية»
    s = re.sub(r"(.)\1+", r"\1", s)          # «تمويين» = «تموين»
    s = re.sub(r"\bو(?=\w{3,})", "", s)       # «والتبريد» → «تبريد»
    return " ".join(s.split())


_ORDS = {"اول", "اولي", "ثاني", "ثالث", "رابع", "1", "2", "3", "4"}


def similarity(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    ta, tb = set(na.split()), set(nb.split())
    jac = len(ta & tb) / len(ta | tb)
    cont = 0.0
    if (na in nb or nb in na) and min(len(na), len(nb)) >= 6:
        short, long_ = sorted((ta, tb), key=len)
        cont = 0.6 + 0.3 * (len(short) / max(1, len(long_)))
    sc = max(jac, cont, SequenceMatcher(None, na, nb).ratio() * 0.95)
    oa, ob = ta & _ORDS, tb & _ORDS
    if (oa or ob) and oa != ob:          # «مستوى ثاني» ≠ «مستوى ثالث»
        sc *= 0.6
    return sc


ACCEPT = 0.88      # فوقها: ربط آلي — تحتها: تُعرض للتأكيد مع أقرب مادة


@dataclass
class Row:
    no: int
    name: str
    hours: float
    subject_id: int | None = None
    score: float = 0.0
    status: str = "ok"            # ok | unmatched | skip | conflict
    grp: int = 1                  # رقم المجموعة داخل الجدول (تفصل بينها أسطر «المجموع»)
    phase: str = "all"            # basic إذا كانت تحت عنوان «التكوين القاعدي المشترك» في الجدول
    excel_row: int = 0


@dataclass
class Block:
    index: int
    excel_row: int
    header: str
    level_text: str
    spec_text: str
    rows: list[Row] = field(default_factory=list)
    total: float | None = None
    level_id: int | None = None
    specialty_id: int | None = None   # None = كل اختصاصات الطور
    skip: bool = False
    note: str = ""
    sub_label: str = ""                                      # الفصيلة/السرية إن وُجدت
    checks: list = field(default_factory=list)              # [(خطورة، نص، سطر Excel)]
    group_totals: dict = field(default_factory=dict)        # {رقم المجموعة: المجموع المكتوب}
    phased: bool = False                                     # في الجدول عنوان «القاعدي المشترك»

    @property
    def label(self) -> str:
        return self.header


# ------------------------------------------------------------------ القراءة
def parse(path: str) -> list[Block]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    blocks: list[Block] = []
    grp, phase = 1, "all"
    for i, r in enumerate(ws.iter_rows(min_row=1, max_col=6, values_only=True), start=1):
        r = tuple(r or ()) + (None,) * 3
        a, b1, c = r[0], r[1], r[2]
        sa = " ".join(str(a).split()) if isinstance(a, str) else ""
        sb = " ".join(str(b1).split()) if isinstance(b1, str) else ""
        if "الفئة" in sa:
            m = re.search(r"الفئة\s*:?\s*(.*?)(?:\s+(?:الإختصاص|الاختصاص|تخصص)\s*:\s*(.*))?$", sa)
            lvl = (m.group(1) if m else sa).strip(" :")
            spec = ((m.group(2) or "") if m else "").strip(" :")
            sub = ""
            for t in (spec, lvl):
                mm = re.search(r"(الفصيلة|فصيلة)\s*:?\s*(.*)$", t)
                if mm:
                    sub = mm.group(2).strip(" :")
            spec = re.sub(r"\s*(الفصيلة|فصيلة).*$", "", spec).strip(" :")
            lvl = re.sub(r"\s*(الفصيلة|فصيلة).*$", "", lvl).strip(" :")
            blk = Block(len(blocks), i, sa, lvl, spec, sub_label=sub)
            if not spec and "سنة أولى" not in lvl:
                blk.checks.append(("high", "الاختصاص فارغ في عنوان الجدول", i))
            blocks.append(blk)
            grp, phase = 1, "all"
            continue
        if not blocks:
            continue
        b = blocks[-1]
        tot_txt = sa if ("المجموع" in sa or sa.startswith("مجموع")) else (sb if "المجموع" in sb else "")
        if tot_txt:
            v = _num(c)
            if "+" in tot_txt or "العام" in tot_txt:
                b.total = v
            else:
                b.group_totals[grp] = v
                grp += 1
                phase = "all"
            continue
        if sa.startswith("التكوين") and not sb:
            if "القاعدي" in sa and b.rows:
                phase = "basic"
                b.phased = True
            continue
        name = sb if sb else ""
        if name and not name.startswith("تعين") and not name.startswith("المجموع"):
            hrs = _num(c)
            if hrs is None:
                continue
            no = int(a) if isinstance(a, (int, float)) else 0
            row = Row(no, name, hrs, grp=grp, phase=phase, excel_row=i)
            if any(k in row.name for k in SKIP_KEYS) or "مختلفات" in row.name or "الإنقطاعات" in row.name \
                    or "الانقطاعات" in row.name:
                row.status = "skip"
            b.rows.append(row)
    wb.close()
    for b in blocks:
        _check_block(b)
    _check_duplicates(blocks)
    return blocks


def _check_block(b: Block):
    """فحص الجدول: المجاميع المكتوبة مقابل المحسوبة، وقفزات الترقيم (مادة ناقصة)."""
    sums: dict[int, float] = {}
    for r in b.rows:
        sums[r.grp] = sums.get(r.grp, 0) + r.hours
    for g, v in b.group_totals.items():
        if v is not None and abs(sums.get(g, 0) - v) > 0.01:
            b.checks.append(("high", f"المجموع ({g}) المكتوب {v:g} والمحسوب {sums.get(g, 0):g} "
                                     f"(فرق {v - sums.get(g, 0):+g} سا)", b.excel_row))
    if b.total is not None and abs(sum(sums.values()) - b.total) > 0.01:
        b.checks.append(("high", f"المجموع العام المكتوب {b.total:g} والمحسوب {sum(sums.values()):g}", b.excel_row))
    nums = [r.no for r in b.rows if r.no]
    for x, y in zip(nums, nums[1:]):
        if 1 < y - x <= 3:
            miss = "، ".join(str(k) for k in range(x + 1, y))
            b.checks.append(("high", f"الترقيم يقفز من {x} إلى {y}: المادة رقم {miss} غير موجودة", b.excel_row))
    unnumbered = [r.name for r in b.rows if not r.no and r.status != "skip"]
    if unnumbered:
        b.checks.append(("low", "مواد بلا رقم: " + "، ".join(unnumbered), b.excel_row))


def _check_duplicates(blocks: list[Block]):
    """جدولان بنفس العنوان ومحتوى مختلف (مثل «فندقة» مرتين بدون فصيلة)."""
    by_head: dict[tuple, list[Block]] = {}
    for b in blocks:
        by_head.setdefault((norm(b.level_text), norm(b.spec_text), b.sub_label), []).append(b)
    for bs in by_head.values():
        if len(bs) < 2:
            continue
        sigs = {tuple(sorted((norm(r.name), r.hours) for r in x.rows)) for x in bs}
        if len(sigs) > 1:
            for x in bs[1:]:
                x.checks.append(("high", f"جدولان بنفس العنوان «{x.spec_text or x.level_text}» ببرنامجين مختلفين "
                                         f"(السطر {bs[0].excel_row} والسطر {x.excel_row}) — تأكد من اختصاص هذا الجدول",
                                 x.excel_row))


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------------ الربط الآلي
def guess_level(db: Database, text: str) -> int | None:
    t = text.replace("ـ", "")
    code = None
    if "عصاة" in t and "جنود" in t:
        code = "I-HDT-R"
    elif "عصاة" in t:
        code = "I-ESO-R"
    elif "خدمة وطنية" in t and "ضابط صف" in t:
        code = "ESO-R"
    elif "خدمة وطنية" in t:
        code = "OF-R"
    elif "شهادة" in t and "سنة أولى" in t:
        code = "ESOC1"
    elif "شهادة" in t:
        code = "ESOC2"
    elif "درجة ثانية" in t:
        code = "BMP2"
    elif "درجة أولى" in t or "درجة اولى" in t:
        code = "BMP1"
    if not code:
        return None
    return db.scalar("SELECT id FROM levels WHERE code=? ORDER BY id LIMIT 1", (code,))


def guess_specialty(db: Database, level_id: int | None, text: str) -> tuple[int | None, float]:
    if not level_id:
        return None, 0.0
    specs = db.q("SELECT id, name FROM specialties WHERE level_id=?", (level_id,))
    if len(specs) == 1:
        return specs[0]["id"], 1.0
    t = re.sub(r"(الفصيلة|فصيلة)\s*:?\s*\d+.*$", "", text or "").strip()
    if not t:
        return None, 0.0
    syn = [v for k, v in SPEC_SYNONYMS.items() if norm(k) == norm(t)]
    for s in specs:
        if syn and s["name"].replace(" ", "") == syn[0].replace(" ", ""):
            return s["id"], 1.0
    cands = [t] + [v for k, v in SPEC_SYNONYMS.items() if norm(k) in norm(t) or norm(t) in norm(k)]
    best, score = None, 0.0
    for s in specs:
        for c in cands:
            sc = similarity(c, s["name"])
            # الاختصاص «تكوين مكونين-X»: يكفي أن يطابق X
            for part in re.split(r"[-+]", s["name"]):
                sc = max(sc, similarity(c, part) * 0.98)
            if sc > score:
                best, score = s["id"], sc
    return (best, score) if score >= 0.62 else (None, score)


def match_subjects(db: Database, rows: list[Row]):
    subs = [(r["id"], r["name"]) for r in db.q("SELECT id, name FROM subjects WHERE COALESCE(kind,'teach')<>'nonteach'")]
    exact = {}
    for sid, name in subs:
        exact.setdefault(norm(name), sid)
    for row in rows:
        if row.status == "skip":
            continue
        n = norm(row.name)
        if n in exact:
            row.subject_id, row.score, row.status = exact[n], 1.0, "ok"
            continue
        best, sc = None, 0.0
        for sid, name in subs:
            s = similarity(row.name, name)
            if s > sc:
                best, sc = sid, s
        if sc >= ACCEPT:
            row.subject_id, row.score, row.status = best, sc, "ok"
        else:
            row.subject_id, row.score, row.status = (best if sc >= 0.5 else None), sc, "unmatched"


def analyze(db: Database, path: str) -> list[Block]:
    blocks = parse(path)
    for b in blocks:
        b.level_id = guess_level(db, b.level_text)
        b.specialty_id, sc = guess_specialty(db, b.level_id, b.spec_text)
        if not b.level_id:
            b.note = "الطور غير معروف"
        elif b.spec_text and not b.specialty_id:
            b.note = "الاختصاص غير معروف — اختره أو اتركه «كل الاختصاصات»"
        match_subjects(db, b.rows)
    return blocks


# ------------------------------------------------------------------ الإدخال
NEW_SUBJECT_BELOW = 0.6     # تحتها: المادة غير موجودة فعلاً في البرنامج فتُنشأ آلياً بنفس الاسم


def _phase_of(b: Block, r: Row) -> str:
    """في جداول فيها عنوان «القاعدي المشترك»: ما قبله تخصصي، وما تحته قاعدي، وما بعده للتكوين كاملاً."""
    if not b.phased:
        return "all"
    if r.phase == "basic":
        return "basic"
    first_basic = min((x.grp for x in b.rows if x.phase == "basic"), default=99)
    return "specialized" if r.grp < first_basic else "all"


def _create_subject(db: Database, name: str) -> int:
    from ..services.structure import CATEGORY_COLORS, is_shared_subject, subject_category
    from ..utils import make_abbrev
    cat = subject_category(name)
    base = make_abbrev(name)
    short, n = base, 1
    while db.scalar("SELECT 1 FROM subjects WHERE short=?", (short,)):
        n += 1
        short = f"{base} {n}"
    return db.execute("INSERT INTO subjects(name, short, color, shareable, kind, category) VALUES (?,?,?,?,?,?)",
                      (name, short, CATEGORY_COLORS.get(cat, "#CCCCCC"), int(is_shared_subject(name)),
                       "nonteach" if cat == "nonteach" else "teach", cat))


def apply(db: Database, blocks: list[Block], replace: bool = True, create_missing: bool = True) -> dict:
    """يدخل المقرر.

    * نفس المادة مرتين في نفس الجدول ونفس المرحلة: تُجمع الساعتان (مع تنبيه).
    * نفس المادة في عدة جداول لنفس الطور والاختصاص بقيم مختلفة: تُعتمد قيمة الأغلبية (مع تنبيه بالجداول المخالفة)؛
      إن تساوت القيم تُترك للمراجعة.
    * المادة غير الموجودة في البرنامج (لا تشبه أي مادة) تُنشأ بنفس اسمها؛ المشكوك فيها تُترك للمراجعة.
    * مشاكل الملف (مجاميع لا تطابق، ترقيم ناقص، اختصاص فارغ…) تصبح تنبيهات دائمة.
    """
    from ..services import alerts as AL
    values: dict[tuple, dict[float, list[str]]] = {}
    issues: list[tuple] = []
    created: dict[str, int] = {}
    summed: list[str] = []
    with db.tx():
        if replace:
            db.execute("DELETE FROM curriculum WHERE source='import'")
            db.execute("DELETE FROM curriculum_issues WHERE resolved=0")
            AL.drop_kind(db, "curriculum_file")
        for b in blocks:
            where = f"السطر {b.excel_row}: {b.spec_text or b.level_text}" + (f" — {b.sub_label}" if b.sub_label else "")
            for sev, msg, row in b.checks:
                AL.add(db, f"cf:{norm(b.header)}:{b.sub_label}:{norm(msg)}", "curriculum_file", msg,
                       f"{where}\n{b.header}", sev, b.level_id, b.specialty_id, target=f"excel:{row}")
            if b.skip or not b.level_id:
                if not b.skip:
                    issues += [(None, None, b.header, r.name, r.hours, b.note or "الطور غير معروف", None)
                               for r in b.rows if r.status != "skip"]
                continue
            agg: dict[tuple, list[float]] = {}
            for r in b.rows:
                if r.status == "skip":
                    continue
                if (r.status != "ok" or not r.subject_id) and create_missing and r.score < NEW_SUBJECT_BELOW:
                    key = norm(r.name)
                    if key not in created:
                        created[key] = _create_subject(db, r.name)
                    r.subject_id, r.status, r.score = created[key], "ok", 1.0
                if r.status != "ok" or not r.subject_id:
                    issues.append((b.level_id, b.specialty_id, b.header, r.name, r.hours,
                                   "مادة غير موجودة في البرنامج — اختر المادة المقابلة", r.subject_id))
                    continue
                agg.setdefault((r.subject_id, _phase_of(b, r)), []).append(r.hours)
            for (sub, ph), hs in agg.items():
                if len(hs) > 1:
                    nm = db.scalar("SELECT name FROM subjects WHERE id=?", (sub,))
                    summed.append(f"{nm}: {' + '.join(f'{h:g}' for h in hs)} = {sum(hs):g} ({where})")
                key = (b.level_id, b.specialty_id or 0, sub, ph)
                values.setdefault(key, {}).setdefault(sum(hs), []).append(where)
        n = conflicts = majority = 0
        deviants: dict[tuple, list[str]] = {}
        for (lvl, spec, sub, ph), vals in values.items():
            if len(vals) > 1:
                ranked = sorted(vals.items(), key=lambda kv: -len(kv[1]))
                if len(ranked[0][1]) == len(ranked[1][1]):
                    conflicts += 1
                    name = db.scalar("SELECT name FROM subjects WHERE id=?", (sub,))
                    for h, heads in vals.items():
                        issues.append((lvl, spec or None, " / ".join(heads[:2]), name, h,
                                       "قيمتان مختلفتان لنفس المادة — اختر الصحيحة", sub))
                    continue
                majority += 1
                hours = ranked[0][0]
                name = db.scalar("SELECT name FROM subjects WHERE id=?", (sub,))
                for h, ws_ in ranked[1:]:
                    for w in ws_:
                        deviants.setdefault((lvl, spec, w), []).append(f"{name}: {h:g} سا (الأغلبية {hours:g})")
            else:
                hours = next(iter(vals))
            if db.one("""SELECT id FROM curriculum WHERE level_id=? AND specialty_id=? AND subject_id=? AND phase=?
                         AND source='manual'""", (lvl, spec, sub, ph)):
                continue                  # لا نكتب فوق ما أدخلته يدوياً
            db.execute("""INSERT INTO curriculum(level_id, specialty_id, subject_id, phase, hours, source)
                          VALUES (?,?,?,?,?,'import')
                          ON CONFLICT(level_id, specialty_id, subject_id, phase) DO UPDATE SET hours=excluded.hours,
                          source='import'""", (lvl, spec, sub, ph, hours))
            n += 1
        for (lvl, spec, w), lst in deviants.items():
            AL.add(db, f"dev:{lvl}:{spec}:{norm(w)}", "curriculum_file",
                   f"جدول يخالف باقي جداول نفس الاختصاص في {len(lst)} مادة: اعتُمدت قيمة الأغلبية",
                   f"{w}\n" + "\n".join(lst), "medium", lvl, spec or None, target="curriculum")
        if summed:
            AL.add(db, "cf:summed", "curriculum_file", f"{len(summed)} مادة مكررة داخل نفس الجدول: جُمعت ساعاتها",
                   "\n".join(summed), "medium", target="curriculum")
        if created:
            names = sorted(db.scalar("SELECT name FROM subjects WHERE id=?", (x,)) for x in created.values())
            AL.add(db, "cf:created", "curriculum_file", f"{len(created)} مادة جديدة أُنشئت من المقرر",
                   "مواد موجودة في المقرر ولم تُدرَّس بعد في الجداول المستوردة. راجع أنواعها في صفحة المواد:\n"
                   + "، ".join(names), "low", target="subjects")
        seen = set()
        for lvl, spec, block, name, hours, reason, guess in issues:
            k = (lvl, spec or 0, norm(name), hours)
            if k in seen:
                continue
            seen.add(k)
            db.execute("""INSERT INTO curriculum_issues(level_id, specialty_id, block, name, hours, reason, guess_subject_id)
                          VALUES (?,?,?,?,?,?,?)""", (lvl, spec, block, name, hours, reason, guess))
        db.log("استيراد المقرر", "curriculum", None, {"imported": n, "issues": len(seen), "conflicts": conflicts,
                                                    "created": len(created), "majority": majority})
    return {"imported": n, "issues": len(seen), "conflicts": conflicts, "created": len(created),
            "majority": majority, "summed": len(summed)}


def resolve_issue(db: Database, issue_id: int, level_id: int, specialty_id: int | None, subject_id: int, hours: float):
    from ..services.progress import set_hours
    set_hours(db, level_id, specialty_id, subject_id, "all", hours)
    with db.tx():
        db.execute("UPDATE curriculum_issues SET resolved=1 WHERE id=?", (issue_id,))
        # نفس المادة ونفس الطور/الاختصاص في مشاكل أخرى (قيم متعارضة) تُغلق أيضاً
        db.execute("""UPDATE curriculum_issues SET resolved=1 WHERE resolved=0 AND level_id=? AND
                      COALESCE(specialty_id,0)=? AND guess_subject_id=? AND reason LIKE 'قيمتان%'""",
                   (level_id, specialty_id or 0, subject_id))


def dismiss_issue(db: Database, issue_id: int):
    db.execute("UPDATE curriculum_issues SET resolved=2 WHERE id=?", (issue_id,))
    db.commit()


# ------------------------------------------------------------------ المقرر المرفق مع البرنامج
def bundled_file():
    """ملف المقرر المرفق مع البرنامج (تقرير نسبة التنفيذ الذي أرسله المستخدم)."""
    import sys
    from pathlib import Path
    for base in (Path(getattr(sys, "_MEIPASS", "")) / "dpp", Path(__file__).resolve().parent.parent):
        p = base / "assets" / "curriculum" / "المقرر.xlsx"
        if p.exists():
            return p
    return None


def bootstrap(db: Database, force: bool = False) -> dict | None:
    """يدرج المقرر المرفق مرة واحدة إذا كان المقرر المستورد شبه فارغ (لا يمس ما أدخلته يدوياً)."""
    path = bundled_file()
    if not path or (db.get_setting("curriculum_bundled_v1", "") == "1" and not force):
        return None
    if not db.scalar("SELECT COUNT(*) FROM levels WHERE code IS NOT NULL", (), 0):
        return None                         # لا توجد أطوار بعد: نحاول في التشغيل القادم
    if not force and db.scalar("SELECT COUNT(*) FROM curriculum WHERE source='import'", (), 0) >= 100:
        db.set_setting("curriculum_bundled_v1", "1")
        return None
    res = apply(db, analyze(db, str(path)), replace=True)
    db.set_setting("curriculum_bundled_v1", "1")
    return res
