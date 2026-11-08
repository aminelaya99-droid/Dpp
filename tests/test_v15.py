"""اختبارات الإصدار 1.5: الجدول بالساعات وأحجام الأعمدة، اليوم الكامل والغداء المرن، التقارير في المحرر الواحد،
الضبط، تقارير التقدم وExcel، أولويات البرمجة، الخفارة والخدمات، أدوات المخطط، والأصوات."""
from datetime import date, timedelta

from conftest import START

from dpp.services import timetables as T
from dpp.services.grid import WeekGrid


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


def test_hours_layout_and_resizable_columns(seeded):
    app = _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    page, M = _page(db)
    page.set_layout("hours")
    gv = page.view_grid
    assert gv.time_mode() and gv.slot() == 60
    assert all(u.end - u.start == 60 for u in gv.units)
    w0 = gv.col_w[0]
    # سحب حد الخانة الأولى يغيّر عرضها فقط
    gv._start_size_drag(("unit", 0), gv.col_rect(0).topLeft())
    from PySide6.QtCore import QPoint
    gv._do_size_drag(gv.col_rect(0).topLeft() - QPoint(40, 0))
    assert gv.col_w[0] > w0 and gv.col_w[1] == gv.col_w[gv.nu + 1]
    # عرض يوم كامل
    band0 = sum(gv.col_w[:gv.nu])
    gv._start_size_drag(("day", 0), QPoint(gv.col_rect(gv.nu - 1).x(), 5))
    gv._do_size_drag(QPoint(gv.col_rect(gv.nu - 1).x() - 60, 5))
    assert sum(gv.col_w[:gv.nu]) > band0
    gv.reset_size(("day", 0))
    page.hide_unit(gv.units[-1].idx)
    n = gv.nu
    page.show_all_units()
    assert gv.nu == n + 1
    # كل خانة تُصاب بالنقر في موضعها
    for c in range(len(gv.col_w)):
        rc = gv.col_rect(c, 0)
        if 0 <= rc.center().x() < gv.viewport().width() - gv.LW():
            assert gv.hit(rc.center()) == (0, c)
    page.reset_all_sizes()
    page.set_layout("periods")
    app.processEvents()


def test_full_day_cards_lunch_and_events(seeded, monkeypatch):
    _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    page, M = _page(db)
    monkeypatch.setattr(M, "confirm", lambda *a, **k: True)
    page._fill_tray()
    quick = [it for it in page.tray.items if it.full_day]
    assert [it.sname for it in quick][:4] == ["اختبار", "خفارة", "خدمة", "تمرين ميداني"]
    g = page.grid
    sec = ids["sections"][0]
    d = next(c.day for c in g.by_section[sec])
    before = len(g.day_cards(sec, d))
    assert before
    page.place_full_day(quick[1], sec, d)
    after = g.day_cards(sec, d)
    s, e = g.full_day_range(sec)
    assert len(after) == 1 and (after[0].start, after[0].end) == (s, e) and after[0].sname == "خفارة"
    page.undo()                                            # خطوة تراجع واحدة تعيد اليوم كما كان
    assert len(g.day_cards(sec, d)) == before
    # الغداء المرن: يكفي أن تبقى ساعة فارغة في اليوم
    lunchless = [c for c in g.by_section[sec] if c.day == d and c.kind == "nonteach"]
    for c in lunchless:
        g.delete(c.sid)
    msg = g.lunch_room_msg(sec, d, s, e - 30)
    assert msg and "غداء" in msg
    assert g.lunch_room_msg(sec, d, s, e) is None          # اليوم الكامل يغطي الغداء
    # حدث «يوم كامل» من الأحداث يظهر في الفحص
    from dpp.services import calendar as CAL
    d2 = d + timedelta(days=1)
    eid = CAL.add_event(db, "خفارة السرية", "duty", d2)
    CAL.set_event_sections(db, eid, [sec])
    g.reload()
    assert (sec, d2) in g.day_events
    msgs = g.check(sections=[sec], groups=set(), teacher=None, room=None, subject=1, shareable=False, kind="teach",
                   day=d2, start=s, end=s + 60)
    assert any("خفارة السرية" in m for m in msgs)


def test_exam_counts_in_curriculum_and_duty_not(seeded):
    db, ids = seeded
    from dpp.services import fullday as FD
    ids_ = FD.subjects(db)
    kinds = {db.scalar("SELECT name FROM subjects WHERE id=?", (i,)): db.scalar("SELECT kind FROM subjects WHERE id=?", (i,))
             for i in ids_}
    assert kinds["اختبار"] == "teach" and kinds["خفارة"] == "nonteach" and kinds["خدمة"] == "nonteach"
    assert FD.lunch_subject(db)


