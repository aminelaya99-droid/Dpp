"""اختبارات الإصدار 1.4: البطاقات بالاسم الكامل، اقتراحات الوقت، البطاقة الجديدة، الأستاذ الجديد…"""
from datetime import date, timedelta

import pytest
from conftest import START

from dpp.services import timetables as T
from dpp.services.grid import Card, TrayItem, WeekGrid


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_subject_shades_by_family():
    _app()
    from dpp.ui.colors import family, subject_shade
    a, b = subject_shade("specialty", 1), subject_shade("specialty", 2)
    assert a.name() != b.name()                                   # كل مادة درجتها
    assert subject_shade("specialty", 7).name() == subject_shade("specialty", 7).name()   # ثابتة
    assert family("pe") == family("drill") == "military"
    m, s, g = subject_shade("military", 3), subject_shade("specialty", 3), subject_shade("general", 3)
    assert abs(m.hueF() - s.hueF()) > 0.15 and abs(s.hueF() - g.hueF()) > 0.15
    for c in (m, s, g):
        assert c.lightness() > 150                                # فاتحة: النص الداكن مقروء


def test_suggest_slots_and_new_teacher(seeded):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    g = WeekGrid(db, START, today=START)
    sec = ids["sections"][0]
    it = g.subject_items(sec)[0]
    slots = g.suggest_slots(it, sec)
    assert slots
    for sl in slots:                                              # كل اقتراح خالٍ من التعارض
        assert not g.check_free(it, sec, sl["day"], sl["start"], sl["end"], teacher=sl["teacher"])
    assert slots == sorted(slots, key=lambda x: (x["past"], x["day"], x["start"]))
    c = next(c for c in g.cards.values() if c.sections and c.kind == "teach")
    mv = g.suggest_slots(c, c.sections[0])
    assert all(not g.check_card(c, x["day"], x["start"], x["end"]) for x in mv)
    assert all(not (x["day"] == c.day and x["start"] == c.start) for x in mv)
    tid = g.create_teacher("رقيب أول: جديد الاسم", it.subject, sec)
    r = db.one("SELECT * FROM teachers WHERE id=?", (tid,))
    assert r["rank"] == "رقيب أول" and r["full_name"] == "جديد الاسم"
    assert db.scalar("SELECT 1 FROM teacher_subjects WHERE teacher_id=? AND subject_id=?", (tid, it.subject))
    cands = g.teacher_candidates(sec, it.subject)
    assert any(x["id"] == tid and x["group"] in ("qualified", "qualified_spec") for x in cands)


def test_master_cards_fill_cell_and_pins(seeded, monkeypatch):
    app = _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.ui.context import AppContext
    from dpp.ui.pages import master as M
    page = M.MasterPage(AppContext(db))
    page.resize(1400, 800)
    page.set_week(START)
    app.processEvents()
    assert page.options["full_name"] and page.color_mode() == "shade"
    gv = page.view_grid
    # البطاقة تغطي خانة الحصة كاملة إن لم تشاركها حصة أخرى
    for ri, cards in enumerate(gv.cards_of_row):
        for c in cards:
            a, b = gv.spans.get((ri, c.sid), (c.start, c.end))
            assert a <= c.start and b >= c.end
            others = [o for o in cards if o.sid != c.sid and o.day == c.day]
            assert not any(o.start < b and o.end > a for o in others if (ri, c.sid) in gv.spans)
    # بطاقة مثبتة
    sec = ids["sections"][0]
    sub = db.scalar("SELECT id FROM subjects WHERE COALESCE(kind,'teach')='teach' LIMIT 1")
    db.set_setting("tray_pins", f"[[{sec}, {sub}, 90]]")
    gv.selected_section = sec
    page._fill_tray()
    first = page.tray.items[0]
    assert first.pinned and first.subject == sub and first.minutes == 90 and first.home == sec
    page.unpin(first)
    assert page.pins() == []
    # الوضع عبر اقتراح الوقت مع اختيار الأستاذ (النافذة تُقبل آلياً)
    it = page.grid.subject_items(sec)[0]
    sl = page.grid.suggest_slots(it, sec)[0]

    def fake_exec(self):
        self.result_id = self.cands[0]["id"]
        self.chosen = True
        return M.QDialog.Accepted
    monkeypatch.setattr(M.TeacherPicker, "exec", fake_exec)
    n0 = len(page.grid.cards)
    page.place_at(it, sec, sl["day"], sl["start"], sl["end"], sl["teacher"])
    assert len(page.grid.cards) == n0 + 1
    page.close()


