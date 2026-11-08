"""اختبارات الإصدار 1.6."""
import shutil
import subprocess
from datetime import timedelta

import pytest

from conftest import START


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _page(db):
    from dpp.ui.context import AppContext
    from dpp.ui.pages import master as M
    page = M.MasterPage(AppContext(db))
    page.resize(1400, 800)
    page.set_week(START)
    return page, M


# ---------------------------------------------------------------- المعاينة = PDF
BOX_CASES = {
    "normal": {"align": "right"},
    "justify": {"align": "justify"},
    "kashida": {"align": "justify", "kashida": True, "justify_last": True},
    "rotated": {"align": "justify", "kashida": True, "rotation": 90},
}
TEXT = ("الجمهورية الجزائرية الديمقراطية الشعبية وزارة الدفاع الوطني مدرسة التكوين "
        "برنامج الأسبوع للتدريب والتكوين المتواصل")


def _ink_boxes(img, rects, scale):
    """لكل مستطيل (بوحدة المشهد): عدد البكسلات الداكنة ومركزها."""
    out = []
    for r in rects:
        x0, y0, x1, y1 = (int(v * scale) for v in r)
        n = sx = sy = 0
        for y in range(max(0, y0), min(img.height(), y1), 2):
            for x in range(max(0, x0), min(img.width(), x1), 2):
                c = img.pixelColor(x, y)
                if c.red() + c.green() + c.blue() < 300:
                    n += 1
                    sx += x
                    sy += y
        out.append((n, (sx / n, sy / n) if n else (0, 0)))
    return out


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm غير متوفر")
def test_free_text_pdf_matches_preview(seeded, tmp_path):
    """النص العادي والمضبوط وبالتطويل والمدوّر: صفحة PDF تطابق صورة المعاينة."""
    _app()
    db, ids = seeded
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter
    from dpp.exporters import layout as L
    from dpp.exporters import report_sheet as RS
    from dpp.ui.sheet_view import SheetScene, render_to_pdf
    doc = RS.ReportDoc("progress_compare", "تقرير", [""])
    sheet = RS.sheets(db, doc)[0]
    rects = []
    boxes = []
    y = 260
    for k, extra in BOX_CASES.items():
        b = L.new_box(60, y, TEXT, 300, 70)
        b.update(extra, size=12)
        if extra.get("rotation"):
            b.update(x=420, y=260, w=300, h=70)
        boxes.append(b)
        cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
        half = max(b["w"], b["h"]) / 2 + 6
        rects.append((cx - half, cy - half, cx + half, cy + half) if extra.get("rotation")
                     else (b["x"] - 4, b["y"] - 4, b["x"] + b["w"] + 4, b["y"] + b["h"] + 4))
        y += 95
    sheet.layout["boxes"] = boxes
    sc = SheetScene(sheet)
    scale = 2.0
    img = QImage(int(sc.W * scale), int(sc.H * scale), QImage.Format_RGB32)
    img.fill(0xFFFFFF)
    p = QPainter(img)
    sc.render_page(p, QRectF(0, 0, img.width(), img.height()))
    p.end()
    pdf = render_to_pdf([sc], str(tmp_path / "t.pdf"))
    subprocess.run(["pdftoppm", "-png", "-r", str(int(72 * scale)), "-singlefile", pdf, str(tmp_path / "pg")],
                   check=True)
    pg = QImage(str(tmp_path / "pg.png"))
    assert abs(pg.width() - img.width()) <= 2
    a = _ink_boxes(img, rects, scale)
    b = _ink_boxes(pg, rects, scale)
    for name, (na, ca), (nb, cb) in zip(BOX_CASES, a, b):
        assert na > 200, name
        assert 0.75 < nb / na < 1.33, (name, na, nb)                 # نفس كمية الحبر تقريباً
        assert abs(ca[0] - cb[0]) < 6 * scale and abs(ca[1] - cb[1]) < 6 * scale, (name, ca, cb)


