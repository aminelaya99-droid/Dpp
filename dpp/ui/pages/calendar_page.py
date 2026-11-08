"""رزنامة التكوين: العطل، الامتحانات، المواعيد، التنبيهات."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import (QAbstractItemView, QCalendarWidget, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...services import calendar as C
from ...utils import iso, to_date
from .. import theme
from ..context import AppContext
from ..widgets import FormDialog, confirm, error, icon, info, page_title

KIND_COLORS = {"holiday": "#C0392B", "inst_holiday": "#E67E22", "break": "#B7950B", "exam": "#8E44AD",
               "final_exam": "#6C3483", "evaluation": "#2980B9", "graduation": "#16A085", "meeting": "#2C3E50",
               "report": "#7F8C8D", "admin": "#34495E", "phase": "#27AE60", "custom": "#95A5A6"}


class EventDialog(QDialog):
    """إضافة/تعديل حدث مع اختيار الأقسام المعنية بالحضور من شجرة (تكوين ← طور ← أقسام)."""

    def __init__(self, page, title: str, values: dict, sections: list[int] | None = None):
        super().__init__(page)
        from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem
        self.setWindowTitle(title)
        self.resize(820, 560)
        self.db = page.ctx.db
        lay = QHBoxLayout(self)
        left = QVBoxLayout()
        fields = [f for f in page._fields() if f[0] != "formation_id"]
        self.inner = FormDialog(self, title, fields, values, required=("title",))
        self.inner.setWindowFlags(Qt.Widget)
        # نستعمل حقول النافذة العامة كجزء من هذه النافذة، وأزرارها هي أزرار الحفظ
        left.addWidget(self.inner)
        lay.addLayout(left, 3)
        right = QVBoxLayout()
        lab = QLabel("المعنيون بالحضور")
        lab.setObjectName("SectionTitle")
        right.addWidget(lab)
        hint = QLabel("اختر الأقسام (أو طوراً كاملاً أو تكويناً كاملاً). بلا اختيار = كل التكوينات.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        right.addWidget(hint)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        chosen = set(sections or [])
        fsel = values.get("formation_id")
        for f in self.db.q("SELECT id, name FROM formations WHERE archived=0 ORDER BY id"):
            fi = QTreeWidgetItem([f["name"]])
            fi.setFlags(fi.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
            fi.setCheckState(0, Qt.Unchecked)
            self.tree.addTopLevelItem(fi)
            for lv in self.db.q("SELECT id, code, name FROM levels WHERE formation_id=? ORDER BY COALESCE(sort,99), id",
                                (f["id"],)):
                li = QTreeWidgetItem([f"{lv['code'] or ''} — {lv['name']}"])
                li.setFlags(li.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                fi.addChild(li)
                for sc in self.db.q("SELECT id, short FROM sections WHERE level_id=? ORDER BY sort, id", (lv["id"],)):
                    si = QTreeWidgetItem([sc["short"]])
                    si.setFlags(si.flags() | Qt.ItemIsUserCheckable)
                    si.setData(0, Qt.UserRole, sc["id"])
                    si.setCheckState(0, Qt.Checked if (sc["id"] in chosen or (not chosen and fsel == f["id"]))
                                     else Qt.Unchecked)
                    li.addChild(si)
            fi.setExpanded(fi.checkState(0) != Qt.Unchecked)
        right.addWidget(self.tree, 1)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        right.addWidget(self.count)
        self.tree.itemChanged.connect(lambda *_: self._count())
        lay.addLayout(right, 2)
        self._count()
        self.inner.accepted.connect(self.accept)
        self.inner.rejected.connect(self.reject)

    def _leaves(self):
        out = []
        for i in range(self.tree.topLevelItemCount()):
            f = self.tree.topLevelItem(i)
            for j in range(f.childCount()):
                lv = f.child(j)
                for k in range(lv.childCount()):
                    out.append((i, lv.child(k)))
        return out

    def _count(self):
        n = sum(1 for _i, it in self._leaves() if it.checkState(0) == Qt.Checked)
        self.count.setText(f"{n} قسم محدد" if n else "لا قسم محدد: الحدث يخص كل التكوينات")

    def values(self) -> dict:
        v = self.inner.values()
        leaves = self._leaves()
        checked = [(i, it.data(0, Qt.UserRole)) for i, it in leaves if it.checkState(0) == Qt.Checked]
        fids = {i for i, _s in checked}
        rows = self.db.q("SELECT id FROM formations WHERE archived=0 ORDER BY id")
        v["formation_id"] = rows[next(iter(fids))]["id"] if len(fids) == 1 else None
        total_in = {i: sum(1 for j, _ in leaves if j == i) for i in fids}
        # تكوين كامل محدد: لا داعي لحفظ أقسامه واحداً واحداً
        whole = len(fids) == 1 and len(checked) == total_in[next(iter(fids))]
        v["sections"] = [] if whole else [s for _i, s in checked]
        return v


class CalendarPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("رزنامة التكوين",
                                 "العطل والامتحانات والتوقفات تحجب الجدولة تلقائياً (يمكن تغيير ذلك لكل حدث)."))
        bar = QHBoxLayout()
        for text, ic, fn, primary in [("إضافة حدث", "mdi6.plus", self.add, True), ("تعديل", "mdi6.pencil", self.edit, False),
                                      ("حذف", "mdi6.delete-outline", self.delete, False),
                                      ("إعادة برمجة الحصص المتأثرة", "mdi6.calendar-refresh", self.reschedule, False)]:
            b = QPushButton(icon(ic), text)
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        self.cal = QCalendarWidget()
        self.cal.setFirstDayOfWeek(Qt.Sunday)
        self.cal.setGridVisible(True)
        self.cal.selectionChanged.connect(self._day_selected)
        self.cal.currentPageChanged.connect(lambda *_: self._paint())
        split.addWidget(self.cal)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        self.day_lbl = QLabel()
        self.day_lbl.setObjectName("SectionTitle")
        rl.addWidget(self.day_lbl)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["العنوان", "النوع", "من", "إلى", "المعنيون بالحضور", "يحجب الجدولة",
                                              "التنبيه قبل (أيام)"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        rl.addWidget(self.table)
        split.addWidget(right)
        split.setSizes([380, 700])
        lay.addWidget(split, 1)
        ctx.data_changed.connect(lambda w: self.refresh() if w in ("*", "calendar_events") else None)
        self.refresh()

    def refresh(self, select: int | None = None):
        db = self.ctx.db
        rows = db.q("""SELECT e.*, f.name fname FROM calendar_events e LEFT JOIN formations f ON f.id=e.formation_id
                       ORDER BY e.start_date DESC""")
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["title"], C.EVENT_KINDS.get(r["kind"], r["kind"]), r["start_date"], r["end_date"],
                    C.attendees_label(db, r["id"], r["fname"]),
                    "نعم" if r["blocks_scheduling"] else "", r["remind_days"] or ""]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if j == 0:
                    it.setData(Qt.UserRole, r["id"])
                if j == 1:
                    it.setForeground(QColor(KIND_COLORS.get(r["kind"], "#555")))
                self.table.setItem(i, j, it)
            if select and r["id"] == select:
                self.table.selectRow(i)
                self.table.scrollToItem(self.table.item(i, 0))
        self._paint()

    def _paint(self):
        self.cal.setDateTextFormat(QDate(), QTextCharFormat())
        for r in self.ctx.db.q("SELECT kind, start_date, end_date FROM calendar_events"):
            d, e = to_date(r["start_date"]), to_date(r["end_date"])
            fmt = QTextCharFormat()
            c = QColor(KIND_COLORS.get(r["kind"], "#999"))
            c.setAlpha(80)
            fmt.setBackground(c)
            fmt.setFontWeight(700)
            n = 0
            while d <= e and n < 400:
                self.cal.setDateTextFormat(QDate(d.year, d.month, d.day), fmt)
                d += timedelta(days=1)
                n += 1

    def _day_selected(self):
        d = self.cal.selectedDate().toPython()
        evs = self.ctx.db.q("SELECT title, kind FROM calendar_events WHERE start_date<=? AND end_date>=?", (iso(d), iso(d)))
        self.day_lbl.setText(d.strftime("%d/%m/%Y") + ("  —  " + "، ".join(f"{e['title']}" for e in evs) if evs else ""))

    def _fields(self):
        db = self.ctx.db
        return [("title", "العنوان", "text", None), ("kind", "النوع", "combo", list(C.EVENT_KINDS.items())),
                ("start_date", "من", "date", None), ("end_date", "إلى", "date", None),
                ("formation_id", "التكوين", "combo", [(None, "كل التكوينات")] +
                 [(r[0], r[1]) for r in db.q("SELECT id, name FROM formations ORDER BY start_date DESC")]),
                ("importance", "الأهمية", "combo", [(1, "عادية"), (2, "مهمة"), (3, "عالية جداً")]),
                ("blocks_scheduling", "يحجب الجدولة", "bool", None),
                ("remind_days", "التنبيه قبل (أيام، مفصولة بفواصل)", "text", "30,14,7,3,1"),
                ("description", "الوصف", "multiline", None)]

    def add(self):
        d = self.cal.selectedDate().toString("yyyy-MM-dd")
        dlg = EventDialog(self, "إضافة حدث",
                          {"start_date": d, "end_date": d, "kind": "exam", "formation_id": self.ctx.formation_id,
                           "remind_days": "7,3,1", "blocks_scheduling": 1})
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            try:
                eid = C.add_event(self.ctx.db, v["title"], v["kind"], v["start_date"], v["end_date"], v["formation_id"],
                                  None, v["description"], v["importance"], bool(v["blocks_scheduling"]),
                                  v["remind_days"] or "")
                C.set_event_sections(self.ctx.db, eid, v["sections"])
            except ValueError as e:
                error(self, str(e))
                return
            self._after_change()
            self.refresh(select=eid)
            self.ctx.status.emit(f"حُفظ الحدث «{v['title']}» وأُضيف إلى القائمة.")

    def _eid(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.UserRole) if r >= 0 and self.table.item(r, 0) else None

    def edit(self):
        eid = self._eid()
        if not eid:
            info(self, "اختر حدثاً.")
            return
        row = dict(self.ctx.db.one("SELECT * FROM calendar_events WHERE id=?", (eid,)))
        dlg = EventDialog(self, "تعديل حدث", row, C.event_sections(self.ctx.db, eid))
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            if v["end_date"] < v["start_date"]:
                error(self, "تاريخ النهاية يسبق البداية.")
                return
            secs = v.pop("sections")
            C.update_event(self.ctx.db, eid, **v)
            C.set_event_sections(self.ctx.db, eid, secs)
            self._after_change()
            self.refresh(select=eid)

    def delete(self):
        eid = self._eid()
        if eid and confirm(self, "حذف هذا الحدث؟", danger=True):
            C.delete_event(self.ctx.db, eid)
            self._after_change()

    def _after_change(self):
        self.ctx.changed("calendar_events")
        fids = self.ctx.formation_ids()
        if not fids:
            return
        from ...services.timetables import reschedule_after_calendar_change
        rs = [reschedule_after_calendar_change(self.ctx.db, f, apply=False) for f in fids]
        r = {"removed": sum(x["removed"] for x in rs), "needs_confirmation": [y for x in rs for y in x["needs_confirmation"]]}
        affected = len(r["needs_confirmation"])
        if r["removed"] or affected:
            if confirm(self, f"تعديل الرزنامة أثّر في حصص مبرمجة:\n• {r['removed']} حصة مولدة آلياً في مسودات\n"
                             f"• {affected} حصة في جداول معتمدة أو يدوية (لن تُلمس إلا بموافقتك من المخطط)\n\n"
                             "هل تريد إعادة برمجة الحصص المولدة آلياً الآن؟"):
                self.reschedule(skip_confirm=True)

    def reschedule(self, skip_confirm=False):
        fids = self.ctx.formation_ids()
        if not fids:
            return
        if not skip_confirm and not confirm(self, "حذف الحصص المولدة آلياً الواقعة في أيام محجوبة وإعادة برمجة ساعاتها؟"):
            return
        from ...services.timetables import reschedule_after_calendar_change
        rs = [reschedule_after_calendar_change(self.ctx.db, f, apply=True) for f in fids]
        r = dict(rs[0])
        r["removed"] = sum(x["removed"] for x in rs)
        r["needs_confirmation"] = [y for x in rs for y in x["needs_confirmation"]]
        self.ctx.changed("sessions")
        msg = f"حُذفت {r['removed']} حصة من أيام محجوبة."
        if r.get("plan"):
            msg += f"\nأعيدت برمجة {r['plan'].placed} حصة."
            if r["plan"].carried_over:
                msg += f"\nبقيت {sum(r['plan'].carried_over.values()):g} ساعة دون برمجة."
        if r["needs_confirmation"]:
            msg += f"\n{len(r['needs_confirmation'])} حصة معتمدة/يدوية في أيام محجوبة تحتاج قرارك في المخطط."
        info(self, msg)
