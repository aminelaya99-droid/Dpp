"""ملف الأستاذ (كل المعلومات عليه) ونافذة التعويض عند الإجازة."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFrame, QGridLayout,
                               QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
                               QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..exporters import official as O
from ..services import absences as A
from ..services import teachers as TS
from ..services.grid import week_number
from ..utils import DAY_NAMES, STATUS_LABELS, hm, iso, to_date, week_start
from . import theme
from .widgets import FormDialog, confirm, error, icon, info


def _table(headers, stretch_last=True):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(stretch_last)
    return t


def _fill(t: QTableWidget, rows: list[list], data=None):
    t.setSortingEnabled(False)
    t.setRowCount(len(rows))
    for i, r in enumerate(rows):
        for j, v in enumerate(r):
            if isinstance(v, float):
                v = f"{v:g}"
            it = QTableWidgetItem("" if v is None else str(v))
            if j == 0 and data is not None:
                it.setData(Qt.UserRole, data[i])
            if isinstance(r[j], (int, float)):
                it.setTextAlignment(Qt.AlignCenter)
            t.setItem(i, j, it)
    t.resizeColumnsToContents()
    t.setSortingEnabled(True)


def _stat(title, value, sub=""):
    f = QFrame()
    f.setObjectName("Card")
    v = QVBoxLayout(f)
    v.setContentsMargins(12, 8, 12, 8)
    a = QLabel(title)
    a.setObjectName("Muted")
    b = QLabel(str(value))
    fnt = QFont()
    fnt.setPointSize(17)
    fnt.setBold(True)
    b.setFont(fnt)
    v.addWidget(a)
    v.addWidget(b)
    if sub:
        c = QLabel(sub)
        c.setObjectName("Muted")
        c.setWordWrap(True)
        v.addWidget(c)
    return f


def _searchable(cb: QComboBox):
    """قائمة يُكتب فيها للبحث في كل الأساتذة (يكفي جزء من الاسم)."""
    from PySide6.QtWidgets import QCompleter
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    cb.lineEdit().setPlaceholderText("اكتب للبحث عن أي أستاذ…")
    comp = QCompleter(cb.model(), cb)
    comp.setFilterMode(Qt.MatchContains)
    comp.setCaseSensitivity(Qt.CaseInsensitive)
    comp.setCompletionMode(QCompleter.PopupCompletion)
    cb.setCompleter(comp)

    def fix():
        i = cb.findText(cb.currentText())
        if i < 0:
            cb.setCurrentIndex(cb.currentIndex())
            cb.setEditText(cb.itemText(cb.currentIndex()))
    cb.lineEdit().editingFinished.connect(fix)


# ====================================================================== نافذة التعويض
class SubstitutionDialog(QDialog):
    """حصص الأستاذ الغائب في الفترة + اقتراح من يعوّضه في كل حصة."""

    def __init__(self, ctx, absence_id: int, parent=None):
        super().__init__(parent)
        self.ctx, self.db, self.aid = ctx, ctx.db, absence_id
        a = self.db.one("""SELECT a.*, t.full_name FROM absences a JOIN teachers t ON t.id=a.teacher_id
                           WHERE a.id=?""", (absence_id,))
        self.setWindowTitle(f"التعويض — {a['full_name']} ({a['reason']})")
        self.resize(1080, 560)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"<b>{a['full_name']}</b> — {a['reason']} من {a['start_date']} إلى {a['end_date']}. "
                           "اختر المعوّض لكل حصة (المقترحون: من درّس المادة لنفس القسم، ثم من يدرّسها، ثم نفس "
                           "الاختصاص، ثم أي أستاذ متفرغ — والأقل ساعات أولاً). الحصة بلا معوّض تبقى في مكانها "
                           "«بدون أستاذ» وتظهر بالأحمر في الجدول."))
        self.table = _table(["التاريخ", "اليوم", "التوقيت", "المادة", "القسم", "المعوّض الحالي", "اختيار المعوّض"])
        v.addWidget(self.table, 1)
        bar = QHBoxLayout()
        b_auto = QPushButton(icon("mdi6.auto-fix"), "اقتراح تلقائي للكل")
        b_auto.clicked.connect(self.auto)
        bar.addWidget(b_auto)
        b_clear = QPushButton(icon("mdi6.account-remove-outline"), "بدون معوّض للكل")
        b_clear.clicked.connect(self.clear_all)
        bar.addWidget(b_clear)
        bar.addStretch()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        bar.addWidget(self.status)
        bb = QDialogButtonBox()
        b_ok = bb.addButton("حفظ التعويضات", QDialogButtonBox.AcceptRole)
        b_ok.setObjectName("Primary")
        bb.addButton("إغلاق", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.save)
        bb.rejected.connect(self.reject)
        bar.addWidget(bb)
        v.addLayout(bar)
        self.load()

    def load(self):
        rows = self.db.q("""SELECT s.*, sub.name sname, st.full_name stname,
                                   (SELECT GROUP_CONCAT(DISTINCT sec.short) FROM session_groups sg
                                    JOIN groups_ g ON g.id=sg.group_id JOIN sections sec ON sec.id=g.section_id
                                    WHERE sg.session_id=s.id) secs
                            FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                            LEFT JOIN teachers st ON st.id=s.substitute_id
                            JOIN absences a ON a.id=? AND s.teacher_id=a.teacher_id
                            WHERE s.date BETWEEN a.start_date AND a.end_date AND s.status='planned'
                            AND COALESCE(sub.kind,'teach')<>'nonteach' ORDER BY s.date, s.start_min""", (self.aid,))
        self.rows = [dict(r) for r in rows]
        t = self.table
        t.setRowCount(len(self.rows))
        self.combos = []
        for i, r in enumerate(self.rows):
            d = to_date(r["date"])
            vals = [r["date"], DAY_NAMES[(d.weekday() + 1) % 7], f"{hm(r['start_min'])} - {hm(r['end_min'])}",
                    r["sname"], r["secs"] or "", r["stname"] or "— بدون —"]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                if j == 5 and not r["stname"]:
                    it.setForeground(QColor(theme.CURRENT["bad"]))
                t.setItem(i, j, it)
            cb = QComboBox()
            cb.addItem("— بدون معوّض (تبقى في مكانها) —", None)
            sugg = A.suggest_substitutes(self.db, r["id"], int(self.db.get_setting("sub_limit", "25") or 25))
            for c in sugg:
                cb.addItem(f"{c['rank'] + ' ' if c['rank'] else ''}{c['name']} · {c['reason']} · "
                           f"{c['week_load']:g} سا هذا الأسبوع", c["id"])
            # كل الأساتذة الآخرين للبحث (المشغول أو الغائب يُعلَّم، ويمكن اختياره)
            shown = {c["id"] for c in sugg} | {r["teacher_id"]}
            busy = A._busy_teachers(self.db, r["date"], r["start_min"], r["end_min"], r["id"])
            absent = A.absent_teachers(self.db, r["date"])
            others = [x for x in self.db.q("SELECT id, full_name, rank FROM teachers WHERE active=1 ORDER BY full_name")
                      if x["id"] not in shown]
            if others:
                cb.insertSeparator(cb.count())
                for x in others:
                    flag = " · غائب" if x["id"] in absent else (" · مشغول في هذا الوقت" if x["id"] in busy else "")
                    cb.addItem(f"{x['rank'] + ' ' if x['rank'] else ''}{x['full_name']}{flag}", x["id"])
            _searchable(cb)
            if r["substitute_id"]:
                k = cb.findData(r["substitute_id"])
                if k < 0:
                    cb.addItem(f"{r['stname']} (الحالي)", r["substitute_id"])
                    k = cb.count() - 1
                cb.setCurrentIndex(k)
            cb.setMinimumWidth(380)
            t.setCellWidget(i, 6, cb)
            self.combos.append(cb)
        t.resizeColumnsToContents()
        n_none = sum(1 for cb in self.combos if cb.count() == 1)
        self.status.setText(f"{len(self.rows)} حصة" + (f" · {n_none} بلا أي أستاذ متفرغ" if n_none else ""))

    def auto(self):
        for cb in self.combos:
            cb.setCurrentIndex(1 if cb.count() > 1 else 0)

    def clear_all(self):
        for cb in self.combos:
            cb.setCurrentIndex(0)

    def save(self):
        n = 0
        try:
            for r, cb in zip(self.rows, self.combos):
                new = cb.currentData()
                if new != r["substitute_id"]:
                    A.assign_substitute(self.db, r["id"], new, force=True)
                    n += 1
        except Exception as e:
            error(self, f"تعذر الحفظ: {e}")
            return
        self.ctx.changed("sessions")
        info(self, f"تم حفظ {n} تعويض." if n else "لا تغيير.")
        self.accept()


def add_leave(ctx, parent, teacher_id: int | None = None) -> int | None:
    db = ctx.db
    fields = [("teacher_id", "الأستاذ", "combo",
               [(r[0], r[1]) for r in db.q("SELECT id, full_name FROM teachers ORDER BY full_name")]),
              ("reason", "السبب", "combo", [(x, x) for x in A.REASONS]),
              ("start", "من", "date", None), ("end", "إلى", "date", None),
              ("notes", "ملاحظات / وثائق", "multiline", None)]
    d = FormDialog(parent, "تسجيل إجازة / غياب", fields,
                   {"teacher_id": teacher_id, "start": iso(date.today()), "end": iso(date.today() + timedelta(days=1))},
                   required=("teacher_id",))
    if d.exec() != QDialog.Accepted:
        return None
    v = d.values()
    try:
        aid = A.add_absence(db, v["teacher_id"], v["reason"], v["start"], v["end"], v["notes"])
    except ValueError as e:
        error(parent, str(e))
        return None
    ctx.changed("absences")
    if A.affected_sessions(db, aid) and confirm(parent, "عنده حصص في هذه الفترة. تحب تختار من يعوّضه الآن؟"):
        SubstitutionDialog(ctx, aid, parent).exec()
    return aid


# ====================================================================== ملف الأستاذ
class TeacherProfileDialog(QDialog):
    def __init__(self, ctx, teacher_id: int, parent=None, ws=None):
        super().__init__(parent)
        self.ctx, self.db, self.tid = ctx, ctx.db, teacher_id
        self.ws = week_start(ws or date.today())
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1180, 800)
        self.lay = QVBoxLayout(self)
        self.head = QHBoxLayout()
        self.lay.addLayout(self.head)
        self.stats = QGridLayout()
        self.lay.addLayout(self.stats)
        self.tabs = QTabWidget()
        self.lay.addWidget(self.tabs, 1)
        # الأسابيع
        self.t_weeks = _table(["الأسبوع", "من", "الساعات", "منها المنجزة", "كمعوّض", "عوّضه غيره", "مؤجلة",
                               "الأقسام", "المواد"])
        self.t_weeks.doubleClicked.connect(self._open_week_row)
        self.tabs.addTab(self.t_weeks, icon("mdi6.calendar-week"), "ساعات كل أسبوع")
        # الأقسام والمواد
        self.t_pairs = _table(["القسم", "المادة", "الساعات", "المنجزة", "عدد الأسابيع", "آخر حصة"])
        self.tabs.addTab(self.t_pairs, icon("mdi6.google-classroom"), "الأقسام والمواد")
        # البرنامج الأسبوعي (نفس الورقة الرسمية)
        w = QWidget()
        wl = QVBoxLayout(w)
        nav = QHBoxLayout()
        for ic, tip, d in (("mdi6.chevron-right", "الأسبوع السابق", -7), ("mdi6.chevron-left", "الأسبوع التالي", 7)):
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, d=d: self.set_week(self.ws + timedelta(days=d)))
            nav.addWidget(b)
        self.week_lbl = QLabel()
        self.week_lbl.setObjectName("SectionTitle")
        nav.addWidget(self.week_lbl)
        nav.addStretch()
        bp = QPushButton(icon("mdi6.printer-eye"), "طباعة / معاينة")
        bp.clicked.connect(self.print_week)
        nav.addWidget(bp)
        wl.addLayout(nav)
        from .sheet_view import PaperView
        self.paper = PaperView()
        wl.addWidget(self.paper, 1)
        self.tabs.addTab(w, icon("mdi6.table-large"), "البرنامج الأسبوعي")
        # الإجازات والتعويض
        w2 = QWidget()
        l2 = QVBoxLayout(w2)
        b2 = QHBoxLayout()
        for text, ic, fn in (("تسجيل إجازة…", "mdi6.calendar-remove-outline", self.add_leave),
                             ("اختيار المعوّضين…", "mdi6.account-switch-outline", self.substitutions),
                             ("حذف الإجازة", "mdi6.delete-outline", self.del_leave)):
            b = QPushButton(icon(ic), text)
            b.clicked.connect(fn)
            b2.addWidget(b)
        b2.addStretch()
        l2.addLayout(b2)
        self.t_abs = _table(["السبب", "من", "إلى", "الحصص", "بلا معوّض", "ملاحظات"])
        self.t_abs.doubleClicked.connect(lambda *_: self.substitutions())
        l2.addWidget(self.t_abs)
        lab = QLabel("الحصص التي عوّض فيها هذا الأستاذ غيره")
        lab.setObjectName("SectionTitle")
        l2.addWidget(lab)
        self.t_subs = _table(["التاريخ", "التوقيت", "المادة", "القسم", "بدلاً من"])
        l2.addWidget(self.t_subs)
        self.tabs.addTab(w2, icon("mdi6.account-switch-outline"), "الإجازات والتعويض")
        ctx.data_changed.connect(self._changed)
        self.reload()
        self.set_week(self.ws)

    def _changed(self, w):
        if w in ("*", "sessions", "sessions_grid", "absences", "teachers"):
            self.reload()
            self.set_week(self.ws)

    def reload(self):
        p = self.p = TS.profile(self.db, self.tid)
        t = p["teacher"]
        while self.head.count():
            it = self.head.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        title = QLabel(f"<span style='font-size:18pt; font-weight:700'>{t['full_name']}</span>"
                       f"<br><span style='color:{theme.CURRENT['muted']}'>"
                       f"{' · '.join(x for x in (t['rank'], t['cat'], t['specialty'], 'نشط' if t['active'] else 'غير نشط') if x)}"
                       f"</span>")
        self.head.addWidget(title)
        if p["absent_today"]:
            a = p["absent_today"]
            warn = QLabel(f"<b style='color:{theme.CURRENT['bad']}'>في {a['reason']} حتى {a['end_date']}</b>")
            self.head.addWidget(warn)
        self.head.addStretch()
        for text, ic, fn in (("تعديل البيانات", "mdi6.pencil", self.edit),
                             ("تسجيل إجازة", "mdi6.calendar-remove-outline", self.add_leave),
                             ("طباعة البرنامج", "mdi6.printer-eye", self.print_week)):
            b = QPushButton(icon(ic), text)
            b.clicked.connect(fn)
            self.head.addWidget(b)
        self.setWindowTitle(f"ملف الأستاذ — {t['full_name']}")
        while self.stats.count():
            it = self.stats.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        mx = t["max_week_hours"] or 0
        cards = [_stat("هذا الأسبوع", f"{p['this_week']:g} سا", f"الحد الأقصى {mx:g} سا" if mx else ""),
                 _stat("المنجز منذ البداية", f"{p['done_total']:g} سا", f"متوسط {p['avg_week']:g} سا/أسبوع"),
                 _stat("مبرمج قادم", f"{p['planned_future']:g} سا"),
                 _stat("الأقسام", len(p["sections"]), "، ".join(p["sections"][:6]) + ("…" if len(p["sections"]) > 6 else "")),
                 _stat("المواد", len(p["subjects"]), "، ".join(p["subjects"][:4]) + ("…" if len(p["subjects"]) > 4 else "")),
                 _stat("التعويض", f"{p['as_sub_total']:g} سا", f"عوّضه غيره {p['replaced_total']:g} سا")]
        for i, c in enumerate(cards):
            self.stats.addWidget(c, 0, i)
        # جداول
        self.week_rows = p["weeks"]
        _fill(self.t_weeks, [[week_number(self.db, to_date(w["week"])), to_date(w["week"]).strftime("%d/%m/%Y"),
                              w["planned"], w["done"], w["as_sub"] or "", w["replaced"] or "", w["postponed"] or "",
                              "، ".join(w["sections"]), "، ".join(w["subjects"])] for w in self.week_rows],
              [w["week"] for w in self.week_rows])
        _fill(self.t_pairs, [[x["section"], x["subject"], x["total"], x["done"], x["weeks"], x["last"]]
                             for x in p["pairs"]])
        abs_rows, ids = [], []
        for a in p["absences"]:
            n = self.db.scalar("""SELECT COUNT(*) FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                                  WHERE s.teacher_id=? AND s.date BETWEEN ? AND ? AND s.status IN ('planned','done')
                                  AND COALESCE(sub.kind,'teach')<>'nonteach'""",
                               (self.tid, a["start_date"], a["end_date"]), 0)
            un = self.db.scalar("""SELECT COUNT(*) FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                                   WHERE s.teacher_id=? AND s.date BETWEEN ? AND ? AND s.status='planned'
                                   AND s.substitute_id IS NULL AND COALESCE(sub.kind,'teach')<>'nonteach'""",
                                (self.tid, a["start_date"], a["end_date"]), 0)
            abs_rows.append([a["reason"], a["start_date"], a["end_date"], n, un, a["notes"] or ""])
            ids.append(a["id"])
        _fill(self.t_abs, abs_rows, ids)
        subs = self.db.q("""SELECT s.date, s.start_min, s.end_min, sub.name sname, t.full_name tname,
                                   (SELECT GROUP_CONCAT(DISTINCT sec.short) FROM session_groups sg
                                    JOIN groups_ g ON g.id=sg.group_id JOIN sections sec ON sec.id=g.section_id
                                    WHERE sg.session_id=s.id) secs
                            FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                            LEFT JOIN teachers t ON t.id=s.teacher_id
                            WHERE s.substitute_id=? ORDER BY s.date DESC""", (self.tid,))
        _fill(self.t_subs, [[r["date"], f"{hm(r['start_min'])} - {hm(r['end_min'])}", r["sname"], r["secs"] or "",
                             r["tname"] or ""] for r in subs])

    def set_week(self, ws):
        from .sheet_view import SheetScene
        self.ws = week_start(ws)
        n = week_number(self.db, self.ws)
        self.week_lbl.setText(f"الأسبوع {n} — من {self.ws.strftime('%d/%m/%Y')} إلى "
                              f"{(self.ws + timedelta(days=6)).strftime('%d/%m/%Y')}")
        self.sheet = O.build_teacher_sheet(self.db, self.tid, self.ws)
        self.scene = SheetScene(self.sheet, True, False)
        self.paper.set_scene(self.scene)

    def _open_week_row(self, idx):
        it = self.t_weeks.item(idx.row(), 0)
        if it is not None and it.data(Qt.UserRole):
            self.set_week(to_date(it.data(Qt.UserRole)))
            self.tabs.setCurrentIndex(2)

    def print_week(self):
        from .sheet_view import open_print
        open_print(self.ctx, self.ws, self, "teacher", self.tid)

    def edit(self):
        page = None
        try:
            from .pages.entities import SPECS, EntityPage
            page = EntityPage(self.ctx, SPECS["teachers"])
            for i in range(page.table.rowCount()):
                if page.table.item(i, 0).data(Qt.UserRole) == self.tid:
                    page.table.selectRow(i)
                    break
            page.edit()
        finally:
            if page is not None:
                page.deleteLater()
        self.reload()

    def _abs_id(self):
        r = self.t_abs.currentRow()
        it = self.t_abs.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def add_leave(self):
        if add_leave(self.ctx, self, self.tid):
            self.tabs.setCurrentIndex(3)

    def substitutions(self):
        aid = self._abs_id()
        if not aid:
            if self.t_abs.rowCount() == 1:
                aid = self.t_abs.item(0, 0).data(Qt.UserRole)
            else:
                info(self, "اختر الإجازة من القائمة.")
                return
        SubstitutionDialog(self.ctx, aid, self).exec()

    def del_leave(self):
        aid = self._abs_id()
        if aid and confirm(self, "حذف هذه الإجازة؟ (التعويضات المسجلة تبقى)", danger=True):
            A.delete_absence(self.db, aid)
            self.ctx.changed("absences")


def open_profile(ctx, teacher_id: int, parent=None, ws=None):
    if not teacher_id:
        return None
    d = TeacherProfileDialog(ctx, teacher_id, parent, ws)
    d.exec()
    return d


__all__ = ["TeacherProfileDialog", "SubstitutionDialog", "open_profile", "add_leave", "STATUS_LABELS"]