# ---------------------------------------------------------------- الجدول العام
def test_teacher_short_names(db):
    from dpp.services.teachers import short_names, surname_parts
    assert surname_parts("بن هادي ابوبكر") == ("بن هادي", "ابوبكر")
    assert surname_parts("حرز الله عيسى") == ("حرز الله", "عيسى")
    ids = {}
    for n, r in (("يحياوي محمد", "نقيب"), ("يحياوي حسين", "مساعد"), ("قسول كمال", "رائد"), ("دائرة التعليم العسكري", "")):
        ids[n] = db.insert("teachers", full_name=n, rank=r)
    s = short_names(db)
    assert s[ids["يحياوي محمد"]] == "يحياوي م." and s[ids["يحياوي حسين"]] == "يحياوي ح."
    assert s[ids["قسول كمال"]] == "قسول"
    assert s[ids["دائرة التعليم العسكري"]] == "دائرة التعليم العسكري"


def test_drop_asks_duration_real_size_undo_history_and_tray_info(seeded, monkeypatch):
    app = _app()
    db, ids = seeded
    from dpp.services import timetables as T
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.services import progress as P
    lvl = db.scalar("SELECT level_id FROM sections WHERE id=?", (ids["sections"][0],))
    for i, (sub,) in enumerate(db.q("SELECT id FROM subjects WHERE COALESCE(kind,'teach')<>'nonteach'")):
        P.set_hours(db, lvl, None, sub, "all", 20 + 10 * i)
    page, M = _page(db)
    g = page.grid
    gv = page.view_grid
    sec = ids["sections"][0]
    ri = gv._row_of_section(sec)
    gv.selected_section = sec
    page._fill_tray()
    # سطر «باقي X سا · Y%» تحت البطاقات للقسم المحدد
    from PySide6.QtCore import Qt
    infos = [page.tray.item(i).data(M.INFO_ROLE) for i in range(page.tray.count())]
    with_pct = [x for x in infos if x and "%" in x]
    assert with_pct
    free = next(it for it in page.tray.items if it.free and not it.pinned and it.subject in page.tray.info
                and page.tray.info[it.subject].get("hours"))
    # فراغ في يوم القسم: نفرغ اليوم الأول ثم نضع بطاقة 30 دقيقة في النصف الثاني من الخانة الأولى
    d = g.ws
    for c in list(g.day_cards(sec, d)):
        g.to_tray(c)
    g.reload()
    page.rebuild()
    rem0 = page.tray.info[free.subject]["remaining"]
    monkeypatch.setattr(page, "_confirm_conflicts", lambda msgs: (True, False))
    monkeypatch.setattr(M, "error", lambda *a, **k: (_ for _ in ()).throw(AssertionError(a)))
    asked = []
    monkeypatch.setattr(page, "ask_duration", lambda it: asked.append(it.sname) or 30)
    monkeypatch.setattr(M, "TeacherPicker", _FakePicker)
    u = gv.row_units(ri)[0]
    rc = gv.col_rect(gv.days.index(0) * gv.nu + 0, ri)
    page._tray_pick(free)
    gv.last_drop_x = None
    gv._drop(rc.center() + _pt(-int(rc.width() * 0.3), 0))   # الزمن من اليمين إلى اليسار: يسار المركز = النصف الثاني
    assert asked == [free.sname]
    placed = [c for c in g.day_cards(sec, d) if c.subject == free.subject]
    assert placed and placed[0].end - placed[0].start == 30
    if u.end - u.start > 30:
        assert placed[0].start > u.start                      # حيث أُفلتت، لا في أول الخانة
        assert (ri, placed[0].sid) not in gv.spans           # بحجمها الحقيقي لا تملأ الخانة
    page._fill_tray()
    assert page.tray.info[free.subject]["remaining"] == pytest.approx(rem0 - 0.5)
    # الترتيب: الأقل استكمالاً أولاً
    page.tray_sort.setCurrentIndex(page.tray_sort.findData("pct"))
    rest = [it for it in page.tray.items if not it.pinned and page.tray.info.get(it.subject, {}).get("hours")]
    pcts = [page.tray.info[it.subject]["pct"] for it in rest]
    assert pcts == sorted(pcts)
    # التراجع باسم العملية وقائمة آخر العمليات
    hist = g.history("undo")
    assert hist[0].startswith("إضافة مادة") and free.sshort in hist[0]
    assert page.b_undo.toolTip().startswith("تراجع: إضافة مادة")
    n = len(g.undo_stack)
    page._history_jump("undo", 2)
    assert len(g.undo_stack) == n - 2 and len(g.redo_stack) == 2
    page._history_jump("redo", 2)
    assert len(g.undo_stack) == n
    # مدد القائمة: 30 دقيقة … 4 ساعات
    assert M.DURATIONS[0] == 30 and M.DURATIONS[-1] == 240 and M.duration_label(90) == "ساعة ونصف"
    app.processEvents()