# ====================================================================== قوالب الطباعة ومحرر الورقة
def test_print_layout_inheritance(seeded):
    db, ids = seeded
    from dpp.exporters import layout as L
    sec = ids["sections"][0]
    lvl = db.scalar("SELECT level_id FROM sections WHERE id=?", (sec,))
    lay, used = L.effective(db, "section", lvl, sec)
    assert used == [] and lay["page"]["paper"] == "A4" and L.paper_size(lay) == (841.89, 595.28)
    # قالب الطور: ورقة A3 عمودية ونص حر
    lay["page"].update(paper="A3", orientation="portrait")
    b = L.new_box(50, 50, "قسم {section} — {missing_unknown} — {decree}")
    lay["boxes"].append(b)
    L.save(db, f"level:{lvl}", lay, "section", lvl, sec)
    lay2, used2 = L.effective(db, "section", lvl, sec)
    assert used2 == [f"level:{lvl}"] and L.paper_size(lay2) == (841.89, 1190.55) and lay2["boxes"][0]["id"] == b["id"]
    # المحفوظ في الطور هو الفرق فقط (الهوامش والجدول موروثة)
    raw = L.scope_layout(db, f"level:{lvl}")
    assert "margins" not in raw.get("page", {}) and "table" not in raw
    # قالب القسم يغيّر الهوامش ويحذف النص الموروث، والطور يبقى كما هو
    lay2["page"]["margins"] = [5, 5, 5, 5]
    lay2["boxes"] = []
    L.save(db, f"section:{sec}", lay2, "section", lvl, sec)
    lay3, used3 = L.effective(db, "section", lvl, sec)
    assert used3 == [f"level:{lvl}", f"section:{sec}"] and lay3["boxes"] == [] and lay3["page"]["paper"] == "A3"
    other = ids["sections"][1]
    lay_o, _ = L.effective(db, "section", lvl, other)
    assert lay_o["boxes"] and lay_o["page"]["margins"] == [20.0, 20.0, 20.0, 20.0]
    L.reset(db, f"section:{sec}")
    assert L.effective(db, "section", lvl, sec)[1] == [f"level:{lvl}"]
    # الحقول التلقائية: المعروف الفارغ يُعلَّم، وغير المعروف يبقى كما هو
    txt, miss = L.fill_text("قسم {section} {decree} {zzz}", {"section": "ق1", "decree": ""})
    assert txt.startswith("قسم ق1") and "[رقم المقرر؟]" in txt and "{zzz}" in txt and miss == ["decree"]


def test_sheet_scene_layout_and_pdf(seeded, tmp_path):
    app = _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.exporters import layout as L
    from dpp.exporters import official as O
    from dpp.ui.sheet_view import FreeBox, SheetScene, TableHandle, render_to_pdf
    sec = ids["sections"][0]
    sh = O.build(db, "section", sec, START)
    assert sh.section_id == sec and sh.layout and sh.values.get("specialty") is not None
    n_cells = len(sh.cells)
    b = L.new_box(100, 100, "{section} صفحة {page}/{pages}", 200, 30)
    b.update(rotation=-90, frame_w=1)
    sh.layout["boxes"].append(b)
    used_col = sh.cells[0].c0
    sh.layout["table"].update(notes_col=True, hidden_cols=[used_col], merges=[{"day": 0, "c0": 0, "c1": 1, "text": "x"}])
    sh.layout["page"].update(paper="A4", orientation="portrait")
    sc = SheetScene(sh, design=True, page_no=2, pages=3)
    assert (sc.W, sc.H) == (595.28, 841.89)
    fb = sc.boxes[b["id"]]
    assert isinstance(fb, FreeBox) and fb.text.endswith("صفحة 2/3") and fb.rotation() == -90
    assert sc.hidden_with_data                      # حصص في عمود مخفي: تنبيه
    assert any(isinstance(i, TableHandle) for i in sc.items())
    # الالتصاق بالشبكة
    fb.setPos(103.4, 98.2)
    assert (fb.pos().x(), fb.pos().y()) == (100.0, 100.0)
    sc.snap = False
    fb.setPos(103.4, 98.2)
    assert abs(fb.pos().x() - 103.4) < 1e-6
    # الإخراج PDF بنفس مقاس الورقة، والبيانات لم تتغير
    pdf = render_to_pdf([sc, SheetScene(O.build(db, "section", sec, START))], str(tmp_path / "x.pdf"))
    assert (tmp_path / "x.pdf").stat().st_size > 2000 and pdf
    assert len(O.build(db, "section", sec, START).cells) == n_cells


