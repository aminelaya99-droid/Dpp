"""الإصدار 1.9: محرر نصوص الورقة، القوالب الافتراضية لكل قسم، أزرار الرموز، ثيم «ورقي دافئ»."""
from __future__ import annotations

from datetime import timedelta

from conftest import START

from dpp.exporters import layout as L
from dpp.exporters import official as O
from dpp.scheduler.engine import Scheduler
from dpp.services import timetables as T


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def _week(db, ids):
    res = Scheduler(db, time_limit=10).schedule_week(ids["formation"], START)
    return T.save_result(db, ids["formation"], res)


def _wait(ms=40):
    from PySide6.QtTest import QTest
    QTest.qWait(ms)


# ------------------------------------------------------------------ محرر نصوص الورقة: النموذج
def test_field_style_model():
    assert L.field_class("cell:2:1:title") == "cls:title" and L.field_class("cell:0:0:sub") == "cls:sub"
    assert L.field_class("day:3") == "cls:day" and L.field_class("ph:1:time") == "cls:ph_time"
    assert L.field_class("center_block") is None
    assert L.is_stylable("republic") and L.is_stylable("cell:0:0:corner") and not L.is_stylable("box:1")
    lay = L.effective_default()
    # نص مفرد: شكل + إزاحة + حيّز
    L.set_field_style(lay, "center_block", underline=True, size=15, dx=-4.0, w=180.0)
    assert L.field_style(lay, "center_block") == {"underline": True, "size": 15, "dx": -4.0, "w": 180.0}
    # نص من الجدول: يُحفظ كصنف، بلا إزاحة ولا حيّز
    L.set_field_style(lay, "cell:1:0:title", bold=False, dx=9.0, w=50.0)
    assert lay["field_styles"]["cls:title"] == {"bold": False}
    assert L.field_style(lay, "cell:4:2:title") == {"bold": False}
    # خانة بعينها: فوق الصنف، وفي مخزن الأسبوع لا في القالب
    L.set_field_style(lay, "cell:1:0:title", cell_only=True, color="#0B5394")
    assert lay["cell_styles"] == {"cell:1:0:title": {"color": "#0B5394"}}
    assert L.field_style(lay, "cell:1:0:title") == {"bold": False, "color": "#0B5394"}
    assert L.field_style(lay, "cell:4:2:title") == {"bold": False}
    # None يحذف الخاصية، والإرجاع إلى الأصل يحذف الكل
    L.set_field_style(lay, "center_block", size=None)
    assert "size" not in lay["field_styles"]["center_block"]
    L.clear_field_style(lay, "center_block")
    assert "center_block" not in lay["field_styles"]
    L.clear_field_style(lay, "cell:1:0:title", cell_only=True)
    assert not lay["cell_styles"]


def test_field_styles_inherit_and_reset_across_scopes(seeded):
    db, ids = seeded
    sec = ids["sections"][0]
    lvl = db.scalar("SELECT level_id FROM sections WHERE id=?", (sec,))
    lay, _ = L.effective(db, "section", lvl, sec)
    L.set_field_style(lay, "center_block", underline=True, size=15)
    L.set_field_style(lay, "day:0", color="#14532D")
    L.set_field_style(lay, "cell:0:0:title", cell_only=True, size=13)     # لا يدخل القالب أبداً
    L.save(db, f"level:{lvl}", lay, "section", lvl, sec)
    stored = L.scope_layout(db, f"level:{lvl}")
    assert "cell_styles" not in stored
    assert stored["field_styles"] == {"center_block": {"underline": True, "size": 15}, "cls:day": {"color": "#14532D"}}
    # قسم آخر من نفس الطور يرث
    other = next(s for s in ids["sections"] if s != sec and
                 db.scalar("SELECT level_id FROM sections WHERE id=?", (s,)) == lvl)
    lay2, used = L.effective(db, "section", lvl, other)
    assert L.field_style(lay2, "center_block") == {"underline": True, "size": 15} and f"level:{lvl}" in used
    # القسم يعدّل خاصية ويُرجع أخرى إلى الأصل: لا تعود موروثة من الطور
    L.set_field_style(lay2, "center_block", size=12, underline=None)
    L.clear_field_style(lay2, "day:0")
    L.save(db, f"section:{other}", lay2, "section", lvl, other)
    lay3, _ = L.effective(db, "section", lvl, other)
    assert L.field_style(lay3, "center_block") == {"size": 12}
    assert L.field_style(lay3, "day:3") == {}
    # والقسم الأول باقٍ على قالب الطور
    lay4, _ = L.effective(db, "section", lvl, sec)
    assert L.field_style(lay4, "center_block") == {"underline": True, "size": 15}
    assert L.field_style(lay4, "day:3") == {"color": "#14532D"}


