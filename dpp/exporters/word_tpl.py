"""قوالب Word لأوراق الأقسام: قالب لكل طور، وقالب خاص لقسم عند الحاجة (يرث من طوره).

* أول نسخة من القالب تُولَّد من التصميم الحالي (الرأس، جدول الأيام × الحصص، الملاحظة، التوقيعات).
* القالب ملف Word عادي يعدّله المستخدم في Word: النصوص، الخطوط، الألوان، الحدود، الشعار…
  فيه حقول بين قوسين تُملأ عند الإخراج: {القسم} {الأسبوع} {من} {إلى} … (القائمة في FIELDS).
* جدول الحصص يُعرف بعموده الأول (أسماء الأيام). البرنامج يضبط عدد أعمدة الحصص وعناوينها حسب القسم،
  ويكتب في كل خانة المادة والأستاذ والقاعة، ويدمج الخانات للحصص الطويلة. تنسيق الخانات يؤخذ من القالب.
* القوالب المعتمدة محفوظة في قاعدة البيانات (word_tpl:L<الطور> / word_tpl:S<القسم>)، فتدخل في النسخ الاحتياطي.
  نسخة التعديل ملف في مجلد البيانات «قوالب Word»؛ عند حفظها في Word تُفحص وتُستورد (انظر ui/word_watch.py).
"""
from __future__ import annotations

import base64
import copy
import io
import json
import re
from datetime import datetime
from pathlib import Path

from ..db.database import Database, default_data_dir
from ..utils import DAY_NAMES

# الحقول المتاحة في القالب ← مفتاح القيمة في الورقة (sheet.values)
FIELDS = {
    "القسم": "section", "الرمز": "short", "الطور": "level", "الاختصاص": "specialty", "التكوين": "formation",
    "الأسبوع": "week", "الأسبوع_بالحروف": "week_words", "من": "d0", "إلى": "d1",
    "السنة_الدراسية": "year", "المقرر": "decree", "تاريخ_المقرر": "decree_date", "القاعة": "room",
    "اليوم": "today", "المؤسسة": "institution",
}
# رموز النصوص الحالية (بالإنجليزية) ← الحقل العربي في القالب
EN_TO_AR = {"week_words": "الأسبوع_بالحروف", "week": "الأسبوع", "decree_date": "تاريخ_المقرر", "decree": "المقرر",
            "target": "القسم", "section": "القسم", "short": "الرمز", "level": "الطور", "room": "القاعة",
            "d0": "من", "d1": "إلى", "year": "السنة_الدراسية", "today": "اليوم", "specialty": "الاختصاص",
            "formation": "التكوين", "institution": "المؤسسة"}
GRID_CORNER = "الأيام"
FIELD_RE = re.compile(r"\{([^{}\n]+)\}")
WORK_DAYS = 5                     # الأحد … الخميس في القالب المولَّد؛ الجمعة والسبت يُضافان عند وجود حصص


class TemplateError(Exception):
    pass


# ====================================================================== التخزين
def scope_key(level_id: int | None = None, section_id: int | None = None) -> str:
    return f"S{section_id}" if section_id else f"L{level_id}"


def stored(db: Database, scope: str) -> bytes | None:
    v = db.get_setting(f"word_tpl:{scope}", "")
    return base64.b64decode(v) if v else None


def meta(db: Database) -> dict:
    try:
        return json.loads(db.get_setting("word_tpl_meta", "") or "{}")
    except Exception:
        return {}


def store(db: Database, scope: str, data: bytes, source: str = "word") -> None:
    db.set_setting(f"word_tpl:{scope}", base64.b64encode(data).decode())
    m = meta(db)
    m[scope] = {"updated": datetime.now().strftime("%Y-%m-%d %H:%M"), "by": getattr(db, "current_user", ""),
                "source": source}
    db.set_setting("word_tpl_meta", json.dumps(m, ensure_ascii=False))
    db.log("استيراد قالب Word", "word_templates", None, {"scope": scope, "source": source})