def test_preview_design_mode_undo_and_save(seeded, monkeypatch):
    app = _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.exporters import layout as L
    from dpp.exporters import official as O
    from dpp.ui import sheet_design as SD
    from dpp.ui import sheet_view as SV
    sec = ids["sections"][0]
    dlg = SV.PreviewDialog(db, [O.build(db, "section", s, START) for s in ids["sections"][:2]])
    dlg.b_design.setChecked(True)
    monkeypatch.setattr(SD.TextDialog, "exec", lambda self: SD.QDialog.Rejected)
    dlg.design.add_box()
    app.processEvents()
    sh = dlg.cur_sheet()
    assert len(sh.layout["boxes"]) == 1 and dlg.is_dirty()
    bid = sh.layout["boxes"][0]["id"]
    dlg.design.box_id = bid
    dlg.design.set_box(align="right", bold=True, size=16)
    assert sh.layout["boxes"][0]["align"] == "right" and sh.layout["boxes"][0]["size"] == 16
    dlg.design.center_box(True, True)
    bx = sh.layout["boxes"][0]
    assert abs(bx["x"] - (dlg.cur_scene().W - bx["w"]) / 2) < 0.2
    dlg._table_resized("col", 0, 1, 0.3)
    assert sh.layout["table"]["col_weights"]
    dlg.undo()
    assert not sh.layout["table"].get("col_weights")
    dlg.redo()
    assert sh.layout["table"]["col_weights"]
    # الحفظ في قالب الطور (بلا نوافذ تأكيد)
    monkeypatch.setattr(SD, "confirm", lambda *a, **k: True)
    monkeypatch.setattr(SD, "info", lambda *a, **k: None)
    dlg.design.sync()
    lvl = sh.level_id
    for b in dlg.design.scope_btns.buttons():
        b.setChecked(b.property("scope") == f"level:{lvl}")
    dlg.design.save_scope()
    assert not dlg.is_dirty()
    assert L.effective(db, "section", lvl, ids["sections"][1])[0]["boxes"]      # القسم الآخر يرث
    dlg.saved_layouts = {i: dlg._json.dumps(s.layout, sort_keys=True) for i, s in enumerate(dlg.sheets)}
    dlg.close()