def test_cell_styles_belong_to_one_week(seeded):
    db, ids = seeded
    _week(db, ids)
    sec = ids["sections"][0]
    sh = O.build(db, "section", sec, START)
    key = f"cell:{sh.cells[0].day}:{sh.cells[0].c0}:title"
    L.save_cell_styles(db, "section", sec, START, {key: {"color": "#0B5394", "size": 13}})
    assert O.build(db, "section", sec, START).layout["cell_styles"] == {key: {"color": "#0B5394", "size": 13}}
    assert O.build(db, "section", sec, START + timedelta(days=7)).layout["cell_styles"] == {}
    assert O.build(db, "section", ids["sections"][1], START).layout["cell_styles"] == {}
    L.save_cell_styles(db, "section", sec, START, {})
    assert O.build(db, "section", sec, START).layout["cell_styles"] == {}


# ------------------------------------------------------------------ محرر نصوص الورقة: الرسم
def test_scene_applies_field_styles(seeded, tmp_path):
    db, ids = seeded
    _week(db, ids)
    _app()
    from PySide6.QtGui import QColor
    from dpp.ui.sheet_view import SheetScene, render_to_pdf
    sec = ids["sections"][0]
    sh = O.build(db, "section", sec, START)
    c0 = sh.cells[0]
    tkey = f"cell:{c0.day}:{c0.c0}:title"
    plain = SheetScene(sh, design=True)
    b0 = {t.key: t for t in plain.texts}
    base_box = b0["right_block"].box
    assert plain.field_base["center_block"]["underline"] is False and not plain.overflow
    assert set(plain.frames) >= {"republic", "right_block", "left_block", "center_block", tkey, "day:0"}
    assert plain.frames["right_block"].movable and not plain.frames[tkey].movable

    L.set_field_style(sh.layout, "center_block", underline=True, color="#7A1F1F", font="DejaVu Sans")
    L.set_field_style(sh.layout, "right_block", dx=-20.0, dy=6.0, w=120.0, align="left")
    L.set_field_style(sh.layout, tkey, italic=False, size=14)                    # الصنف: كل أسماء المواد
    L.set_field_style(sh.layout, tkey, cell_only=True, color="#0B5394")          # هذه الخانة فقط
    sc = SheetScene(sh, design=True)
    by = {t.key: t for t in sc.texts}
    assert by["center_block"].font().underline() and by["center_block"].defaultTextColor() == QColor("#7A1F1F")
    assert by["center_block"].font().families()[0] == "DejaVu Sans"
    rb = by["right_block"].box
    assert abs(rb.x() - (base_box.x() - 20)) < 0.01 and abs(rb.y() - (base_box.y() + 6)) < 0.01
    assert abs(rb.width() - 120) < 0.01
    titles = [t for t in sc.texts if t.key.endswith(":title")]
    assert titles and all(not t.font().italic() for t in titles)
    assert all(t.defaultTextColor() == QColor("#0B5394") for t in titles if t.key == tkey)
    assert all(t.defaultTextColor() == QColor("#000000") for t in titles if t.key != tkey)
    # الأصل محفوظ للإرجاع، والإطارات لا تُطبع
    assert sc.field_base[tkey]["italic"] == plain.field_base[tkey]["italic"]
    out = render_to_pdf([sc], str(tmp_path / "s.pdf"))
    assert out and (tmp_path / "s.pdf").stat().st_size > 2000
    # حيّز ضيق جداً ← تنبيه قبل الطباعة
    L.set_field_style(sh.layout, "right_block", w=40.0, h=10.0)
    assert L.field_label("right_block") in SheetScene(sh).overflow


def test_field_styles_reach_excel(seeded, tmp_path):
    import openpyxl
    db, ids = seeded
    _week(db, ids)
    sh = O.build(db, "section", ids["sections"][0], START)
    L.set_field_style(sh.layout, "republic", underline=True, font="Tahoma", size=16, color="#7A1F1F", align="right")
    L.set_field_style(sh.layout, "day:0", bold=False)
    c0 = sh.cells[0]
    L.set_field_style(sh.layout, f"cell:{c0.day}:{c0.c0}:title", cell_only=True, italic=False, size=9)
    O.to_xlsx([sh], tmp_path / "s.xlsx")
    ws = openpyxl.load_workbook(tmp_path / "s.xlsx").worksheets[0]
    f = ws.cell(1, 1).font
    assert (f.name, f.size, f.underline, f.bold) == ("Tahoma", 16, "single", True) and f.color.rgb.endswith("7A1F1F")
    assert ws.cell(1, 1).alignment.horizontal == "right"
    assert ws.cell(5, 1).font.bold is False and ws.cell(6, 1).font.bold is False
    cf = ws.cell(5 + c0.day, c0.c0 + 2).font
    assert cf.size == 9 and cf.italic is False