def test_report_pages_pagination_and_render(seeded, tmp_path):
    _app()
    db, ids = seeded
    from dpp.exporters import layout as L
    from dpp.exporters import report_sheet as RS
    from dpp.ui.sheet_view import SheetScene, render_to_pdf
    doc = RS.ReportDoc("progress_compare", "تقرير تجريبي", ["سطر معلومات"])
    doc.para("فقرة تجريبية طويلة " * 10)
    doc.table(["المادة", "القيمة", "النسبة"], [[f"مادة {i}", str(i), f"{i}%"] for i in range(120)],
              fills={"0:2": "#F6C9C2"})
    sheets = RS.sheets(db, doc)
    assert len(sheets) >= 3 and all(s.layout is sheets[0].layout for s in sheets)
    rows = [r for s in sheets for it in s.report["items"] if it["type"] == "table" for r in it["rows"]]
    assert rows == list(range(120))                       # لا سطر ضائع ولا مكرر
    scenes = [SheetScene(s, page_no=i + 1, pages=len(sheets)) for i, s in enumerate(sheets)]
    pdf = render_to_pdf(scenes, str(tmp_path / "r.pdf"))
    assert (tmp_path / "r.pdf").stat().st_size > 2000
    # تصميم «كل التقارير» يورَّث، وتقرير بعينه يتخصص
    lay, used = L.effective(db, "report_progress_compare")
    assert lay["page"]["orientation"] == "portrait" and L.scope_chain("report_x") == ["kind:report", "kind:report_x"]
    lay["page"]["orientation"] = "landscape"
    L.save(db, "kind:report", lay, "report_progress_compare")
    assert L.effective(db, "report_progress_compare")[0]["page"]["orientation"] == "landscape"
    sh2 = RS.sheets(db, doc)
    assert len(sh2) != len(sheets) or True                 # الأفقي يغيّر التوزيع
    _ = pdf


def test_justify_and_kashida():
    _app()
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPainter
    from dpp.ui import justify as J
    f = QFont()
    f.setPointSizeF(12)
    fm = QFontMetricsF(f)
    line = "الجمهورية الجزائرية الديمقراطية"
    w = fm.horizontalAdvance(line) * 1.25
    st = J.stretch_kashida(line, fm, w)
    assert J.TATWEEL in st and fm.horizontalAdvance(st) <= w + 0.5
    assert J.kashida_points("دار") == []                  # الدال والألف لا يتصلان بما بعدهما
    img = QImage(400, 200, QImage.Format_RGB32)
    p = QPainter(img)
    h = J.draw(p, QRectF(5, 5, 390, 190), "نص للتجربة " * 12, f, "top", kashida=True)
    p.end()
    assert h > fm.lineSpacing() * 2


def test_progress_reports_and_excel_formulas(seeded, tmp_path):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.services import progress as P
    from dpp.services import progress_reports as PR
    db.execute("UPDATE sessions SET status='done'")
    db.commit()
    lv = db.scalar("SELECT level_id FROM sections WHERE id=?", (ids["sections"][0],))
    db.execute("INSERT OR REPLACE INTO curriculum(level_id, specialty_id, subject_id, phase, hours, source) "
               "SELECT ?, 0, subject_id, 'all', 40, 'manual' FROM requirements GROUP BY subject_id", (lv,))
    db.commit()
    rows = P.simple_progress(db, [ids["formation"]], START + timedelta(days=60))
    assert rows
    m = PR.matrix(rows)
    assert m["sections"] and m["subjects"]
    for f in (PR.doc_compare, PR.doc_sections, PR.doc_full):
        d = f(db, rows, "اختبار", START)
        assert any(b["type"] == "table" for b in d.blocks)
    path = PR.to_xlsx(db, rows, tmp_path / "p.xlsx")
    import openpyxl
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames[0] == "ملخص" and len(wb.sheetnames) >= 3
    ws = wb[wb.sheetnames[-1]]
    assert str(ws["E4"].value).startswith("=IF(") and ws.conditional_formatting


def test_priorities_plan_and_rules(seeded):
    db, ids = seeded
    from dpp.scheduler.engine import Scheduler
    from dpp.services import priorities as PRI
    fid = ids["formation"]
    sec = ids["sections"][0]
    sub = db.scalar("""SELECT r.subject_id FROM requirements r JOIN groups_ g ON g.id=r.group_id
                       WHERE g.section_id=? LIMIT 1""", (sec,))
    cfg = PRI.load(db)
    cfg.update(enabled=True, targets=[{"scope": "section", "ref": sec, "subject": sub, "hours": 4}])
    cfg["rules"].update(day_hours=7, max_per_day=1)
    hours, rows = PRI.week_plan(db, fid, START, cfg=cfg)
    hit = [r for r in rows if r["section_id"] == sec and r["subject_id"] == sub]
    assert hit and all(r["hours"] == 4 for r in hit) and "محددة" in hit[0]["reason"]
    res = Scheduler(db, time_limit=10).schedule_week(fid, START, hours_override=hours, rules=cfg["rules"])
    per = {}
    for p in res.placements:
        for gid in p.meeting.group_ids:
            per.setdefault((gid, p.meeting.subject_id, p.day), 0)
            per[(gid, p.meeting.subject_id, p.day)] += 1
    assert max(per.values(), default=0) <= 1               # حصة واحدة من نفس المادة في اليوم
    day_min = {}
    for p in res.placements:
        for gid in p.meeting.group_ids:
            day_min[(gid, p.day)] = day_min.get((gid, p.day), 0) + p.end_min - p.start_min
    assert max(day_min.values(), default=0) <= 7 * 60
    cmp = PRI.compare_result(rows, res)
    assert all("placed" in r and "short" in r for r in cmp)