def remove(db: Database, scope: str) -> None:
    db.set_setting(f"word_tpl:{scope}", "")
    m = meta(db)
    m.pop(scope, None)
    db.set_setting("word_tpl_meta", json.dumps(m, ensure_ascii=False))
    db.log("إرجاع قالب Word إلى الافتراضي", "word_templates", None, {"scope": scope})


def effective(db: Database, section_id: int) -> tuple[bytes, str]:
    """القالب المستعمل لقسم: الخاص به، وإلا قالب طوره، وإلا قالب مولَّد من التصميم الحالي. (البيانات، المصدر)."""
    lvl = db.scalar("SELECT level_id FROM sections WHERE id=?", (section_id,))
    own = stored(db, scope_key(section_id=section_id))
    if own:
        return own, scope_key(section_id=section_id)
    lv = stored(db, scope_key(level_id=lvl)) if lvl else None
    if lv:
        return lv, scope_key(level_id=lvl)
    return generate(db, lvl, section_id), "generated"


def scope_bytes(db: Database, scope: str) -> bytes:
    """محتوى نطاق للتعديل: المحفوظ له، أو ما يرثه (القسم يرث طوره)، أو المولَّد."""
    data = stored(db, scope)
    if data:
        return data
    if scope.startswith("S"):
        return effective(db, int(scope[1:]))[0]
    lvl = int(scope[1:])
    sec = db.scalar("SELECT id FROM sections WHERE level_id=? ORDER BY sort, id LIMIT 1", (lvl,))
    return generate(db, lvl, sec)


def templates_dir() -> Path:
    d = default_data_dir() / "قوالب Word"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", name).strip() or "قالب"


def edit_path(db: Database, scope: str) -> Path:
    if scope.startswith("S"):
        r = db.one("SELECT short, name FROM sections WHERE id=?", (int(scope[1:]),))
        nm = f"قالب القسم - {(r['short'] or r['name']) if r else scope}"
    else:
        r = db.one("SELECT code, name FROM levels WHERE id=?", (int(scope[1:]),))
        nm = f"قالب الطور - {(r['code'] or r['name']) if r else scope}"
    return templates_dir() / f"{_safe(nm)}.docx"


def scope_label(db: Database, scope: str) -> str:
    if scope.startswith("S"):
        r = db.one("SELECT short, name FROM sections WHERE id=?", (int(scope[1:]),))
        return f"القسم {(r['short'] or r['name']) if r else '?'}"
    r = db.one("SELECT code, name FROM levels WHERE id=?", (int(scope[1:]),))
    return f"الطور {(r['code'] or r['name']) if r else '?'}"


# ====================================================================== أدوات XML (اتجاه عربي)
def _q(tag):
    from docx.oxml.ns import qn
    return qn(tag)


def _el(tag, **attrs):
    from docx.oxml import OxmlElement
    e = OxmlElement(tag)
    for k, v in attrs.items():
        e.set(_q(k), str(v))
    return e


def _set_child(parent, tag, **attrs):
    old = parent.find(_q(tag))
    if old is not None:
        parent.remove(old)
    e = _el(tag, **attrs)
    parent.append(e)
    return e