# ------------------------------------------------------------------ محرر نصوص الورقة: الواجهة
def test_preview_text_editor_flow(seeded, monkeypatch):
    db, ids = seeded
    _week(db, ids)
    _app()
    from dpp.ui import sheet_design as SD
    from dpp.ui import sheet_view as SV
    secs = ids["sections"][:2]
    dlg = SV.PreviewDialog(db, [O.build(db, "section", s, START) for s in secs])
    dlg.b_design.setChecked(True)
    d = dlg.design
    sc = dlg.cur_scene()
    # تحديد نص مفرد ← اللوحة تعرض خصائصه مع الإزاحة والحيّز
    sc.frames["center_block"].setSelected(True)
    assert d.field_key == "center_block" and d.currentIndex() == 1
    assert not d.off_w.isHidden() and not d.geo_w.isHidden() and not d.cell_only.isEnabled()
    d.set_field(underline=True, size=15)
    _wait()                                                               # إعادة الرسم مؤجلة (QTimer)
    sh = dlg.cur_sheet()
    assert sh.layout["field_styles"]["center_block"] == {"underline": True, "size": 15} and dlg.is_dirty()
    assert dlg.cur_scene().frames["center_block"].isSelected()            # التحديد يبقى بعد إعادة الرسم
    assert d.under.isChecked() and d.size.value() == 15
    # السحب والأسهم ← إزاحة
    dlg._field_moved("center_block", {"dx": -12.0, "dy": 3.0})
    _wait()
    assert sh.layout["field_styles"]["center_block"]["dx"] == -12.0 and d.f_dx.value() == -12.0
    d.f_w.setValue(150.0)
    _wait()
    assert sh.layout["field_styles"]["center_block"]["w"] == 150.0
    dlg.undo()
    assert "w" not in sh.layout["field_styles"]["center_block"]
    dlg.redo()
    _wait()
    # نص من الجدول ← صنف (بلا إزاحة)، ثم «هذه الخانة فقط»
    sc = dlg.cur_scene()
    tkey = next(k for k in sc.frames if k.endswith(":title"))
    sc.clearSelection()
    sc.frames[tkey].setSelected(True)
    assert d.field_key == tkey and d.off_w.isHidden() and d.cell_only.isEnabled()
    d.set_field(bold=False)
    _wait()
    assert sh.layout["field_styles"]["cls:title"] == {"bold": False}
    d.cell_only.setChecked(True)
    d.set_field(color="#0B5394")
    _wait()
    assert sh.layout["cell_styles"] == {tkey: {"color": "#0B5394"}}
    assert "color" not in sh.layout["field_styles"]["cls:title"]
    # الاختيار من القائمة يحدد أول نص من الصنف
    i = d.field_pick.findData("cls:day")
    d.field_pick.setCurrentIndex(i)
    d.field_pick.activated.emit(i)
    _wait(60)
    assert L.field_class(d.field_key) == "cls:day"
    # الإرجاع إلى الأصل
    d.cell_only.setChecked(False)
    dlg.cur_scene().clearSelection()
    dlg.cur_scene().frames["center_block"].setSelected(True)
    d.reset_field()
    assert "center_block" not in sh.layout["field_styles"]
    d.set_field(italic=True)
    _wait()
    # الحفظ في قالب الطور: الأصناف والنصوص في القالب، وخانة الأسبوع مع ورقتها
    monkeypatch.setattr(SD, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(SD, "info", lambda *a, **k: None)
    d.sync()
    for b in d.scope_btns.buttons():
        b.setChecked(b.property("scope") == f"level:{sh.level_id}")
    d.save_scope()
    again = O.build(db, "section", secs[0], START)
    assert again.layout["field_styles"] == {"cls:title": {"bold": False}, "center_block": {"italic": True}}
    assert again.layout["cell_styles"] == {tkey: {"color": "#0B5394"}}
    nxt = O.build(db, "section", secs[0], START + timedelta(days=7))
    assert nxt.layout["field_styles"] == again.layout["field_styles"] and nxt.layout["cell_styles"] == {}
    dlg.b_save.setEnabled(False)
    dlg.close()