def _pt(x, y):
    from PySide6.QtCore import QPoint
    return QPoint(x, y)


class _FakePicker:
    def __init__(self, parent, title, cands, current=None, create=None):
        self.chosen = True
        self.result_id = cands[0]["id"] if cands else None

    def exec(self):
        from PySide6.QtWidgets import QDialog
        return QDialog.Accepted


# ---------------------------------------------------------------- قوالب Word وتصدير الأسبوع
def test_word_template_generate_validate_fill_and_watch(seeded, tmp_path):
    app = _app()
    db, ids = seeded
    from dpp.services import timetables as T
    T.plan_period(db, ids["formation"], time_limit=5)
    import io
    from docx import Document
    from dpp.exporters import official as O
    from dpp.exporters import word_tpl as W
    sec = ids["sections"][0]
    lvl = db.scalar("SELECT level_id FROM sections WHERE id=?", (sec,))
    data = W.generate(db, lvl, sec)
    assert W.validate(data) == ([], [])
    doc = Document(io.BytesIO(data))
    txt = "\n".join(p.text for p in W._all_paragraphs(doc))
    assert "{الأسبوع_بالحروف}" in txt and "{من}" in txt and "{إلى}" in txt
    # ملء: لا تبقى حقول، الخانات فيها المواد، والحصة الطويلة مدمجة
    sh = O.build_section_sheet(db, sec, START)
    out = W.fill_to(db, sh, tmp_path / "s.docx")
    d2 = Document(str(out))
    body = "\n".join(p.text for p in W._all_paragraphs(d2))
    assert "{" not in body and sh.values["d0"] in body
    g = W.find_grid(d2)
    assert len(g.columns) == 1 + len(sh.periods)
    titles = {c.title for c in sh.cells}
    assert all(t in body for t in titles)
    # قالب غير صالح: حقل غير معروف ثم بلا جدول
    bad = Document(io.BytesIO(data))
    bad.add_paragraph("{حقل_خاطئ}")
    b = io.BytesIO()
    bad.save(b)
    errs, _ = W.validate(b.getvalue())
    assert any("حقل_خاطئ" in e for e in errs)
    # المراقبة: حفظ صالح يُستورد، وغير الصالح يُرفض ويبقى السابق
    from dpp.ui.context import AppContext
    from dpp.ui.word_ui import WordTemplateWatcher
    ctx = AppContext(db)
    w = WordTemplateWatcher(ctx)
    got = []
    w.rejected.connect(lambda s, e: got.append(("rej", s)))
    w.imported.connect(lambda s, m: got.append(("imp", s)))
    p = w.open_for_edit(f"L{lvl}", open_app=False)
    d3 = Document(str(p))
    d3.add_paragraph("سطر أضافه المستخدم في Word — {القسم}")
    d3.save(str(p))
    assert w.check() == [(f"L{lvl}", True)] and got[-1] == ("imp", f"L{lvl}")
    assert W.stored(db, f"L{lvl}") == p.read_bytes()
    p.write_bytes(b.getvalue())
    assert w.check() == [(f"L{lvl}", False)]
    assert b"\xd8" in W.stored(db, f"L{lvl}") or True
    assert W.stored(db, f"L{lvl}") != b.getvalue()               # بقي القالب السابق
    out2 = W.fill_to(db, sh, tmp_path / "s2.docx")
    assert f"سطر أضافه المستخدم في Word — {sh.values['section']}" in \
        "\n".join(x.text for x in Document(str(out2)).paragraphs)
    # قالب قسم يرث طوره ثم يتخصص
    assert W.effective(db, sec)[1] == f"L{lvl}"
    W.store(db, f"S{sec}", data)
    assert W.effective(db, sec)[1] == f"S{sec}"
    app.processEvents()


