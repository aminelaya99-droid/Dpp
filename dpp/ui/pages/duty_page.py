"""صفحة الخفارة والخدمات: الأنواع، التوزيع الآلي العادل واليدوي، الإحصائيات، الطباعة وExcel،
والإدراج في الجدول عند الطلب فقط (نظام منفصل عن البرنامج)."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QColorDialog, QDateEdit, QDialog, QDialogButtonBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QPushButton, QSpinBox, QSplitter, QTableWidget,
                               QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...services import duty as D
from ...utils import DAY_NAMES, iso, weekday_sun0, week_start
from ..widgets import confirm, error, icon, info, page_title


class TypeDialog(QDialog):
    """نوع مناوبة: الاسم، عدد الأقسام في اليوم، الأيام، والأقسام المعنية (أقسام أو أطوار أو سنوات)."""

    def __init__(self, parent, db, t: dict | None = None):
        super().__init__(parent)
        self.db, self.t = db, t or {}
        self.setWindowTitle("نوع مناوبة")
        self.resize(520, 620)
        v = QVBoxLayout(self)
        f = QFormLayout()
        self.name = QLineEdit(self.t.get("name", ""))
        self.name.setPlaceholderText("مثلاً: خفارة، خدمة المطعم…")
        f.addRow("الاسم", self.name)
        self.per = QSpinBox()
        self.per.setRange(1, 20)
        self.per.setValue(int(self.t.get("per_day", 1)))
        self.per.setSuffix(" قسم في اليوم")
        f.addRow("العدد", self.per)
        dh = QHBoxLayout()
        self.days = {}
        for d in range(7):
            cb = QCheckBox(DAY_NAMES[d])
            cb.setChecked(d in (self.t.get("days") or list(range(7))))
            self.days[d] = cb
            dh.addWidget(cb)
        w = QWidget()
        w.setLayout(dh)
        f.addRow("الأيام", w)
        self.color = self.t.get("color") or "#CDB89B"
        self.b_color = QPushButton("اللون")
        self.b_color.clicked.connect(self._pick)
        self._paint()
        f.addRow("", self.b_color)
        self.active = QCheckBox("مفعّل")
        self.active.setChecked(bool(self.t.get("active", 1)))
        f.addRow("", self.active)
        v.addLayout(f)
        g = QGroupBox("الأقسام المعنية (لا شيء محدد = كل الأقسام)")
        gl = QVBoxLayout(g)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        sc = self.t.get("scope") or {}
        years = sorted({r[0] for r in db.q("SELECT DISTINCT year_no FROM levels WHERE year_no IS NOT NULL")})
        if years:
            yr = QTreeWidgetItem(["السنوات"])
            for y in years:
                it = QTreeWidgetItem([f"السنة {y}"])
                it.setData(0, Qt.UserRole, ("y", y))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if y in (sc.get("years") or []) else Qt.Unchecked)
                yr.addChild(it)
            self.tree.addTopLevelItem(yr)
        for lv in db.q("SELECT id, COALESCE(code, name) n FROM levels ORDER BY sort, id"):
            li = QTreeWidgetItem([f"الطور {lv['n']}"])
            li.setData(0, Qt.UserRole, ("l", lv["id"]))
            li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
            li.setCheckState(0, Qt.Checked if lv["id"] in (sc.get("levels") or []) else Qt.Unchecked)
            for s in db.q("SELECT id, short FROM sections WHERE level_id=? ORDER BY sort, id", (lv["id"],)):
                it = QTreeWidgetItem([s["short"]])
                it.setData(0, Qt.UserRole, ("s", s["id"]))
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                it.setCheckState(0, Qt.Checked if s["id"] in (sc.get("sections") or []) else Qt.Unchecked)
                li.addChild(it)
            self.tree.addTopLevelItem(li)
        self.tree.expandToDepth(0)
        gl.addWidget(self.tree)
        v.addWidget(g, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _paint(self):
        self.b_color.setStyleSheet(f"background:{self.color};")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self)
        if c.isValid():
            self.color = c.name()
            self._paint()

    def scope(self) -> dict:
        out = {"sections": [], "levels": [], "years": []}

        def walk(it):
            k = it.data(0, Qt.UserRole)
            if k and it.checkState(0) == Qt.Checked:
                out[{"s": "sections", "l": "levels", "y": "years"}[k[0]]].append(k[1])
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return {k: v for k, v in out.items() if v}

    def _ok(self):
        try:
            self.saved = D.save_type(self.db, self.name.text(), self.per.value(),
                                     [d for d, cb in self.days.items() if cb.isChecked()], self.scope(), self.color,
                                     self.t.get("id"), self.active.isChecked())
        except Exception as e:
            error(self, str(e))
            return
        self.accept()


class PickSections(QDialog):
    """تعيين يدوي: اختيار الأقسام لنوع ويوم (حتى العدد المطلوب)."""

    def __init__(self, parent, db, t: dict, d: date, current: list[int]):
        super().__init__(parent)
        self.setWindowTitle(f"{t['name']} — {DAY_NAMES[weekday_sun0(d)]} {d.strftime('%d/%m/%Y')}")
        self.resize(380, 480)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"اختر {t['per_day']} قسم (التعيين اليدوي لا يغيّره التوزيع الآلي):"))
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث…")
        v.addWidget(self.search)
        self.list = QListWidget()
        st = D.stats(db)
        cnt = {name: c.get(t["id"], 0) for name, c, _tot in st["rows"]}
        for s in D.eligible(db, t):
            it = QListWidgetItem(f"{s['short']}   ({cnt.get(s['short'], 0)} مناوبة)")
            it.setData(Qt.UserRole, s["id"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if s["id"] in current else Qt.Unchecked)
            self.list.addItem(it)
        self.search.textChanged.connect(lambda q: [self.list.item(i).setHidden(q not in self.list.item(i).text())
                                                   for i in range(self.list.count())])
        v.addWidget(self.list, 1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def chosen(self) -> list[int]:
        return [self.list.item(i).data(Qt.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.Checked]


class DutyPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        D.ensure_defaults(self.db)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("الخفارة والخدمات",
                                 "نظام منفصل عن الجدول: وزّع المناوبات آلياً بتناوب عادل أو يدوياً، واطبعها. "
                                 "لا تدخل الجدول إلا بزر «إدراج في الجدول»."))
        bar = QHBoxLayout()
        bar.addWidget(QLabel("من"))
        today = date.today()
        first = today.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        self.d0 = QDateEdit(QDate(first.year, first.month, first.day))
        self.d1 = QDateEdit(QDate(nxt.year, nxt.month, nxt.day).addDays(-1))
        for de in (self.d0, self.d1):
            de.setCalendarPopup(True)
            de.setDisplayFormat("dd/MM/yyyy")
            de.dateChanged.connect(lambda _: self.refresh())
        bar.addWidget(self.d0)
        bar.addWidget(QLabel("إلى"))
        bar.addWidget(self.d1)
        for ic, lab, fn, primary in (("mdi6.auto-fix", "توزيع آلي", self.auto, True),
                                     ("mdi6.eraser", "مسح الآلي", self.clear, False),
                                     ("mdi6.table-arrow-down", "إدراج في الجدول…", self.insert, False),
                                     ("mdi6.printer-eye", "طباعة", self.print_, False),
                                     ("mdi6.file-excel-outline", "Excel", self.xlsx, False)):
            b = QPushButton(icon(ic, "white" if primary else None), lab)
            if primary:
                b.setObjectName("Primary")
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        lay.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("الأنواع"))
        self.types = QListWidget()
        self.types.itemDoubleClicked.connect(lambda _: self.edit_type())
        lv.addWidget(self.types, 1)
        th = QHBoxLayout()
        for ic, tip, fn in (("mdi6.plus", "نوع جديد", self.add_type), ("mdi6.pencil", "تعديل", self.edit_type),
                            ("mdi6.delete-outline", "حذف", self.del_type)):
            b = QPushButton(icon(ic), "")
            b.setToolTip(tip)
            b.clicked.connect(fn)
            th.addWidget(b)
        lv.addLayout(th)
        lv.addWidget(QLabel("الإحصائيات (عدد المناوبات)"))
        self.stats = QTableWidget()
        self.stats.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.stats.verticalHeader().setVisible(False)
        self.stats.setSortingEnabled(True)
        lv.addWidget(self.stats, 2)
        split.addWidget(left)
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.cellDoubleClicked.connect(self._cell)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        split.addWidget(self.table)
        split.setStretchFactor(1, 3)
        split.setSizes([330, 900])
        lay.addWidget(split, 1)
        self.msg = QLabel()
        self.msg.setObjectName("Muted")
        self.msg.setWordWrap(True)
        lay.addWidget(self.msg)
        self.refresh()

    def range(self):
        return self.d0.date().toPython(), self.d1.date().toPython()

    def refresh(self):
        self.ts = D.types(self.db)
        self.types.clear()
        for t in self.ts:
            it = QListWidgetItem(f"{t['name']} · {t['per_day']}/يوم · {D.scope_label(self.db, t['scope'])}"
                                 + ("" if t["active"] else " (موقوف)"))
            it.setData(Qt.UserRole, t["id"])
            it.setForeground(QBrush(QColor(t["color"] or "#888").darker(150)))
            self.types.addItem(it)
        a, b = self.range()
        active = [t for t in self.ts if t["active"]]
        days = []
        d = a
        while d <= b:
            days.append(d)
            d += timedelta(days=1)
        by = {}
        for x in D.assignments(self.db, a, b):
            by.setdefault((x["date"], x["type_id"]), []).append(x)
        t = self.table
        t.clear()
        t.setColumnCount(2 + len(active))
        t.setHorizontalHeaderLabels(["اليوم", "التاريخ"] + [x["name"] for x in active])
        t.setRowCount(len(days))
        for i, d in enumerate(days):
            wd = weekday_sun0(d)
            t.setItem(i, 0, QTableWidgetItem(DAY_NAMES[wd]))
            t.setItem(i, 1, QTableWidgetItem(d.strftime("%d/%m/%Y")))
            for j, ty in enumerate(active):
                xs = by.get((iso(d), ty["id"]), [])
                txt = "، ".join(x["short"] for x in xs)
                it = QTableWidgetItem(txt if wd in ty["days"] else "—")
                it.setData(Qt.UserRole, (iso(d), ty["id"]))
                if xs:
                    col = QColor(ty["color"] or "#CDB89B")
                    col.setAlpha(110)
                    it.setBackground(QBrush(col))
                    if any(x["manual"] for x in xs):
                        f = it.font()
                        f.setBold(True)
                        it.setFont(f)
                        it.setToolTip("تعيين يدوي")
                    if any(x["session_id"] for x in xs):
                        it.setText(txt + "  ✓")
                        it.setToolTip((it.toolTip() + "\n" if it.toolTip() else "") + "مُدرجة في الجدول")
                t.setItem(i, 2 + j, it)
            if d == date.today():
                for j in range(t.columnCount()):
                    if t.item(i, j):
                        f = t.item(i, j).font()
                        f.setBold(True)
                        t.item(i, j).setFont(f)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        st = D.stats(self.db, a, b)
        s = self.stats
        s.setSortingEnabled(False)
        s.clear()
        s.setColumnCount(2 + len(st["types"]))
        s.setHorizontalHeaderLabels(["القسم"] + [x["name"] for x in st["types"]] + ["المجموع"])
        s.setRowCount(len(st["rows"]))
        for i, (name, cnt, tot) in enumerate(st["rows"]):
            s.setItem(i, 0, QTableWidgetItem(name))
            for j, ty in enumerate(st["types"], 1):
                it = QTableWidgetItem()
                it.setData(Qt.DisplayRole, cnt.get(ty["id"], 0))
                s.setItem(i, j, it)
            it = QTableWidgetItem()
            it.setData(Qt.DisplayRole, tot)
            s.setItem(i, len(st["types"]) + 1, it)
        s.setSortingEnabled(True)
        s.resizeColumnsToContents()
        tots = [tot for _n, _c, tot in st["rows"]]
        if tots:
            self.msg.setText(f"الفترة: {len(days)} يوماً · المناوبات لكل قسم بين {min(tots)} و{max(tots)} "
                             "(تناوب عادل كلما تقارب الرقمان). انقر مرتين على خانة للتعيين اليدوي.")

    # ------------------------------------------------------------------ الأنواع
    def _cur_type(self):
        it = self.types.currentItem()
        return next((t for t in self.ts if it and t["id"] == it.data(Qt.UserRole)), None)

    def add_type(self):
        if TypeDialog(self, self.db).exec() == QDialog.Accepted:
            self.refresh()
            self.ctx.changed("subjects")

    def edit_type(self):
        t = self._cur_type()
        if t and TypeDialog(self, self.db, t).exec() == QDialog.Accepted:
            self.refresh()

    def del_type(self):
        t = self._cur_type()
        if t and confirm(self, f"حذف النوع «{t['name']}» وكل مناوباته؟", danger=True):
            D.delete_type(self.db, t["id"])
            self.refresh()

    # ------------------------------------------------------------------ التوزيع
    def auto(self):
        a, b = self.range()
        res = D.generate(self.db, a, b)
        self.refresh()
        from .. import sounds
        sounds.play("ok", self.db)
        txt = f"وُزعت {res['placed']} مناوبة."
        if res["missing"]:
            txt += f"\n{len(res['missing'])} خانة بلا قسم:\n" + "\n".join(
                f"• {d.strftime('%d/%m')} {n}: {why}" for d, n, why in res["missing"][:10])
        info(self, txt)

    def clear(self):
        a, b = self.range()
        if confirm(self, "مسح المناوبات الموزعة آلياً في الفترة؟ (اليدوية تبقى)"):
            D.clear_auto(self.db, a, b)
            self.refresh()

    def _cell(self, row, col):
        it = self.table.item(row, col)
        if not it or col < 2:
            return
        d, tid = it.data(Qt.UserRole)
        t = next(x for x in self.ts if x["id"] == tid)
        cur = [x["section_id"] for x in D.assignments(self.db, d, d) if x["type_id"] == tid]
        dlg = PickSections(self, self.db, t, date.fromisoformat(d), cur)
        if dlg.exec() == QDialog.Accepted:
            D.set_manual(self.db, tid, d, dlg.chosen())
            self.refresh()

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        if not it or it.column() < 2:
            return
        d, tid = it.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction(icon("mdi6.pencil"), "تعيين يدوي…", lambda: self._cell(it.row(), it.column()))
        m.addAction(icon("mdi6.close"), "تفريغ هذه الخانة",
                    lambda: (D.set_manual(self.db, tid, d, []), self.refresh()))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def insert(self):
        """الإدراج في الجدول عند الطلب فقط: أسبوع يختاره المستخدم."""
        a, _b = self.range()
        dlg = QDialog(self)
        dlg.setWindowTitle("إدراج المناوبات في الجدول")
        f = QFormLayout(dlg)
        wk = QDateEdit(QDate.currentDate())
        wk.setCalendarPopup(True)
        wk.setDisplayFormat("dd/MM/yyyy")
        f.addRow("الأسبوع (أي يوم منه)", wk)
        f.addRow(QLabel("تُوضع كل مناوبة كبطاقة «يوم كامل» للقسم في ذلك اليوم. "
                        "إذا كان في اليوم حصص يسألك قبل إرجاعها إلى الشريط."))
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        ws = week_start(wk.date().toPython())

        def ask(short, d, busy):
            names = "، ".join(c.sname for c in busy[:5])
            return confirm(self, f"{short} — {DAY_NAMES[weekday_sun0(d)]} {d.strftime('%d/%m')}: فيه {len(busy)} حصة "
                                 f"({names}). إرجاعها إلى الشريط ووضع المناوبة؟")
        res = D.insert_week(self.db, ws, ask)
        self.refresh()
        self.ctx.changed("sessions_grid")
        txt = f"أُدرجت {res['inserted']} مناوبة في جدول الأسبوع."
        if res["skipped"]:
            txt += "\nلم تُدرج:\n" + "\n".join(f"• {s} {d.strftime('%d/%m')}: {why}" for s, d, why in res["skipped"][:12])
        info(self, txt)

    def print_(self):
        from ...exporters import report_sheet as RS
        from ..sheet_view import PreviewDialog
        a, b = self.range()
        doc = D.report_doc(self.db, a, b)
        doc.xlsx = lambda path: D.to_xlsx(self.db, a, b, path)
        PreviewDialog(self.db, RS.sheets(self.db, doc), self).exec()

    def xlsx(self):
        from pathlib import Path

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFileDialog
        a, b = self.range()
        base = self.db.get_setting("print_dir", "") or str(Path.home() / "Documents")
        path, _ = QFileDialog.getSaveFileName(self, "حفظ Excel", str(Path(base) / f"المناوبات_{a}_{b}.xlsx"), "*.xlsx")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        D.to_xlsx(self.db, a, b, path)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
