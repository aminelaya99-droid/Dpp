"""صفحة الغياب والاستخلاف."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...services import absences as A
from ...services import timetables as T
from ...utils import STATUS_LABELS, hm, iso
from ..context import AppContext
from ..widgets import FormDialog, confirm, error, icon, info, page_title


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    t.horizontalHeader().setStretchLastSection(True)
    t.setAlternatingRowColors(True)
    return t


class AbsencesPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("الغياب والاستخلاف",
                                 "ساعات الحصة المنفذة بالاستخلاف تُحتسب للمستخلف وحده، ويبقى اسم الأستاذ الأصلي للتتبع."))
        bar = QHBoxLayout()
        add = QPushButton(icon("mdi6.plus"), "تسجيل غياب")
        add.setObjectName("Primary")
        add.clicked.connect(self.add)
        dele = QPushButton(icon("mdi6.delete-outline"), "حذف الغياب")
        dele.clicked.connect(self.delete)
        self.filter = QComboBox()
        self.filter.addItems(["الغيابات الحالية والقادمة", "كل الغيابات"])
        self.filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(add)
        bar.addWidget(dele)
        bar.addStretch()
        bar.addWidget(self.filter)
        lay.addLayout(bar)
        split = QSplitter(Qt.Vertical)
        self.abs_t = _table(["الأستاذ", "السبب", "من", "إلى", "الحصص المتأثرة", "بلا مستخلف", "ملاحظات"])
        self.abs_t.itemSelectionChanged.connect(self.load_sessions)
        split.addWidget(self.abs_t)
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 6, 0, 0)
        h = QHBoxLayout()
        lab = QLabel("الحصص المتأثرة بالغياب المحدد")
        lab.setObjectName("SectionTitle")
        h.addWidget(lab)
        h.addStretch()
        sub = QPushButton(icon("mdi6.account-switch"), "تعيين مستخلف…")
        sub.clicked.connect(self.substitute)
        auto = QPushButton(icon("mdi6.auto-fix"), "اقتراح تلقائي لكل الحصص")
        auto.clicked.connect(self.auto_assign)
        done = QPushButton(icon("mdi6.check"), "تسجيل كمنجزة")
        done.clicked.connect(lambda: self._status("done"))
        canc = QPushButton(icon("mdi6.cancel"), "إلغاء الحصة")
        canc.clicked.connect(lambda: self._status("cancelled"))
        post = QPushButton(icon("mdi6.clock-outline"), "تأجيل")
        post.clicked.connect(lambda: self._status("postponed"))
        for b in (sub, auto, done, post, canc):
            h.addWidget(b)
        wl.addLayout(h)
        self.ses_t = _table(["التاريخ", "التوقيت", "المادة", "الأفواج", "الأستاذ الأصلي", "المستخلف", "الحالة"])
        wl.addWidget(self.ses_t)
        split.addWidget(w)
        lay.addWidget(split, 1)
        ctx.data_changed.connect(lambda wh: self.refresh() if wh in ("*", "absences", "sessions", "teachers") else None)
        self.refresh()

    def refresh(self):
        db = self.ctx.db
        cond = "" if self.filter.currentIndex() == 1 else f"WHERE a.end_date>='{iso(date.today())}'"
        rows = db.q(f"""SELECT a.*, t.full_name FROM absences a JOIN teachers t ON t.id=a.teacher_id {cond}
                        ORDER BY a.start_date DESC""")
        self.abs_t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            n = db.scalar("SELECT COUNT(*) FROM sessions WHERE teacher_id=? AND date BETWEEN ? AND ?",
                          (r["teacher_id"], r["start_date"], r["end_date"]), 0)
            unc = db.scalar("""SELECT COUNT(*) FROM sessions WHERE teacher_id=? AND date BETWEEN ? AND ?
                               AND substitute_id IS NULL AND status='planned'""",
                            (r["teacher_id"], r["start_date"], r["end_date"]), 0)
            vals = [r["full_name"], r["reason"], r["start_date"], r["end_date"], n, unc, r["notes"] or ""]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j == 0:
                    it.setData(Qt.UserRole, r["id"])
                self.abs_t.setItem(i, j, it)
        self.load_sessions()

    def current_absence(self):
        r = self.abs_t.currentRow()
        return self.abs_t.item(r, 0).data(Qt.UserRole) if r >= 0 and self.abs_t.item(r, 0) else None

    def load_sessions(self):
        db = self.ctx.db
        aid = self.current_absence()
        self.ses_t.setRowCount(0)
        if not aid:
            return
        a = db.one("SELECT * FROM absences WHERE id=?", (aid,))
        rows = db.q("""SELECT s.*, sub.name sname, t.full_name tname, st.full_name stname,
                              (SELECT GROUP_CONCAT(sec.short||'/'||g.name, '، ') FROM session_groups sg JOIN groups_ g ON g.id=sg.group_id
                               JOIN sections sec ON sec.id=g.section_id WHERE sg.session_id=s.id) gt
                       FROM sessions s JOIN subjects sub ON sub.id=s.subject_id LEFT JOIN teachers t ON t.id=s.teacher_id
                       LEFT JOIN teachers st ON st.id=s.substitute_id
                       WHERE s.teacher_id=? AND s.date BETWEEN ? AND ? ORDER BY s.date, s.start_min""",
                    (a["teacher_id"], a["start_date"], a["end_date"]))
        self.ses_t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["date"], f"{hm(r['start_min'])}–{hm(r['end_min'])}", r["sname"], r["gt"] or "", r["tname"] or "",
                    r["stname"] or "— لم يُعيَّن —", STATUS_LABELS[r["status"]]]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j == 0:
                    it.setData(Qt.UserRole, r["id"])
                self.ses_t.setItem(i, j, it)

    def _sid(self):
        r = self.ses_t.currentRow()
        return self.ses_t.item(r, 0).data(Qt.UserRole) if r >= 0 and self.ses_t.item(r, 0) else None

    def add(self):
        from ..teacher_profile import add_leave
        add_leave(self.ctx, self)

    def delete(self):
        aid = self.current_absence()
        if aid and confirm(self, "حذف هذا الغياب؟ (لا تتغير الحصص المسجلة)", danger=True):
            A.delete_absence(self.ctx.db, aid)
            self.ctx.changed("absences")

    def substitute(self):
        aid = self.current_absence()
        if not aid:
            info(self, "اختر الغياب من القائمة العلوية.")
            return
        from ..teacher_profile import SubstitutionDialog
        SubstitutionDialog(self.ctx, aid, self).exec()

    def auto_assign(self):
        aid = self.current_absence()
        if not aid:
            return
        res = A.auto_assign(self.ctx.db, aid)
        self.ctx.changed("sessions")
        n, miss = len(res["assigned"]), len(res["unassigned"])
        info(self, f"عُيّن معوّض لـ {n} حصة." + (f"\n{miss} حصة بلا أستاذ متفرغ: تبقى في مكانها «بدون أستاذ»." if miss else ""))

    def _status(self, st):
        sid = self._sid()
        if sid:
            T.set_status(self.ctx.db, sid, st)
            self.ctx.changed("sessions")
