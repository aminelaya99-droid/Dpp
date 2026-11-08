"""لوحة التحكم: بطاقات حقيقية، مركز تنبيهات، مخططات، مواعيد قريبة، عمليات سريعة."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ...services import absences as A
from ...services import calendar as C
from ...services import hours as H
from ...utils import iso, week_days, week_start
from .. import theme
from ..context import AppContext
from ..widgets import BarCompare, DonutChart, StatCard, icon

CARDS = [
    ("formations", "التكوينات النشطة", "mdi6.school-outline"),
    ("sections", "الأقسام والأفواج", "mdi6.account-group-outline"),
    ("teachers", "الأساتذة والقاعات", "mdi6.human-male-board"),
    ("sessions", "الحصص المبرمجة / المنجزة", "mdi6.calendar-check-outline"),
    ("progress", "تقدم التكوين الحالي", "mdi6.chart-donut"),
    ("late", "المواد المتأخرة", "mdi6.alert-outline"),
    ("absences", "الغيابات الحالية", "mdi6.account-off-outline"),
    ("events", "مواعيد خلال 30 يوماً", "mdi6.calendar-clock"),
]


class DashboardPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        scroll.setWidget(body)
        self.lay = QVBoxLayout(body)
        self.lay.setContentsMargins(20, 14, 20, 20)
        self.lay.setSpacing(14)
        head = QHBoxLayout()
        self.title = QLabel("لوحة التحكم")
        self.title.setObjectName("PageTitle")
        head.addWidget(self.title)
        self.sub = QLabel()
        self.sub.setObjectName("Muted")
        head.addWidget(self.sub)
        head.addStretch()
        cust = QPushButton(icon("mdi6.view-dashboard-edit-outline"), "تخصيص البطاقات")
        cust.clicked.connect(self.customize)
        head.addWidget(cust)
        ref = QPushButton(icon("mdi6.refresh"), "تحديث")
        ref.clicked.connect(self.refresh)
        head.addWidget(ref)
        self.lay.addLayout(head)

        self.cards_w = QWidget()
        self.cards_l = QGridLayout(self.cards_w)
        self.cards_l.setSpacing(12)
        self.cards_l.setContentsMargins(0, 0, 0, 0)
        self.lay.addWidget(self.cards_w)
        self.cards = {}
        for key, title, ic in CARDS:
            c = StatCard(key, title, icon_name=ic)
            c.clicked.connect(self._card_clicked)
            self.cards[key] = c

        # الصف الثاني: التنبيهات + المواعيد
        row = QHBoxLayout()
        self.alerts_box, self.alerts = self._panel("مركز التنبيهات", "mdi6.bell-outline")
        self.events_box, self.events = self._panel("المواعيد القريبة والعد التنازلي", "mdi6.timer-sand")
        row.addWidget(self.alerts_box, 3)
        row.addWidget(self.events_box, 2)
        self.lay.addLayout(row)

        # الصف الثالث: المخططات
        row2 = QHBoxLayout()
        self.donut_box, donut_l = self._panel("تقدم الأقسام (المنجز من المقرر)", "mdi6.chart-donut")
        self.donuts = QHBoxLayout()
        self.donuts.setSpacing(8)
        dw = QWidget()
        dw.setLayout(self.donuts)
        donut_l.addWidget(dw)
        self.bars_box, bars_l = self._panel("الأساتذة: المبرمج مقابل المنجز (هذا الأسبوع)", "mdi6.chart-bar")
        self.bars = BarCompare()
        bars_l.addWidget(self.bars)
        row2.addWidget(self.donut_box, 3)
        row2.addWidget(self.bars_box, 2)
        self.lay.addLayout(row2)

        # عمليات سريعة
        qa_box, qa_l = self._panel("عمليات سريعة", "mdi6.lightning-bolt-outline")
        qrow = QHBoxLayout()
        for text, ic, target in [("إنشاء جدول", "mdi6.auto-fix", "generate"), ("تسجيل غياب", "mdi6.account-off-outline", "absences"),
                                 ("إضافة موعد", "mdi6.calendar-plus", "calendar"), ("طباعة تقرير", "mdi6.printer-outline", "reports"),
                                 ("المخطط الأسبوعي", "mdi6.calendar-week", "planner"), ("نسخة احتياطية", "mdi6.backup-restore", "backup")]:
            b = QPushButton(icon(ic), text)
            b.clicked.connect(lambda _=False, t=target: ctx.navigate.emit(t, None))
            qrow.addWidget(b)
        qrow.addStretch()
        qa_l.addLayout(qrow)
        self.lay.addWidget(qa_box)
        self.lay.addStretch()
        ctx.data_changed.connect(lambda _: self.refresh())
        ctx.formation_changed.connect(lambda _: self.refresh())
        self.refresh()

    def _panel(self, title, ic):
        box = QFrame()
        box.setObjectName("Card")
        l = QVBoxLayout(box)
        l.setContentsMargins(14, 10, 14, 12)
        h = QHBoxLayout()
        i = QLabel()
        i.setPixmap(icon(ic, theme.CURRENT["accent"]).pixmap(18, 18))
        h.addWidget(i)
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        h.addWidget(t)
        h.addStretch()
        l.addLayout(h)
        if title.startswith("مركز") or title.startswith("المواعيد"):
            lst = QListWidget()
            lst.setMinimumHeight(190)
            lst.itemDoubleClicked.connect(lambda it: self._alert_action(it))
            l.addWidget(lst)
            return box, lst
        return box, l

    # ------------------------------------------------------------------
    def _card_order(self):
        try:
            cfg = json.loads(self.ctx.db.get_setting("dashboard_cards") or "[]")
        except ValueError:
            cfg = []
        keys = [k for k, _, _ in CARDS]
        if not cfg:
            return [(k, True) for k in keys]
        seen = [(k, v) for k, v in cfg if k in keys]
        return seen + [(k, True) for k in keys if k not in dict(seen)]

    def _layout_cards(self):
        while self.cards_l.count():
            it = self.cards_l.takeAt(0)
            if it.widget():
                it.widget().setParent(None)
        i = 0
        for k, vis in self._card_order():
            if vis:
                self.cards_l.addWidget(self.cards[k], i // 4, i % 4)
                i += 1

    def customize(self):
        d = QDialog(self)
        d.setWindowTitle("تخصيص بطاقات لوحة التحكم")
        v = QVBoxLayout(d)
        v.addWidget(QLabel("فعّل البطاقات المطلوبة واسحبها لإعادة ترتيبها:"))
        lst = QListWidget()
        lst.setDragDropMode(QListWidget.InternalMove)
        names = {k: t for k, t, _ in CARDS}
        for k, vis in self._card_order():
            it = QListWidgetItem(names[k])
            it.setData(Qt.UserRole, k)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if vis else Qt.Unchecked)
            lst.addItem(it)
        v.addWidget(lst)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if d.exec() == QDialog.Accepted:
            cfg = [[lst.item(i).data(Qt.UserRole), lst.item(i).checkState() == Qt.Checked] for i in range(lst.count())]
            self.ctx.db.set_setting("dashboard_cards", json.dumps(cfg))
            self._layout_cards()

    def _card_clicked(self, key):
        target = {"formations": "formations", "sections": "sections", "teachers": "teachers", "sessions": "planner",
                  "progress": "progress", "late": "progress", "absences": "absences", "events": "calendar"}[key]
        self.ctx.navigate.emit(target, None)

    def _alert_action(self, it):
        data = it.data(Qt.UserRole)
        if data:
            self.ctx.navigate.emit(data, None)

    # ------------------------------------------------------------------
    def refresh(self):
        db, fid = self.ctx.db, self.ctx.formation_id
        today = date.today()
        self._layout_cards()
        cq, cs = self.ctx.q, self.ctx.scalar
        fids = self.ctx.formation_ids()
        self.sub.setText(f"— {self.ctx.formation_label()}" if fid else "— لا يوجد تكوين بعد")
        nform = db.scalar("SELECT COUNT(*) FROM formations WHERE archived=0", default=0)
        self.cards["formations"].set(nform, f"{db.scalar('SELECT COUNT(*) FROM formations WHERE archived=1', default=0)} مؤرشف")
        nsec = cs("SELECT COUNT(*) FROM sections WHERE formation_id=?", (fid or -1,), 0)
        ngrp = cs("SELECT COUNT(*) FROM groups_ g JOIN sections s ON s.id=g.section_id WHERE s.formation_id=?",
                  (fid or -1,), 0)
        nlev = cs("SELECT COUNT(*) FROM levels WHERE formation_id=?", (fid or -1,), 0)
        self.cards["sections"].set(f"{nsec} / {ngrp}", f"{nlev} طور — {self.ctx.formation_label()}")
        self.cards["teachers"].set(f"{db.scalar('SELECT COUNT(*) FROM teachers WHERE active=1', default=0)} / "
                                   f"{db.scalar('SELECT COUNT(*) FROM rooms', default=0)}", "أستاذ نشط / قاعة")
        sp = cq("""SELECT SUM(CASE WHEN s.status IN ('planned','done') THEN 1 ELSE 0 END) p,
                          SUM(CASE WHEN s.status='done' THEN 1 ELSE 0 END) d
                   FROM sessions s JOIN timetables t ON t.id=s.timetable_id WHERE t.formation_id=?""", (fid or -1,))[0]
        self.cards["sessions"].set(f"{sp['p'] or 0} / {sp['d'] or 0}", "مبرمجة / منجزة فعلياً")
        from ...services import progress as PR
        prows = PR.section_progress(db, fids, today)
        ps = PR.summarize(prows)
        self.cards["progress"].set(f"{ps['pct_done']:g}%" if ps["pct_done"] is not None else "—",
                                   f"{ps['done']:g} من {ps['hours']:g} ساعة مقررة" if ps["hours"] else
                                   "أدخل المقرر لحساب النسبة")
        self.cards["late"].set(ps["late"], "مقارنة بالمتوقع حسب المخطط الزمني")
        cur_abs = A.current_absences(db, today)
        self.cards["absences"].set(len(cur_abs), "، ".join(a["full_name"] for a in cur_abs[:3]))
        ev = C.upcoming(db, today, 30)
        self.cards["events"].set(len(ev), (f"الأقرب: {ev[0]['title']} بعد {ev[0]['days_left']} يوم" if ev else ""))

        # التنبيهات
        self.alerts.clear()

        def alert(text, target, level="warn"):
            col = theme.CURRENT[{"warn": "warn", "bad": "bad", "ok": "ok", "info": "accent"}[level]]
            it = QListWidgetItem(icon({"warn": "mdi6.alert-outline", "bad": "mdi6.alert-octagon-outline",
                                       "ok": "mdi6.check-circle-outline", "info": "mdi6.information-outline"}[level], col),
                                 text + "   ⟵ نقر مزدوج للمعالجة")
            it.setData(Qt.UserRole, target)
            self.alerts.addItem(it)

        if not fid:
            alert("لا يوجد تكوين. ابدأ بإنشاء تكوين أو استيراد ملف .roz.", "formations", "info")
        else:
            if ps["missing"] and not ps["hours"]:
                alert("لم يُحدَّد المقرر (الحجم الساعي) للمواد بعد؛ نسب الإنجاز تحتاجه.", "progress", "info")
            late = [r for r in prows if r["late"]]
            for r in late[:6]:
                alert(f"مادة متأخرة: {r['subject']} — {r['section']} "
                      f"(منجز {r['done']:g} من المتوقع {r['expected']:g} سا، المطلوب {r['per_week'] or 0:g} سا/أسبوع)",
                      "progress", "bad")
            if len(late) > 6:
                alert(f"… و{len(late) - 6} مادة متأخرة أخرى", "progress", "bad")
            noq = cq("""SELECT DISTINCT s.name FROM requirements r JOIN subjects s ON s.id=r.subject_id
                          WHERE r.formation_id=? AND r.teacher_id IS NULL
                          AND NOT EXISTS (SELECT 1 FROM teacher_subjects ts WHERE ts.subject_id=r.subject_id)""", (fid,))
            for r in noq[:5]:
                alert(f"لا يوجد أستاذ مؤهل لمادة «{r['name']}».", "teachers", "bad")
            ws = week_start(today)
            tts = cq("SELECT status FROM timetables WHERE formation_id=? AND week_start=?", (fid, iso(ws)))
            tt = tts[0] if tts else None
            if not tt:
                alert("لا يوجد جدول لهذا الأسبوع.", "generate", "warn")
            elif tt["status"] != "approved":
                alert("جدول هذا الأسبوع ما زال مسودة غير معتمدة.", "planner", "warn")
            past_planned = cs("""SELECT COUNT(*) FROM sessions s JOIN timetables t ON t.id=s.timetable_id
                                        WHERE t.formation_id=? AND s.status='planned' AND s.date<?""", (fid, iso(today)), 0)
            if past_planned:
                alert(f"{past_planned} حصة سابقة ما زالت «مبرمجة»؛ سجّل إنجازها أو تأجيلها لتصح الإحصائيات.", "planner", "warn")
        for a in cur_abs:
            unc = db.scalar("""SELECT COUNT(*) FROM sessions WHERE teacher_id=? AND date>=? AND date<=? AND status='planned'
                               AND substitute_id IS NULL""", (a["teacher_id"], iso(today), a["end_date"]), 0)
            if unc:
                alert(f"{a['full_name']} غائب ({a['reason']}) و{unc} حصة بلا مستخلف.", "absences", "bad")
        for e in C.due_reminders(db, today):
            alert(f"تذكير: {e['title']} ({e['kind_label']}) " + ("اليوم" if e["days_left"] <= 0 else f"بعد {e['days_left']} يوم"),
                  "calendar", "info")
        if self.alerts.count() == 0:
            alert("لا توجد تنبيهات. كل شيء على ما يرام.", None, "ok")

        # المواعيد
        self.events.clear()
        for e in C.upcoming(db, today, 120)[:15]:
            left = e["days_left"]
            when = "جارٍ الآن" if left <= 0 else ("غداً" if left == 1 else f"بعد {left} يوم")
            it = QListWidgetItem(icon("mdi6.calendar-star" if e["kind"] in ("exam", "final_exam") else "mdi6.calendar",
                                      theme.CURRENT["accent"]),
                                 f"{when}  —  {e['title']}  ({e['kind_label']})  {e['start_date']}")
            it.setData(Qt.UserRole, "calendar")
            self.events.addItem(it)
        if self.events.count() == 0:
            self.events.addItem("لا توجد مواعيد قريبة.")

        # المخططات الحلقية
        while self.donuts.count():
            w = self.donuts.takeAt(0).widget()
            if w:
                w.deleteLater()
        if fid:
            agg = defaultdict(lambda: [0.0, 0.0])
            for r in prows:
                if r["hours"]:
                    agg[r["section"]][0] += r["hours"]
                    agg[r["section"]][1] += r["done"]
            for name, (tot, done) in list(agg.items())[:8]:
                self.donuts.addWidget(DonutChart(name, done / tot * 100 if tot else 0, f"{done:g} من {tot:g} سا", size=120))
        if self.donuts.count() == 0:
            lab = QLabel("لا توجد بيانات تقدم بعد.")
            lab.setObjectName("Muted")
            self.donuts.addWidget(lab)
        self.donuts.addStretch()
        days = week_days(week_start(today))
        rows = db.q("""SELECT t.full_name n, SUM(CASE WHEN s.status IN ('planned','done') THEN s.end_min-s.start_min ELSE 0 END) p,
                              SUM(CASE WHEN s.status='done' THEN s.end_min-s.start_min ELSE 0 END) d
                       FROM sessions s JOIN teachers t ON t.id=COALESCE(s.substitute_id, s.teacher_id)
                       WHERE s.date>=? AND s.date<=? GROUP BY t.id ORDER BY p DESC LIMIT 10""", (iso(days[0]), iso(days[-1])))
        self.bars.set_items([(r["n"], round((r["p"] or 0) / 60, 1), round((r["d"] or 0) / 60, 1)) for r in rows])