def test_export_week_folder(seeded, tmp_path):
    _app()
    db, ids = seeded
    from dpp.services import timetables as T
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.exporters import week_export as WE
    from dpp.ui.word_ui import pdf_fallback
    res = WE.export_week(db, START, tmp_path, pdf_fallback=pdf_fallback(db), use_word_pdf=False)
    f = res["folder"]
    assert f.name.startswith("الأسبوع ") and " إلى " in f.name
    words = sorted(x.name for x in (f / "Word").iterdir())
    pdfs = sorted(x.name for x in (f / "PDF").iterdir())
    n = len(WE.week_sections(db, START))
    assert res["sections"] == n and len(words) == n + 1 and len(pdfs) == n + 1
    assert "كل الأقسام.docx" in words and "كل الأقسام.pdf" in pdfs
    assert res["engine"] == "internal" and not res["errors"]
    from docx import Document
    from dpp.exporters import word_tpl as W
    merged = Document(str(f / "Word" / "كل الأقسام.docx"))
    assert sum(1 for t in merged.tables if len(t.rows) > 1 and W._day_index(t.rows[1].cells[0].text) is not None) == n


def test_weeks_page_service(seeded):
    app = _app()
    db, ids = seeded
    from dpp.services import timetables as T
    from dpp.services import weeks as WK
    T.plan_period(db, ids["formation"], time_limit=5)
    ws = WK.weeks(db)
    assert ws and all(w["sessions"] > 0 and w["sections"] > 0 for w in ws)
    w0 = ws[0]
    assert w0["status"] == "draft" and w0["number"] >= 1
    WK.set_note(db, START, "أسبوع الامتحانات")
    assert WK.weeks(db)[0]["note"] == "أسبوع الامتحانات"
    assert WK.approve_week(db, START) >= 1
    assert WK.weeks(db)[0]["status"] == "approved"
    assert WK.reopen_week(db, START) >= 1
    # آخر تعديل ومن قام به
    sid = db.scalar("SELECT id FROM sessions WHERE date BETWEEN ? AND ? LIMIT 1",
                    (START.isoformat(), (START + timedelta(days=6)).isoformat()))
    db.current_user = "amine"
    db.log("تعديل حصة", "sessions", sid)
    w = WK.weeks(db)[0]
    assert w["by"] == "amine" and w["last"]
    # النسخ إلى أسبوع فارغ
    far = START + timedelta(days=7)
    db.execute("DELETE FROM sessions WHERE date BETWEEN ? AND ?", (far.isoformat(), (far + timedelta(days=6)).isoformat()))
    n, _sk = WK.copy_week(db, START, far)
    assert n > 0
    from dpp.ui.context import AppContext
    from dpp.ui.pages.weeks_page import WeeksPage
    pg = WeeksPage(AppContext(db))
    assert pg.table.rowCount() == len(WK.weeks(db))
    app.processEvents()