def rtl_paragraph(p, align: str = "center"):
    """فقرة من اليمين إلى اليسار. في فقرة bidi تعني «left» بداية السطر (اليمين) كما في Word."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    pPr = p._p.get_or_add_pPr()
    if pPr.find(_q("w:bidi")) is None:
        pPr.insert(0, _el("w:bidi"))
    p.alignment = {"center": WD_ALIGN_PARAGRAPH.CENTER, "right": WD_ALIGN_PARAGRAPH.LEFT,
                   "left": WD_ALIGN_PARAGRAPH.RIGHT, "justify": WD_ALIGN_PARAGRAPH.JUSTIFY}[align]
    pf = p.paragraph_format
    from docx.shared import Pt
    pf.space_before = Pt(0)
    pf.space_after = Pt(0)


def style_run(r, size: float | None = None, bold: bool | None = None, font: str | None = None,
              underline: bool | None = None, color: str | None = None):
    """خط عربي صحيح: Word يأخذ حجم وسماكة النص العربي من szCs/bCs وخطه من rFonts@cs."""
    from docx.shared import Pt, RGBColor
    rPr = r._r.get_or_add_rPr()
    if rPr.find(_q("w:rtl")) is None:
        rPr.append(_el("w:rtl"))
    if font:
        r.font.name = font
        rf = rPr.find(_q("w:rFonts"))
        if rf is None:
            rf = _el("w:rFonts")
            rPr.insert(0, rf)
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(_q(a), font)
    if size:
        r.font.size = Pt(size)
        _set_child(rPr, "w:szCs", **{"w:val": int(round(size * 2))})
    if bold is not None:
        r.font.bold = bold
        if bold:
            _set_child(rPr, "w:bCs")
        else:
            x = rPr.find(_q("w:bCs"))
            if x is not None:
                rPr.remove(x)
    if underline is not None:
        r.font.underline = underline
    if color:
        r.font.color.rgb = RGBColor.from_string(color.lstrip("#").upper())


def _table_rtl(t, borders: bool = True):
    tblPr = t._tbl.tblPr
    if tblPr.find(_q("w:bidiVisual")) is None:
        tblPr.append(_el("w:bidiVisual"))
    if not borders:
        tb = _set_child(tblPr, "w:tblBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            tb.append(_el(f"w:{side}", **{"w:val": "nil"}))


def _cell_text(cell, lines: list[tuple[str, dict]], align="center"):
    """يكتب أسطراً في خانة مع الإبقاء على تنسيق أول فقرة/حرف في القالب."""
    paras = cell.paragraphs
    p0 = paras[0]
    tpl_rpr = None
    if p0.runs:
        rp = p0.runs[0]._r.find(_q("w:rPr"))
        tpl_rpr = copy.deepcopy(rp) if rp is not None else None
    tpl_ppr = p0._p.find(_q("w:pPr"))
    tpl_ppr = copy.deepcopy(tpl_ppr) if tpl_ppr is not None else None
    for p in paras[1:]:
        p._p.getparent().remove(p._p)
    for r in list(p0.runs):
        r._r.getparent().remove(r._r)
    first = True
    for text, st in lines:
        if not text:
            continue
        if first:
            p = p0
            first = False
        else:
            p = cell.add_paragraph()
            if tpl_ppr is not None:
                old = p._p.find(_q("w:pPr"))
                if old is not None:
                    p._p.remove(old)
                p._p.insert(0, copy.deepcopy(tpl_ppr))
        if p._p.find(_q("w:pPr")) is None or p._p.find(_q("w:pPr")).find(_q("w:bidi")) is None:
            rtl_paragraph(p, align)
        r = p.add_run(text)
        if tpl_rpr is not None:
            r._r.insert(0, copy.deepcopy(tpl_rpr))
        style_run(r, size=st.get("size"), bold=st.get("bold"))


def _shade(cell, color: str | None):
    tcPr = cell._tc.get_or_add_tcPr()
    old = tcPr.find(_q("w:shd"))
    if old is not None:
        tcPr.remove(old)
    if color:
        tcPr.append(_el("w:shd", **{"w:val": "clear", "w:color": "auto", "w:fill": color.lstrip("#").upper()}))


# ====================================================================== توليد القالب الأول
def _ar_fields(text: str) -> str:
    return FIELD_RE.sub(lambda m: "{" + EN_TO_AR.get(m.group(1), m.group(1)) + "}", text or "")


def generate(db: Database, level_id: int | None, section_id: int | None = None) -> bytes:
    """قالب Word من التصميم الحالي لورقة القسم (النصوص بحقولها، الورق والهوامش، أعمدة الحصص)."""
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.shared import Mm, Pt
    from . import layout as L
    from . import official as O
    raw = O.template_fields(db, "section", level_id)
    st = O.template_style(db)
    font = st.get("font") or "Arial"
    lay, _ = L.effective(db, "section", level_id, section_id)
    page = lay.get("page", {})
    if section_id:
        prof = db.scalar("""SELECT COALESCE(s.profile, l.profile, 'standard') FROM sections s
                            LEFT JOIN levels l ON l.id=s.level_id WHERE s.id=?""", (section_id,), "standard")
    else:
        prof = db.scalar("SELECT COALESCE(profile,'standard') FROM levels WHERE id=?", (level_id,), "standard")
    periods = [p for p in O._profile_periods(db, prof) if p[3] != "night"] or O._profile_periods(db, "standard")

    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE if page.get("orientation", "landscape") == "landscape" else WD_ORIENT.PORTRAIT
    w, h = {"A3": (420, 297), "A5": (210, 148)}.get(page.get("paper", "A4"), (297, 210))
    if sec.orientation == WD_ORIENT.PORTRAIT:
        w, h = h, w
    sec.page_width, sec.page_height = Mm(w), Mm(h)
    m = page.get("margins") or [20, 20, 20, 20]            # نقاط: أعلى، يمين، أسفل، يسار
    try:
        top, right, bottom, left = (max(5.0, float(x) * 25.4 / 72) for x in m)
    except Exception:
        top = right = bottom = left = 8.0
    sec.top_margin, sec.right_margin, sec.bottom_margin, sec.left_margin = Mm(top), Mm(right), Mm(bottom), Mm(left)
    sec_pr = sec._sectPr
    if sec_pr.find(_q("w:bidi")) is None:
        sec_pr.append(_el("w:bidi"))
    normal = doc.styles["Normal"]
    normal.font.name = font
    normal.font.size = Pt(st.get("head_pt", 9))
    rpr = normal.element.get_or_add_rPr()
    rf = rpr.find(_q("w:rFonts"))
    if rf is None:
        rf = _el("w:rFonts")
        rpr.insert(0, rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs"):
        rf.set(_q(a), font)
    _set_child(rpr, "w:szCs", **{"w:val": int(st.get("head_pt", 9) * 2)})
    _set_child(rpr, "w:lang", **{"w:bidi": "ar-DZ"})
    head_pt = float(st.get("head_pt", 9))
    center_pt = float(st.get("center_pt", 10))

    def para(container, text, align="center", size=head_pt, bold=False, underline=False):
        p = container.add_paragraph() if hasattr(container, "add_paragraph") else container
        rtl_paragraph(p, align)
        for i, line in enumerate((text or "").split("\n")):
            r = p.add_run(line)
            style_run(r, size, bold, font, underline)
            if i < len((text or "").split("\n")) - 1:
                r.add_break()
        return p

    # الرأس
    first = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
    para(first, _ar_fields(raw.get("republic", "")), "center", head_pt + 1, True)
    ht = doc.add_table(rows=1, cols=3)
    _table_rtl(ht, borders=False)
    c_r, c_c, c_l = ht.rows[0].cells           # مع bidiVisual: الخانة الأولى على اليمين
    para(c_r.paragraphs[0], _ar_fields(raw.get("right_block", "")), "right", head_pt, True)
    para(c_c.paragraphs[0], _ar_fields(raw.get("center_block", "")), "center", center_pt, True)
    left = _ar_fields(raw.get("approval", ""))
    left = (left + "\n\n" if left else "") + _ar_fields(raw.get("left_block", ""))
    para(c_l.paragraphs[0], left, "left", head_pt, True)
    doc.add_paragraph()

    # جدول الحصص
    n = len(periods)
    t = doc.add_table(rows=1 + WORK_DAYS, cols=1 + n)
    t.style = "Table Grid"
    _table_rtl(t)
    hdr = t.rows[0].cells
    _cell_text(hdr[0], [(GRID_CORNER, {"size": head_pt, "bold": True})])
    _shade(hdr[0], "#D9E2F3")
    for k, p in enumerate(periods):
        _cell_text(hdr[k + 1], [(p[0], {"size": head_pt, "bold": True}),
                                (f"{O.hm(p[1])} - {O.hm(p[2])}", {"size": head_pt - 1.5, "bold": False})])
        _shade(hdr[k + 1], "#D9E2F3")
    for d in range(WORK_DAYS):
        row = t.rows[d + 1]
        _cell_text(row.cells[0], [(DAY_NAMES[d], {"size": head_pt + 0.5, "bold": True})])
        _shade(row.cells[0], "#F2F2F2")
        for k in range(n):
            _cell_text(row.cells[k + 1], [(" ", {"size": float(st.get("title_pt", 8.5)), "bold": True})])
        for c in row.cells:
            _set_child(c._tc.get_or_add_tcPr(), "w:vAlign", **{"w:val": "center"})
        row.height = Mm(17)
    t.rows[0].cells[0].width = Mm(22)

    # الملاحظة والتوقيعات
    note = _ar_fields(raw.get("note", ""))
    if note:
        para(doc, note, "right", head_pt - 0.5, False)
    created = _ar_fields(raw.get("created", ""))
    if created:
        para(doc, created, "right", head_pt - 2, False)
    st_ = doc.add_table(rows=1, cols=3)
    _table_rtl(st_, borders=False)
    for cell, key in zip(st_.rows[0].cells, ("sign_right", "sign_center", "sign_left")):
        para(cell.paragraphs[0], _ar_fields(raw.get(key, "")), "center", head_pt + 0.5, True, True)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


# ====================================================================== الفحص
def _all_paragraphs(doc):
    def walk(container):
        for p in container.paragraphs:
            yield p
        for t in getattr(container, "tables", []):
            for row in t.rows:
                for cell in row.cells:
                    yield from walk(cell)
    yield from walk(doc)
    for s in doc.sections:
        for part in (s.header, s.footer, s.first_page_header, s.first_page_footer):
            try:
                if part is not None and not part.is_linked_to_previous:
                    yield from walk(part)
            except Exception:
                continue


def _day_index(text: str) -> int | None:
    t = (text or "").strip()
    for i, d in enumerate(DAY_NAMES):
        if t == d or t.startswith(d):
            return i
    return None


def find_grid(doc):
    """جدول الحصص: أول جدول عموده الأول فيه اسم يوم واحد على الأقل وفيه عمود حصة واحد على الأقل."""
    for t in doc.tables:
        try:
            if len(t.columns) < 2 or len(t.rows) < 2:
                continue
            days = [_day_index(r.cells[0].text) for r in t.rows[1:]]
        except Exception:
            continue
        if any(d is not None for d in days):
            return t
    return None


def validate(data: bytes) -> tuple[list[str], list[str]]:
    """(أخطاء تمنع الاستيراد، ملاحظات)."""
    from docx import Document
    try:
        doc = Document(io.BytesIO(data))
    except Exception:
        return ["الملف ليس ملف Word صالحاً (docx)."], []
    errors, notes = [], []
    if find_grid(doc) is None:
        errors.append(f"لا يوجد جدول الحصص: جدول عموده الأول أسماء الأيام ({DAY_NAMES[0]}، {DAY_NAMES[1]}…).")
    bad = set()
    for p in _all_paragraphs(doc):
        for m in FIELD_RE.finditer(p.text):
            if m.group(1).strip() not in FIELDS:
                bad.add(m.group(1))
    for b in sorted(bad):
        errors.append(f"حقل غير معروف: {{{b}}} — الحقول المتاحة: " + "، ".join("{" + k + "}" for k in FIELDS))
    return errors, notes


# ====================================================================== الملء
def _replace_in_paragraph(p, values: dict) -> None:
    """يستبدل الحقول حتى لو قسّمها Word على عدة مقاطع (runs)، مع الإبقاء على تنسيق أول مقطع."""
    text = p.text
    if "{" not in text:
        return
    runs = p.runs
    if not runs:
        return
    spans, pos = [], 0
    for r in runs:
        spans.append((pos, pos + len(r.text)))
        pos += len(r.text)
    if pos != len(text):                # نص خارج المقاطع (روابط…): استبدال بسيط في كل مقطع
        for r in runs:
            r.text = FIELD_RE.sub(lambda m: str(values.get(m.group(1).strip(), m.group(0))), r.text)
        return
    for m in reversed(list(FIELD_RE.finditer(text))):
        key = m.group(1).strip()
        if key not in values:
            continue
        a, b = m.span()
        idx = [i for i, (s, e) in enumerate(spans) if s < b and e > a]
        if not idx:
            continue
        i0, i1 = idx[0], idx[-1]
        s0 = spans[i0][0]
        s1 = spans[i1][0]
        t0 = runs[i0].text
        t1 = runs[i1].text
        new0 = t0[:a - s0] + str(values[key]) + (t1[b - s1:] if i0 == i1 else "")
        if i0 != i1:
            runs[i1].text = t1[b - s1:]
            for k in range(i0 + 1, i1):
                runs[k].text = ""
        runs[i0].text = new0


def field_values(sheet) -> dict:
    v = sheet.values
    out = {ar: v.get(en, "") for ar, en in FIELDS.items()}
    out["القسم"] = v.get("section") or v.get("target", "")
    return {k: ("" if x is None else x) for k, x in out.items()}


def _delete_column(table, idx: int):
    grid = table._tbl.tblGrid
    cols = grid.findall(_q("w:gridCol"))
    if idx < len(cols):
        grid.remove(cols[idx])
    for row in table.rows:
        tcs = row._tr.findall(_q("w:tc"))
        if idx < len(tcs):
            row._tr.remove(tcs[idx])


def _add_column(table, src_idx: int):
    grid = table._tbl.tblGrid
    cols = grid.findall(_q("w:gridCol"))
    grid.append(copy.deepcopy(cols[min(src_idx, len(cols) - 1)]))
    for row in table.rows:
        tcs = row._tr.findall(_q("w:tc"))
        row._tr.append(copy.deepcopy(tcs[min(src_idx, len(tcs) - 1)]))


def fill(sheet, data: bytes, color: bool = False):
    """يملأ قالباً بورقة قسم (official.Sheet). يعيد Document."""
    from docx import Document
    doc = Document(io.BytesIO(data))
    vals = field_values(sheet)
    grid = find_grid(doc)
    grid_cells = set()
    if grid is not None:
        for row in grid.rows:
            for c in row.cells:
                grid_cells.add(id(c._tc))
    for p in _all_paragraphs(doc):
        _replace_in_paragraph(p, vals)
    if grid is None:
        raise TemplateError("القالب بلا جدول حصص.")
    # الأعمدة حسب حصص القسم
    n = len(sheet.periods)
    have = len(grid.columns) - 1
    while have > n and have > 1:
        _delete_column(grid, have)
        have -= 1
    while have < n:
        _add_column(grid, have)
        have += 1
    hdr = grid.rows[0].cells
    for k, (lab, tm) in enumerate(sheet.periods):
        _cell_text(hdr[k + 1], [(lab, {"bold": True}), (tm, {"bold": False})])
    # الأسطر حسب الأيام: الموجودة في القالب، وتُضاف أيام فيها حصص (الجمعة/السبت)
    rows = {}
    for row in grid.rows[1:]:
        d = _day_index(row.cells[0].text)
        if d is not None and d not in rows:
            rows[d] = row
    need = sorted({c.day for c in sheet.cells} - set(rows))
    for d in need:
        last = grid.rows[-1]
        new_tr = copy.deepcopy(last._tr)
        last._tr.addnext(new_tr)
        from docx.table import _Row
        row = _Row(new_tr, grid)
        _cell_text(row.cells[0], [(DAY_NAMES[d], {"bold": True})])
        for c in row.cells[1:]:
            _cell_text(c, [(" ", {})])
        rows[d] = row
    # أيام أكثر من القالب (الجمعة/السبت): تُقصَّر الأسطر حتى تبقى الورقة صفحة واحدة
    base_n = len(rows) - len(need)
    if need and base_n > 0:
        k = base_n / len(rows)
        for row in rows.values():
            trPr = row._tr.find(_q("w:trPr"))
            hgt = trPr.find(_q("w:trHeight")) if trPr is not None else None
            if hgt is not None and hgt.get(_q("w:val")):
                hgt.set(_q("w:val"), str(max(400, int(int(hgt.get(_q("w:val"))) * k))))
    # الخانات: المادة (غامق) والأستاذ والقاعة؛ الحصة الطويلة تُدمج على أعمدتها
    for c in sorted(sheet.cells, key=lambda c: (c.day, -c.c0)):
        row = rows.get(c.day)
        if row is None:
            continue
        cells = row.cells
        a, b = c.c0 + 1, c.c1 + 1
        if b >= len(cells):
            continue
        cell = cells[a].merge(cells[b]) if b > a else cells[a]
        lines = [(c.title, {"bold": True})]
        if c.sub:
            lines.append((c.sub, {"bold": False}))
        if c.corner:
            lines.append((c.corner, {"bold": False}))
        if c.note:
            lines.append((c.note, {"bold": False}))
        _cell_text(cell, lines)
        if color and c.color:
            _shade(cell, c.color)
    return doc


def fill_to(db: Database, sheet, path: str | Path, color: bool = False) -> Path:
    data, _src = effective(db, sheet.target_id)
    doc = fill(sheet, data, color)
    path = Path(path)
    doc.save(str(path))
    return path


# ====================================================================== دمج عدة ملفات في ملف واحد
def merge(paths: list[Path], out: Path) -> Path:
    """ملف واحد: الأول كما هو، ثم كل ملف في صفحة جديدة (مع نقل الصور)."""
    from docx import Document
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    if not paths:
        raise TemplateError("لا توجد ملفات للدمج.")
    master = Document(str(paths[0]))
    body = master.element.body
    sect = body.find(_q("w:sectPr"))
    for pth in paths[1:]:
        src = Document(str(pth))
        els = [el for el in src.element.body if el.tag != _q("w:sectPr")]
        if els and els[0].tag == _q("w:p"):
            # «صفحة جديدة قبل» على أول فقرة: لا فقرة فارغة إضافية قد تنتقل وحدها إلى صفحة بيضاء
            first = copy.deepcopy(els[0])
            pPr = first.find(_q("w:pPr"))
            if pPr is None:
                pPr = _el("w:pPr")
                first.insert(0, pPr)
            if pPr.find(_q("w:pageBreakBefore")) is None:
                pPr.insert(0, _el("w:pageBreakBefore"))
            news = [first] + [copy.deepcopy(e) for e in els[1:]]
        else:
            brk = _el("w:p")
            r = _el("w:r")
            r.append(_el("w:br", **{"w:type": "page"}))
            brk.append(r)
            news = [brk] + [copy.deepcopy(e) for e in els]
        for new in news:
            for blip in new.iter(_q("a:blip")):
                rid = blip.get(_q("r:embed"))
                if rid and rid in src.part.rels:
                    img = src.part.rels[rid].target_part
                    blip.set(_q("r:embed"), master.part.relate_to(img, RT.IMAGE))
            if sect is not None:
                sect.addprevious(new)
            else:
                body.append(new)
    master.save(str(out))
    return out
