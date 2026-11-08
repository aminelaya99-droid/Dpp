"""تصدير أسبوع كامل للحفظ: مجلد باسم الأسبوع، فيه «Word» و«PDF»، وفي كل منهما ملف لكل قسم وملف يجمع كل الأقسام.

  الأسبوع 8 — 01-11 إلى 07-11/
      Word/  BMP2-تسخين.docx … كل الأقسام.docx
      PDF/   BMP2-تسخين.pdf  … كل الأقسام.pdf

Word من قوالب Word (القسم ← الطور ← المولَّد). PDF عبر Word المثبّت، وإلا بمحرك البرنامج الداخلي (pdf_fallback).
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from ..db.database import Database
from ..utils import iso, week_start
from . import official as O
from . import word_pdf as WP
from . import word_tpl as W

ALL_NAME = "كل الأقسام"


def week_folder_name(db: Database, ws) -> str:
    ws = week_start(ws)
    n = O.week_number(db, ws)
    we = ws + timedelta(days=6)
    return f"الأسبوع {n} — {ws.strftime('%d-%m')} إلى {we.strftime('%d-%m')}"


def week_sections(db: Database, ws, formation_ids: list[int] | None = None) -> list[int]:
    """الأقسام التي لها حصص في الأسبوع (بترتيب الأطوار والأقسام)."""
    ws = week_start(ws)
    sql = """SELECT DISTINCT sec.id FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
             JOIN groups_ g ON g.id=sg.group_id JOIN sections sec ON sec.id=g.section_id
             JOIN formations f ON f.id=sec.formation_id LEFT JOIN levels l ON l.id=sec.level_id
             WHERE s.date BETWEEN ? AND ? AND s.status NOT IN ('cancelled','tray') AND f.archived=0"""
    p: list = [iso(ws), iso(ws + timedelta(days=6))]
    if formation_ids:
        sql += f" AND sec.formation_id IN ({','.join('?' * len(formation_ids))})"
        p += list(formation_ids)
    ids = [r[0] for r in db.q(sql, p)]
    order = {r[0]: i for i, r in enumerate(db.q("""SELECT s.id FROM sections s LEFT JOIN levels l ON l.id=s.level_id
                                                   ORDER BY COALESCE(l.sort, 99), s.sort, s.id"""))}
    return sorted(ids, key=lambda i: order.get(i, 9999))


def export_week(db: Database, ws, root: str | Path, formation_ids: list[int] | None = None,
                pdf_fallback=None, progress=None, color: bool = False, use_word_pdf: bool = True) -> dict:
    """يُنشئ المجلد ويعيد ملخصاً: المجلد، عدد الأقسام، محرك PDF، الأخطاء.
    pdf_fallback(sheets, path): رسم PDF بالمحرك الداخلي (من الواجهة). progress(نص، رقم، المجموع)."""
    ws = week_start(ws)
    folder = Path(root) / W._safe(week_folder_name(db, ws))
    wdir, pdir = folder / "Word", folder / "PDF"
    wdir.mkdir(parents=True, exist_ok=True)
    pdir.mkdir(parents=True, exist_ok=True)
    secs = week_sections(db, ws, formation_ids)
    errors, docs, sheets = [], [], []
    total = len(secs) + 2
    for i, sid in enumerate(secs):
        sh = O.build_section_sheet(db, sid, ws)
        name = W._safe(sh.name)
        if progress:
            progress(f"Word: {sh.name}", i, total)
        try:
            p = W.fill_to(db, sh, wdir / f"{name}.docx", color)
            docs.append((p, pdir / f"{name}.pdf"))
            sheets.append(sh)
        except Exception as e:                       # قالب تالف لقسم: نسجل ونكمل
            errors.append(f"{sh.name}: {e}")
    if docs:
        all_docx = wdir / f"{ALL_NAME}.docx"
        try:
            W.merge([d for d, _ in docs], all_docx)
            docs_all = [(all_docx, pdir / f"{ALL_NAME}.pdf")]
        except Exception as e:
            errors.append(f"{ALL_NAME}: {e}")
            docs_all = []
    else:
        docs_all = []
    if progress:
        progress("PDF…", len(secs), total)
    engine = "word"
    pairs = docs + docs_all
    left = WP.convert(pairs, poll=(lambda: progress("PDF عبر Word…", len(secs), total)) if progress else None) \
        if use_word_pdf else list(pairs)
    if left:
        engine = "internal" if len(left) == len(pairs) else "mixed"
        by_docx = {str(d): sh for (d, _p), sh in zip(docs, sheets)}
        for d, pdf in left:
            if pdf_fallback is None:
                errors.append(f"PDF غير متاح: {Path(pdf).name}")
                continue
            try:
                if str(d) in by_docx:
                    pdf_fallback([by_docx[str(d)]], str(pdf))
                else:
                    pdf_fallback(sheets, str(pdf))
            except Exception as e:
                errors.append(f"{Path(pdf).name}: {e}")
    if progress:
        progress("تم", total, total)
    db.log("تصدير أسبوع كامل", "sessions", None, {"week": iso(ws), "folder": str(folder), "sections": len(sheets)})
    return {"folder": folder, "sections": len(sheets), "engine": engine, "errors": errors}