# ====================================================================== المقرر والتقدم والتحليلات
def _curriculum_file(path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    rows = [["الفئة : أهلية عسكرية مهنية درجة أولى الإختصاص : إدارة عقابية"], ["الرقم", "تعين المادة", "الحجم الساعي"],
            [1, "لغة فرنسية", 27], [2, "بيداغوجيا", 122], [4, "قتال", 12], ["المجموع (1)", None, 170],
            [5, "قتال", 40], [6, "مختلفات", 70], ["المجموع العام (1+2)", None, 300]]
    for r in rows:
        ws.append(r)
    wb.save(path)


def test_curriculum_v2_checks_and_alerts(db, tmp_path):
    from dpp.importers import curriculum as CI
    from dpp.services import alerts as AL
    from dpp.services.structure import ensure_structure
    lv = ensure_structure(db)
    lvl = lv["BMP1"]
    sp = db.insert("specialties", level_id=lvl, name="كتابة الضبط")
    s_fr = db.insert("subjects", name="لغة فرنسية", short="ل ف", category="general")
    s_q = db.insert("subjects", name="قتال", short="ق", category="military")
    _curriculum_file(tmp_path / "c.xlsx")
    blocks = CI.analyze(db, str(tmp_path / "c.xlsx"))
    b = blocks[0]
    assert b.specialty_id == sp
    msgs = " | ".join(m for _s, m, _r in b.checks)
    assert "المادة رقم 3 غير موجودة" in msgs                      # قفزة الترقيم
    assert "المجموع (1) المكتوب 170 والمحسوب 161" in msgs          # مجموع لا يطابق
    res = CI.apply(db, blocks)
    # «لغة فرنسية» = «فرنسية»، والقتال مرتين في نفس الجدول = 52 (مع تنبيه)
    assert db.scalar("SELECT hours FROM curriculum WHERE subject_id=?", (s_fr,)) == 27
    assert db.scalar("SELECT hours FROM curriculum WHERE subject_id=?", (s_q,)) == 52
    assert res["summed"] == 1
    keys = {a["key"] for a in AL.open_alerts(db)}
    assert "cf:summed" in keys and any(k.startswith("cf:") and "رقم" in k for k in keys)
    assert not db.scalar("SELECT COUNT(*) FROM subjects WHERE name='مختلفات'")   # سطر غير دراسي
    a = AL.open_alerts(db)[0]
    AL.resolve(db, a["id"])
    CI.apply(db, CI.analyze(db, str(tmp_path / "c.xlsx")))
    assert a["id"] not in {x["id"] for x in AL.open_alerts(db)}    # المؤكَّد لا يعود


def test_bundled_curriculum_and_simple_progress(seeded):
    db, ids = seeded
    from dpp.importers import curriculum as CI
    from dpp.services import progress as P
    if CI.bundled_file() is None:
        pytest.skip("ملف المقرر المدمج غير موجود (غير مرفوع إلى المستودع)")
    T.plan_period(db, ids["formation"], time_limit=5)
    db.execute("UPDATE sessions SET status='done' WHERE date<=?", ((START + timedelta(days=20)).isoformat(),))
    rows = P.simple_progress(db, [ids["formation"]], START + timedelta(days=20))
    assert rows and all(r["family"] in ("specialty", "military", "general") for r in rows)
    r = next(x for x in rows if x["done"] > 0)
    P.set_hours(db, r["level_id"], r["specialty_id"], r["subject_id"], "all", 10)
    r2 = next(x for x in P.simple_progress(db, [ids["formation"]], START + timedelta(days=20))
              if x["section_id"] == r["section_id"] and x["subject_id"] == r["subject_id"])
    assert r2["hours"] == 10 and r2["pct"] == round(r2["done"] / 10 * 100, 1)
    assert r2["remaining"] == round(max(0, 10 - r2["done"]), 2)
    s = P.summarize_simple([r2])
    assert s["hours"] == 10
    fc = P.forecast(db, [r2], START + timedelta(days=20))
    assert fc[0]["status"] in ("ok", "late", "stalled", "done")
    wk = P.weekly_family_hours(db, [ids["formation"]], None, START + timedelta(days=20))
    assert wk["weeks"] and set(wk["series"]) == {"specialty", "military", "general"}
    # مادة مقسمة على مرحلتين: المجموع عند غياب المخطط
    cur = {(1, 0, 5, "basic"): 80.0, (1, 0, 5, "specialized"): 12.0}
    assert P.lookup_hours(cur, 1, None, 5, "all") == 92 and P.curriculum_total(cur, 1, None, 5) == 92


def test_nonteach_reclassified_by_migration(tmp_path):
    import sqlite3
    from dpp.db.database import Database
    d = Database(tmp_path / "m.sqlite")
    d.execute("INSERT INTO subjects(name, short, kind, category) VALUES ('عطلة نهاية الأسبوع','ع ن أ','teach','general')")
    d.execute("UPDATE meta SET value='6' WHERE key='schema_version'")
    d.commit()
    d.close()
    d2 = Database(tmp_path / "m.sqlite")
    assert d2.scalar("SELECT kind FROM subjects WHERE short='ع ن أ'") == "nonteach"
    d2.close()


# ====================================================================== مخطط التكوين والأحداث والمسح
def test_formation_tree_and_phases(db):
    from dpp.services import formation_tree as FT
    from dpp.services.structure import ensure_structure
    lv = ensure_structure(db)
    FT.ensure_defaults(db)
    assert db.scalar("SELECT certificate FROM levels WHERE code='ESOC1'") == "شهادة عسكرية مهنية درجة ثانية"
    assert db.scalar("SELECT year_no FROM levels WHERE code='BMP2'") == 2
    fr = db.scalar("SELECT id FROM formations WHERE short='R'")
    ph = FT.phases(db, fr)
    assert [(p["kind"], p["weeks"]) for p in ph][:3] == [("reception", 1), ("basic", 6), ("leave", 1)]
    sp = db.insert("specialties", level_id=lv["OF-R"], name="ضابط إداري", weeks=10, internship="تربص إداري")
    sch = FT.schedule(db, fr, "2026-09-15", sp)
    assert [p["kind"] for p in sch] == ["reception", "basic", "leave", "specialized"] and sch[-1]["weeks"] == 10
    assert (sch[1]["start"] - sch[0]["start"]).days == 7 and (sch[3]["start"] - sch[1]["start"]).days == 49
    res = FT.generate_timeline(db, fr)
    assert res["weeks"] > 0 and not res["skipped"]
    assert db.scalar("SELECT COUNT(*) FROM timeline WHERE level_code='OF-R' AND kind='leave'") >= 1
    # الشجرة: التكوين ← الشهادة ← الطور ← الاختصاص ← الأقسام، ونقل قسم
    s = db.insert("sections", formation_id=fr, level_id=lv["OF-R"], short="OF-R 1", name="OF-R 1")
    tr = FT.tree(db)
    r = next(f for f in tr if f["id"] == fr)
    names = [sp_["name"] for c in r["certificates"] for l_ in c["levels"] for sp_ in l_["specialties"]]
    assert "بلا اختصاص" in names
    FT.move_section(db, s, lv["OF-R"], sp)
    assert db.scalar("SELECT specialty_id FROM sections WHERE id=?", (s,)) == sp


def test_event_sections_and_blocking(seeded):
    db, ids = seeded
    from dpp.services import calendar as C
    f = ids["formation"]
    s1, s2 = ids["sections"][:2]
    eid = C.add_event(db, "زيارة", "exam", "2026-11-03", "2026-11-03", f, None, "", 1, True, "1")
    C.set_event_sections(db, eid, [s1])
    assert C.event_sections(db, eid) == [s1] and "1 قسم" in C.attendees_label(db, eid)
    d = date(2026, 11, 3)
    assert d in C.blocked_dates(db, f, d, d, s1)
    assert d not in C.blocked_dates(db, f, d, d, s2)          # القسم غير المعني لا يُحجب


def test_wipe_all_data(tmp_path):
    from dpp.db.database import Database
    from dpp.services import backup as B
    d = Database(tmp_path / "w.sqlite")
    d.create_admin("admin", "secret12")
    with pytest.raises(ValueError):
        B.wipe_all(d, "wrong")
    d2 = Database(tmp_path / "w.sqlite")
    B.wipe_all(d2, "secret12")
    assert not (tmp_path / "w.sqlite").exists()
    d3 = Database(tmp_path / "w.sqlite")
    assert not d3.has_users()                                  # كأنه برنامج جديد
    d3.close()


def test_three_styles(seeded):
    app = _app()
    db, ids = seeded
    from dpp.ui import theme
    from dpp.ui.context import AppContext
    from dpp.ui.main_window import MainWindow
    from dpp.ui.shell import STYLES
    db.set_setting("ui_style", "clean")                        # نمط قديم ← الواجهة ب عند الترقية
    w = MainWindow(AppContext(db), app)
    assert w.ui_style == "ledger" and [k for k, _ in STYLES] == ["ops", "ledger", "daily"]
    w.show()
    w.navigate("master")
    for st, pal in (("ops", "ops"), ("ledger", "ledger"), ("daily", "daily")):
        w.apply_style(st)
        app.processEvents()
        assert theme.CURRENT_NAME == pal
    assert w.top_nav.isVisible() and not w.modern_side.isVisible()
    m = w.pages["master"]
    m.focus_day(1)
    assert m.view_grid.days == [1]
    from PySide6.QtCore import Qt
    w.apply_style("ledger")
    assert m.split.orientation() == Qt.Vertical                 # 1.4.1: الشريط في الأسفل في كل الواجهات
    m.options["tray_side"] = True
    m.place_tray()
    assert m.split.orientation() == Qt.Horizontal
    m.options["tray_side"] = False
    m.place_tray()
    w.apply_style("ops")
    assert w.modern_side.collapsed and len(m.view_grid.days) >= 5
    w.close()


def test_substitution_dialog_lists_all_teachers(seeded):
    app = _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.services import absences as A
    from dpp.ui.context import AppContext
    from dpp.ui.teacher_profile import SubstitutionDialog
    r = db.one("SELECT teacher_id, date FROM sessions WHERE teacher_id IS NOT NULL AND status='planned' ORDER BY date LIMIT 1")
    aid = A.add_absence(db, r["teacher_id"], "إجازة", r["date"], r["date"])
    d = SubstitutionDialog(AppContext(db), aid)
    assert d.combos
    n_active = db.scalar("SELECT COUNT(*) FROM teachers WHERE active=1")
    cb = d.combos[0]
    ids_in = {cb.itemData(i) for i in range(cb.count()) if cb.itemData(i)}
    assert len(ids_in) == n_active - 1 and cb.isEditable()       # كل الأساتذة ما عدا الغائب، مع البحث
    d.close()


def test_v141_tray_duration_and_progress_scopes(seeded):
    """1.4.1: نص البطاقة اسم المادة فقط، النقر يحمل البطاقة، المدة من القائمة ترفض عند التعارض،
    والمقرر والمنجز حسب التكوين/الطور/الاختصاص/القسم بثلاثة أشكال، ولا تفرض الصفحات عرضاً أكبر من الشاشة."""
    app = _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from datetime import date as _d
    from PySide6.QtCore import Qt
    from dpp.ui.context import AppContext
    from dpp.ui.main_window import MainWindow
    w = MainWindow(AppContext(db), app)
    w.resize(1280, 760)
    w.show()
    w.navigate("master")
    m = w.pages["master"]
    ws = _d.fromisoformat(db.scalar("SELECT MIN(date) FROM sessions"))
    m.set_week(ws)
    sec = db.scalar("SELECT id FROM sections ORDER BY id LIMIT 1")
    m.view_grid.selected_section = sec
    m._fill_tray()
    app.processEvents()
    assert m.tray.count() > 0
    li = m.tray.item(0)
    it = li.data(Qt.UserRole)
    assert "سا" not in li.text() and "…" not in li.text()
    m.tray._clicked(li)
    assert m.view_grid.picked is it
    m.view_grid.cancel_pick()
    # المدة: تمديد حصة إلى 4 سا يتعارض مع الحصة التالية ← يُرفض دون تغيير
    import dpp.ui.pages.master as M
    errs = []
    M.error = lambda *a, **k: errs.append(a)
    c = next(iter(m.grid.cards.values()))
    before = (c.start, c.end)
    nxt = [x for x in m.grid.cards.values() if x.day == c.day and set(x.sections) & set(c.sections) and x.start >= c.end]
    if nxt:
        m.set_duration(c, (min(x.start for x in nxt) - c.start) + 60)
        assert errs and (m.grid.cards[c.sid].start, m.grid.cards[c.sid].end) == before
    # المقرر والمنجز
    w.navigate("progress")
    pg = w.pages["progress"]
    sv = pg.simple
    for scope in ("formation", "level", "specialty", "section"):
        sv.set_scope(scope)
        for shape in ("donut", "hbar", "vbar"):
            sv.set_shape(shape)
            sv.chart.grab()
    sv.set_scope("formation")
    if sv.chart.items and sv.chart.items[0]["key"]:
        sv._drill(sv.chart.items[0]["key"])
        assert sv.scope == "level"
    # عرض النافذة الأدنى معقول في الواجهات الثلاث (لا تُدفع القائمة الجانبية خارج الشاشة)
    for st in ("ops", "ledger", "daily"):
        w.apply_style(st)
        app.processEvents()
        assert w.minimumSizeHint().width() < 1280, st
    w.close()