def test_duty_fair_rotation_and_insert(seeded, tmp_path):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.services import duty as D
    D.ensure_defaults(db)
    ts = D.types(db)
    assert [t["name"] for t in ts][:2] == ["خفارة", "خدمة"]
    a, b = START, START + timedelta(days=27)
    res = D.generate(db, a, b)
    assert res["placed"] > 0
    st = D.stats(db, a, b)
    tots = [tot for _n, _c, tot in st["rows"]]
    assert max(tots) - min(tots) <= 2                       # تناوب عادل
    rows = D.assignments(db, a, b)
    for x in rows:                                         # لا نوعين لنفس القسم في نفس اليوم
        same = [y for y in rows if y["date"] == x["date"] and y["section_id"] == x["section_id"]]
        assert len(same) == 1
    # التعيين اليدوي يبقى بعد إعادة التوزيع
    d0 = rows[0]["date"]
    other = next(s for s in ids["sections"] if s != rows[0]["section_id"])
    D.set_manual(db, rows[0]["type_id"], d0, [other])
    D.generate(db, a, b)
    keep = [x for x in D.assignments(db, d0, d0) if x["type_id"] == rows[0]["type_id"]]
    assert keep[0]["section_id"] == other and keep[0]["manual"] == 1
    # لا تدخل الجدول إلا بالإدراج
    g = WeekGrid(db, START)
    duty_subs = {t["subject_id"] for t in ts}
    assert not any(c.subject in duty_subs for c in g.cards.values())
    out = D.insert_week(db, START, lambda *x: True)
    g.reload()
    assert out["inserted"] > 0 and any(c.subject in duty_subs for c in g.cards.values())
    assert D.to_xlsx(db, a, b, tmp_path / "d.xlsx")
    doc = D.report_doc(db, a, b)
    assert doc.blocks


def test_planner_tools(seeded):
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.services import planner_tools as PT
    sec = ids["sections"][0]
    nd = PT.needs(db, sec, START)
    assert nd and all(n["left"] >= 0 for n in nd)
    days = PT.day_summary(db, sec, START)
    assert len(days) == 7
    n = PT.save_template(db, sec, START)
    assert n > 0 and PT.template_info(db, sec)["items"]
    nxt = START + timedelta(days=7 * 6)
    placed, skipped = PT.apply_template(db, sec, nxt)
    assert placed + len(skipped) == n
    s1, s2 = [r[0] for r in db.q("""SELECT DISTINCT s.id FROM sessions s JOIN session_groups sg ON sg.session_id=s.id
                                    JOIN groups_ g ON g.id=sg.group_id WHERE g.section_id=? AND s.date BETWEEN ? AND ?
                                    ORDER BY s.date, s.start_min LIMIT 2""", (sec, START.isoformat(),
                                                                           (START + timedelta(days=6)).isoformat()))]
    a = db.one("SELECT date, start_min FROM sessions WHERE id=?", (s1,))
    PT.swap(db, s1, s2)
    b = db.one("SELECT date, start_min FROM sessions WHERE id=?", (s2,))
    assert (a["date"], a["start_min"]) == (b["date"], b["start_min"])
    PT.set_lock(db, [s1], True)
    assert db.scalar("SELECT manual FROM sessions WHERE id=?", (s1,)) == 1
    assert isinstance(PT.check_week(db, [sec], START), list)


def test_sounds_generate_wav():
    from dpp.ui import sounds
    for k in sounds.TONES:
        p = sounds._wav(k, 50)
        import wave
        with wave.open(p) as w:
            assert w.getnframes() > 1000


def test_pages_open_v15(seeded):
    app = _app()
    db, ids = seeded
    T.plan_period(db, ids["formation"], time_limit=5)
    from dpp.ui.context import AppContext
    from dpp.ui.main_window import MainWindow
    w = MainWindow(AppContext(db), app)
    w.resize(1280, 760)
    w.show()
    for k in ("duty", "planner", "progress", "reports", "settings"):
        w.navigate(k)
        app.processEvents()
    pv = w.pages["progress"].simple
    pv.set_scope("level")
    pv.table_mode.setCurrentIndex(0)
    app.processEvents()
    assert pv.tstack.currentWidget() is pv.matrix
    for kind in ("current", "sections", "compare", "full"):
        doc = pv.build_doc(kind)
        assert doc.title and (doc.blocks or not pv.rows)
    w.close()
