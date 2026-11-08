"""النسخة الخفيفة (ويندوز 7): تعمل على نفس البيانات، وبلا OR-Tools.

تُشغَّل هنا بـ PySide6 عبر طبقة التوافق؛ على ويندوز 7 تُبنى بـ PySide2 (Qt 5).
"""
import sys

from conftest import START

from dpp.utils import week_start


def _win(db):
    from dpp_lite.app import build_app
    from dpp_lite.window import LiteWindow
    app = build_app([])
    win = LiteWindow(db)
    win.resize(1200, 760)
    win.show()
    app.processEvents()
    win.goto_week(week_start(START))
    app.processEvents()
    return app, win


def test_lite_opens_same_database(seeded):
    """تفتح قاعدة النسخة الكاملة وتعرض تكويناتها وأقسامها وموادها."""
    db, ids = seeded
    app, win = _win(db)
    assert win.cb_form.count() >= 1
    assert win.cb_sec.count() >= 1
    assert win.tray.count() > 0
    assert "الأسبوع" in win.lb_week.text()
    win.close()


def test_lite_place_move_resize_delete(seeded):
    """الدورة الكاملة لإعداد الجدول يدوياً، والتعديلات تُحفظ في قاعدة البيانات."""
    db, ids = seeded
    app, win = _win(db)
    sec = win.cb_sec.currentData()
    items = win.grid.subject_items(sec)
    assert items
    win.view.armed = items[0]
    day = win.view.days[0]
    win.view._place(day, 540, 660)
    win.on_changed()
    cards = [c for c in win.view.cards() if c.start == 540]
    assert len(cards) == 1
    card = cards[0]
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE id=?", (card.sid,), 0) == 1

    win.grid.move(card, day, 660, 780)                       # نقل
    win.on_changed()
    moved = [c for c in win.view.cards() if c.start == 660]
    assert len(moved) == 1 and moved[0].end == 780

    win.grid.resize(moved[0], 660, 720)                      # تقصير
    win.on_changed()
    assert [c for c in win.view.cards() if c.start == 660][0].minutes == 60

    sid = [c for c in win.view.cards() if c.start == 660][0].sid
    win.grid.delete(sid)
    win.on_changed()
    assert db.scalar("SELECT COUNT(*) FROM sessions WHERE id=?", (sid,), 0) == 0
    win.close()


def test_lite_undo_redo(seeded):
    db, ids = seeded
    app, win = _win(db)
    sec = win.cb_sec.currentData()
    win.view.armed = win.grid.subject_items(sec)[0]
    before = len(win.view.cards())
    win.view._place(win.view.days[1], 480, 600)
    win.on_changed()
    assert len(win.view.cards()) == before + 1
    win.undo()
    assert len(win.view.cards()) == before
    win.redo()
    assert len(win.view.cards()) == before + 1
    win.close()


def test_lite_pdf_export(seeded, tmp_path):
    from dpp_lite.qt import QPrinter, set_landscape
    db, ids = seeded
    app, win = _win(db)
    win.view.armed = win.grid.subject_items(win.cb_sec.currentData())[0]
    win.view._place(win.view.days[0], 480, 600)
    win.on_changed()
    out = tmp_path / "lite.pdf"
    pr = QPrinter(QPrinter.HighResolution)
    set_landscape(pr)
    pr.setOutputFormat(QPrinter.PdfFormat)
    pr.setOutputFileName(str(out))
    win._render(pr)
    assert out.exists() and out.stat().st_size > 1000
    win.close()


def test_lite_does_not_import_ortools(seeded):
    """لا OR-Tools في النسخة الخفيفة: لا توجد لها عجلات 32 بت أصلاً."""
    for m in [k for k in sys.modules if k.split(".")[0] == "ortools"]:
        del sys.modules[m]
    db, _ids = seeded
    app, win = _win(db)
    win.view.armed = win.grid.subject_items(win.cb_sec.currentData())[0]
    win.view._place(win.view.days[0], 480, 540)
    win.on_changed()
    assert not [k for k in sys.modules if k.split(".")[0] == "ortools"]
    win.close()


def test_lite_selftest_runs(monkeypatch, tmp_path):
    """الفحص الذاتي للنسخة الخفيفة — نفس الذي يُشغَّل داخل DPP-Lite.exe."""
    from dpp_lite.app import selftest
    monkeypatch.setenv("DPP_DATA_DIR", str(tmp_path))
    assert selftest() == 0
