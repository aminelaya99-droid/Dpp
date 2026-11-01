import json
import re

import pytest

pytest.importorskip("PySide6.QtGui")


@pytest.fixture
def app():
    from dpp.app import create_app
    return create_app([])


@pytest.fixture
def week(session, sample):
    from pathlib import Path
    from dpp.services import roz_import, planner
    roz_import.import_roz(session, sample["training"], Path(__file__).parent / "data" / "6.roz")
    return planner.get_week(session, sample["training"], 6)


def _pdf_pages(path) -> int:
    data = open(path, "rb").read()
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def test_inheritance(session, sample):
    from dpp.printing import template as tpl
    a, b = sample["a"], sample["b"]
    lay, src = tpl.effective(session, a)
    assert src == "builtin"
    d = tpl.default_layout()
    d["name"] = "عام"
    tpl.save(session, d)
    assert tpl.effective(session, a)[1] == "default"
    lv = tpl.default_layout()
    lv["page"]["orientation"] = "portrait"
    tpl.save(session, lv, level_id=sample["level"].id)
    assert tpl.effective(session, a)[1] == "level"
    sec = tpl.default_layout()
    sec["items"] = sec["items"][:2]
    tpl.save(session, sec, sample["level"].id, a.id)
    la, sa = tpl.effective(session, a)
    lb, sb = tpl.effective(session, b)
    assert (sa, sb) == ("section", "level") and len(la["items"]) == 2
    assert lb["page"]["orientation"] == "portrait"
    tpl.remove(session, sample["level"].id, a.id)
    assert tpl.effective(session, a)[1] == "level"


def test_fields_and_upgrade(session, sample, week):
    from dpp.printing import template as tpl
    from dpp.services import settings
    vals = tpl.field_values(session, sample["a"], week)
    text, missing = tpl.fill("{section} / {week} / {institution}", vals)
    assert text.startswith("BMP1-A / 6 / [") and missing == ["institution"]
    settings.put(session, "institution_name", "المدرسة")
    vals = tpl.field_values(session, sample["a"], week)
    assert tpl.missing_fields(tpl.default_layout(), vals) == []
    old = {"items": [{"type": "text", "id": "x", "x": 1, "y": 1, "w": 10, "h": 5, "text": "a"}]}
    up = tpl.upgrade(old)
    assert up["version"] == tpl.VERSION and up["items"][0]["size"] and up["page"]["size"] == "A4"


def test_table_data_and_geometry(session, sample, week, app):
    from dpp.printing import template as tpl
    from dpp.printing.render import build_table_data, table_geometry
    data = build_table_data(sample["a"], week)
    keys = [c.key for c in data.cols]
    assert keys[0] == "08:00-09:00" and any(c.is_lunch for c in data.cols)
    assert data.days == [0, 1, 2, 3, 4]
    item = tpl.table_item(10, 35, 277, 150)
    g = table_geometry(item, data)
    assert g.cols[0][0] == "__day__" and abs(g.cols[0][2] - 287) < 1e-6
    assert abs(sum(b - a for _, a, b in g.cols) - 277) < 1e-6
    item["hidden_cols"] = [keys[-1]]
    item["hidden_days"] = [4]
    item["extra_cols"] = [{"title": "ملاحظات", "width": 30}]
    item["col_weights"] = {keys[0]: 3}
    g2 = table_geometry(item, data)
    assert len(g2.cols) == len(g.cols)  # عمود مخفي وآخر إضافي
    assert len(g2.rows) == 5
    w = {k: b - a for k, a, b in g2.cols}
    assert w[keys[0]] > w[keys[1]] * 2.5 and abs(w["__extra0__"] - 30) < 1e-6


def test_render_and_pdf(session, sample, week, app, tmp_path):
    from PySide6.QtGui import QColor, QImage, QPainter
    from dpp.printing import output
    from dpp.printing import template as tpl
    from dpp.printing.render import RenderContext, build_table_data, render_page
    lay = tpl.default_layout()
    lay["items"][4]["merges"] = [{"row": 1, "col": 1, "rows": 2, "cols": 2, "text": "نص للطباعة فقط"}]
    img = QImage(1485, 1050, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    missing = render_page(p, lay, RenderContext(tpl.field_values(session, sample["a"], week),
                                                 build_table_data(sample["a"], week)), 5.0)
    p.end()
    assert missing == ["institution"]
    # رُسم شيء غير أبيض داخل منطقة الجدول
    assert img.pixelColor(700, 400) != QColor("white") or img.pixelColor(1300, 300) != QColor("white")
    n_lessons = len(week.lessons)
    sheets = output.make_sheets(session, [sample["a"], sample["b"]], lambda sec: week)
    path = tmp_path / "out.pdf"
    output.export_pdf(session, sheets, path)
    assert path.stat().st_size > 2000 and _pdf_pages(path) == 2
    assert len(week.lessons) == n_lessons  # الطباعة لا تغير البيانات


def test_report_pagination(session, sample, app, tmp_path):
    from dpp.printing import reports
    rep = reports.structure_report(session)
    rep.rows = rep.rows * 20
    path = tmp_path / "tree.pdf"
    n = reports.export_report_pdf(session, rep, path)
    assert n == len(reports.paginate(rep, 297.0)) and n > 1
    assert _pdf_pages(path) == n


def test_editor_canvas_drag(session, sample, week, app):
    from dpp.printing import template as tpl
    from dpp.printing.render import RenderContext, build_table_data, table_geometry
    from dpp.ui.print_view import PageCanvas
    c = PageCanvas()
    lay = tpl.default_layout()
    data = build_table_data(sample["a"], week)
    c.set_data(lay, RenderContext({}, data))
    item = tpl.find_item(lay, "table")
    g = table_geometry(item, data)
    k1, k2 = g.timecols[0].key, g.timecols[1].key
    w0 = {k: b - a for k, a, b in g.cols}
    c._drag_col(item, json.loads(json.dumps(item)), ("col", k1, k2), -5.0)
    w1 = {k: b - a for k, a, b in table_geometry(item, data).cols}
    assert abs(w1[k1] - (w0[k1] + 5)) < 0.05 and abs(w1[k2] - (w0[k2] - 5)) < 0.05
    assert abs(c.snap(12.4) - 10) < 1e-9
    lay["grid"]["snap"] = False
    assert c.snap(12.43) == 12.4
