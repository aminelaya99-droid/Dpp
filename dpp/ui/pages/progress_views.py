"""تبويبات «المقرر والتقدم» الجديدة: المقرر والمنجز، التحليلات، التنبيهات."""
from __future__ import annotations

from datetime import date

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QMenu, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget,
                               QTableWidgetItem, QToolTip, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...services import alerts as AL
from ...services import progress as P
from .. import theme
from ..colors import FAMILY_BASE, FAMILY_LABELS
from ..widgets import DonutChart, LineChart, confirm, icon, info


class Num(QTableWidgetItem):
    """خانة رقمية تُرتَّب حسب القيمة، وتعرض «—» عند غياب القيمة."""

    def __init__(self, v, suffix=""):
        super().__init__("—" if v is None else f"{v:g}{suffix}")
        self.v = -1e18 if v is None else v
        self.setTextAlignment(Qt.AlignCenter)

    def __lt__(self, other):
        return self.v < getattr(other, "v", 0)


def _table(headers: list[str]) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    return t


def pct_color(pct: float | None) -> QColor:
    """لون خانة حسب النسبة: أحمر فاتح (قليل) ← عسلي ← أخضر (مكتمل)."""
    if pct is None:
        return QColor(theme.CURRENT["surface2"])
    x = max(0.0, min(1.0, pct / 100))
    stops = [(0.0, (0xF6, 0xC9, 0xC2)), (0.5, (0xF6, 0xE3, 0xB4)), (1.0, (0xBF, 0xE3, 0xC0))]
    for (a, ca), (b, cb) in zip(stops, stops[1:]):
        if x <= b:
            k = (x - a) / (b - a)
            c = QColor(*(int(ca[i] + (cb[i] - ca[i]) * k) for i in range(3)))
            break
    if theme.is_dark():
        sf = QColor(theme.CURRENT["surface"])
        c = QColor(int(c.red() * 0.45 + sf.red() * 0.55), int(c.green() * 0.45 + sf.green() * 0.55),
                   int(c.blue() * 0.45 + sf.blue() * 0.55))
    return c


# ====================================================================== المقرر والمنجز
SCOPES = [("formation", "التكوين كله"), ("level", "الطور"), ("specialty", "الاختصاص"), ("section", "القسم")]
SHAPES = [("donut", "دوائر", "mdi6.chart-donut"), ("hbar", "أعمدة أفقية", "mdi6.chart-bar"),
          ("vbar", "أعمدة عمودية", "mdi6.chart-bar-stacked")]


class SimpleView(QWidget):
    """المقرر والمنجز: العرض حسب التكوين أو الطور أو الاختصاص أو القسم، بدوائر أو أعمدة، والجدول تحتها."""

    COLS = ["القسم", "المادة", "النوع", "المقرر (سا)", "المنجز (سا)", "نسبة الإنجاز", "الباقي (سا)", "حصص منجزة",
            "ملاحظة"]

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.all_rows: list[dict] = []
        self.rows: list[dict] = []
        self.scope, self.target, self.detail, self.shape = "formation", None, "sections", "donut"
        self._last_page_sec = None
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        # سطر 1: العرض حسب / الاختيار / التفصيل / الشكل
        b1 = QHBoxLayout()
        b1.addWidget(QLabel("العرض حسب:"))
        self.scope_cb = QComboBox()
        for k, lab in SCOPES:
            self.scope_cb.addItem(lab, k)
        self.scope_cb.currentIndexChanged.connect(self._scope_changed)
        b1.addWidget(self.scope_cb)
        self.target_cb = QComboBox()
        self.target_cb.setMinimumWidth(260)
        self.target_cb.currentIndexChanged.connect(self._target_changed)
        b1.addWidget(self.target_cb)
        self.detail_cb = QComboBox()
        self.detail_cb.addItem("لكل قسم", "sections")
        self.detail_cb.addItem("لكل مادة", "subjects")
        self.detail_cb.currentIndexChanged.connect(self._detail_changed)
        b1.addWidget(self.detail_cb)
        b1.addStretch()
        self.shape_btns = {}
        for k, lab, ic in SHAPES:
            bt = QPushButton(lab)
            bt.setIcon(icon(ic))
            bt.setCheckable(True)
            bt.setChecked(k == self.shape)
            bt.clicked.connect(lambda _=False, k=k: self.set_shape(k))
            self.shape_btns[k] = bt
            b1.addWidget(bt)
        b1.addSpacing(10)
        self.b_print = QPushButton(icon("mdi6.printer-eye"), "طباعة")
        pm = QMenu(self.b_print)
        pm.addAction(icon("mdi6.monitor-dashboard"), "العرض الحالي (الرسم والجدول)", lambda: self.print_doc("current"))
        pm.addAction(icon("mdi6.file-document-multiple-outline"), "ورقة لكل قسم", lambda: self.print_doc("sections"))
        pm.addAction(icon("mdi6.table-pivot"), "جدول مقارنة الأقسام (مواد × أقسام)", lambda: self.print_doc("compare"))
        pm.addAction(icon("mdi6.book-open-page-variant-outline"), "التقرير الشامل لتقدم الدروس",
                     lambda: self.print_doc("full"))
        self.b_print.setMenu(pm)
        b1.addWidget(self.b_print)
        self.b_xlsx = QPushButton(icon("mdi6.file-excel-outline"), "Excel")
        self.b_xlsx.setToolTip("ملف واحد: ملخص + ورقة لكل طور (مواد × أقسام) + ورقة لكل قسم، بالألوان والمعادلات")
        self.b_xlsx.clicked.connect(self.export_xlsx)
        b1.addWidget(self.b_xlsx)
        v.addLayout(b1)
        # سطر 2: بحث وتصفية الجدول
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة أو قسم…")
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search, 1)
        self.only_missing = QCheckBox("بلا مقرر")
        self.only_missing.toggled.connect(self._filter)
        bar.addWidget(self.only_missing)
        self.only_open = QCheckBox("غير المكتملة")
        self.only_open.toggled.connect(self._filter)
        bar.addWidget(self.only_open)
        self.family = QComboBox()
        self.family.addItem("كل الأنواع", None)
        for k in ("specialty", "military", "general"):
            self.family.addItem(FAMILY_LABELS[k], k)
        self.family.currentIndexChanged.connect(self._family_changed)
        bar.addWidget(self.family)
        self.table_mode = QComboBox()
        self.table_mode.addItem("الجدول: مقارنة الأقسام (مواد × أقسام)", "compare")
        self.table_mode.addItem("الجدول: التفصيل", "detail")
        self.table_mode.currentIndexChanged.connect(lambda _: self._show())
        bar.addWidget(self.table_mode)
        v.addLayout(bar)
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.RichText)
        v.addWidget(self.summary)
        split = QSplitter(Qt.Vertical)
        split.setChildrenCollapsible(False)
        self.chart_scroll = QScrollArea()
        self.chart_scroll.setWidgetResizable(True)
        self.chart_scroll.setFrameShape(QFrame.NoFrame)
        self.chart_scroll.setMinimumHeight(120)
        self.chart = ProgressChart()
        self.chart.clicked.connect(self._drill)
        self.chart_scroll.setWidget(self.chart)
        split.addWidget(self.chart_scroll)
        self.table = _table(self.COLS)
        self.table.setSortingEnabled(True)
        self.table.cellDoubleClicked.connect(self._double)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.installEventFilter(self)
        self.matrix = QTableWidget()
        self.matrix.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.matrix.verticalHeader().setVisible(False)
        self.matrix.setAlternatingRowColors(True)
        self.matrix.setSortingEnabled(True)
        self.matrix.installEventFilter(self)
        self.matrix.cellDoubleClicked.connect(self._matrix_double)
        self.tstack = QStackedWidget()
        self.tstack.addWidget(self.table)
        self.tstack.addWidget(self.matrix)
        split.addWidget(self.tstack)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([320, 420])
        v.addWidget(split, 1)
        self._update_controls()

    WEIGHTS = [1.3, 2.8, 0.9, 0.9, 0.9, 1.1, 0.9, 0.9, 1.0]

    def fit_columns(self):
        """الأعمدة تملأ عرض الجدول بنسب ثابتة (لا تلتصق باليمين ولا تترك فراغاً)."""
        t = self.table
        w = t.viewport().width()
        cols = [i for i in range(t.columnCount()) if not t.isColumnHidden(i)]
        tot = sum(self.WEIGHTS[i] for i in cols) or 1
        for i in cols[:-1]:
            t.setColumnWidth(i, int(w * self.WEIGHTS[i] / tot))

    def eventFilter(self, obj, e):
        if obj is self.table and e.type() == e.Type.Resize:
            self.fit_columns()
        if obj is getattr(self, "matrix", None) and e.type() == e.Type.Resize:
            self.fit_matrix()
        return False

    def fit_matrix(self):
        t = self.matrix
        n = t.columnCount()
        if n < 3:
            return
        w = t.viewport().width()
        first = max(200, int(w * 0.26))
        rest = max(64, int((w - first - 70) / max(1, n - 2)))
        t.setColumnWidth(0, first)
        t.setColumnWidth(1, 70)
        for j in range(2, n - 1):
            t.setColumnWidth(j, rest)

    def _compare_mode(self) -> bool:
        return self.scope in ("level", "specialty") and self.table_mode.currentData() == "compare"

    def _fill_matrix(self):
        from ...services import progress_reports as PR
        t = self.matrix
        m = PR.matrix(self.rows)
        self._m = m
        q = self.search.text().strip()
        subs = [x for x in m["subjects"] if not q or q in x[1]]
        heads = ["المادة", "النوع"] + [x[1] for x in m["sections"]] + ["المتوسط"]
        t.setSortingEnabled(False)
        t.clear()
        t.setColumnCount(len(heads))
        t.setHorizontalHeaderLabels(heads)
        for j, x in enumerate(m["sections"]):
            t.horizontalHeaderItem(j + 2).setToolTip(x[2])
        t.setRowCount(len(subs) + 1)
        for i, (sid, name, fam) in enumerate(subs):
            it = QTableWidgetItem(name)
            it.setData(Qt.UserRole, sid)
            t.setItem(i, 0, it)
            f = QTableWidgetItem(FAMILY_LABELS.get(fam, ""))
            f.setForeground(QColor(FAMILY_BASE.get(fam, "#777")))
            t.setItem(i, 1, f)
            for j, x in enumerate(m["sections"]):
                r = m["cell"].get((sid, x[0]))
                c = Num(r["pct"] if r else None, "%")
                if r is None:
                    c.setText("")
                elif r["pct"] is None:
                    c.setText("بلا مقرر")
                else:
                    c.setBackground(QBrush(pct_color(r["pct"])))
                    c.setToolTip(f"{x[1]} · {name}\n{r['done']:g} من {r['hours']:g} سا · باقي {r['remaining']:g} سا")
                t.setItem(i, j + 2, c)
            a = Num(m["sub_avg"][sid], "%")
            if m["sub_avg"][sid] is not None:
                a.setBackground(QBrush(pct_color(m["sub_avg"][sid])))
            t.setItem(i, len(heads) - 1, a)
        last = len(subs)
        tot = QTableWidgetItem("المجموع (كل المواد)")
        f = tot.font()
        f.setBold(True)
        tot.setFont(f)
        t.setItem(last, 0, tot)
        for j, x in enumerate(m["sections"]):
            sm = m["sec_sum"][x[0]]
            c = Num(sm["pct"], "%")
            c.setFont(f)
            if sm["pct"] is not None:
                c.setBackground(QBrush(pct_color(sm["pct"])))
            t.setItem(last, j + 2, c)
        allp = P.summarize_simple(self.rows)["pct"]
        c = Num(allp, "%")
        c.setFont(f)
        t.setItem(last, len(heads) - 1, c)
        self.fit_matrix()

    def _matrix_double(self, row, col):
        m = getattr(self, "_m", None)
        if not m or col < 2 or col >= 2 + len(m["sections"]):
            return
        self.set_scope("section", m["sections"][col - 2][0])

    # ------------------------------------------------------------------ الطباعة وExcel
    def _scope_label(self) -> str:
        if self.scope == "formation":
            return f"التكوين: {self.page.ctx.formation_label()}"
        lab = self.target_cb.currentText()
        return {"level": "الطور", "specialty": "الاختصاص", "section": "القسم"}[self.scope] + f": {lab}"

    def _chart_png(self):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        if not self.chart.items:
            return None
        w = max(900, self.chart.width())
        old = dict(theme.CURRENT)
        theme.CURRENT.update(theme.PALETTES.get("light", {}))      # الطباعة دائماً على خلفية فاتحة
        theme.CURRENT["surface"] = "#FFFFFF"
        try:
            self.chart.resize(w, max(self.chart.minimumHeight(), 240))
            pm = self.chart.grab()
        finally:
            theme.CURRENT.clear()
            theme.CURRENT.update(old)
            self.chart.update()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        pm.save(buf, "PNG")
        return bytes(ba), pm.width(), pm.height()

    def build_doc(self, kind: str):
        from ...services import progress_reports as PR
        db, today = self.page.ctx.db, self.page.today()
        rows = self.rows
        lab = self._scope_label()
        if kind == "current":
            return PR.doc_current(db, rows, self._groups(rows), lab, today, self._chart_png(),
                                  detail_rows=None if self._compare_mode() else rows, compare=self._compare_mode())
        if kind == "sections":
            return PR.doc_sections(db, rows, lab, today)
        if kind == "compare":
            if self.scope in ("formation",):
                # مقارنة لكل طور في صفحة
                from ...exporters.report_sheet import ReportDoc
                doc = ReportDoc("progress_compare", "مقارنة أقسام الأطوار", [lab, f"حتى تاريخ: {today}"],
                                name="مقارنة_الأقسام")
                lv = {}
                for r in rows:
                    lv.setdefault(r["level"], []).append(r)
                for k, (code, rs) in enumerate(lv.items()):
                    if k:
                        doc.page_break()
                    doc.heading(f"الطور {code}")
                    PR.add_matrix_table(doc, rs)
                return doc
            return PR.doc_compare(db, rows, lab, today)
        return PR.doc_full(db, self.all_rows if self.scope == "formation" else rows, lab, today)

    def print_doc(self, kind: str):
        from ...exporters import report_sheet as RS
        from ..sheet_view import PreviewDialog
        if not self.rows:
            info(self, "لا توجد بيانات للطباعة في هذا الاختيار.")
            return
        doc = self.build_doc(kind)
        rows = self.all_rows if (kind == "full" and self.scope == "formation") else self.rows
        db = self.page.ctx.db
        from ...services import progress_reports as PR
        today = self.page.today()
        doc.xlsx = lambda path: PR.to_xlsx(db, rows, path, doc.title, today)
        PreviewDialog(db, RS.sheets(db, doc), self).exec()

    def export_xlsx(self):
        from pathlib import Path
        from PySide6.QtWidgets import QFileDialog
        from ...services import progress_reports as PR
        db = self.page.ctx.db
        if not self.rows:
            info(self, "لا توجد بيانات.")
            return
        base = db.get_setting("print_dir", "") or str(Path.home() / "Documents")
        name = "المقرر_والمنجز_" + self._scope_label().replace(":", "").replace("/", "-").replace(" ", "_")[:40] + ".xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "حفظ Excel", str(Path(base) / name), "*.xlsx")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            PR.to_xlsx(db, self.rows, path, "المقرر والمنجز — " + self._scope_label(), self.page.today())
        except Exception as e:
            from ..widgets import error
            error(self, f"تعذر الحفظ: {e}")
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    # ------------------------------------------------------------------ الاختيارات
    def set_shape(self, k: str):
        self.shape = k
        for kk, bt in self.shape_btns.items():
            bt.setChecked(kk == k)
        self._show()

    def set_scope(self, scope: str, target=None, detail: str | None = None):
        self.scope, self.target = scope, target
        if detail:
            self.detail = detail
        self.scope_cb.blockSignals(True)
        self.scope_cb.setCurrentIndex(max(0, self.scope_cb.findData(scope)))
        self.scope_cb.blockSignals(False)
        self._update_controls()
        self._show()

    def _scope_changed(self, *_):
        self.scope = self.scope_cb.currentData()
        self.target = None
        self._update_controls()
        self._show()

    def _target_changed(self, *_):
        self.target = self.target_cb.currentData()
        self._show()

    def _detail_changed(self, *_):
        self.detail = self.detail_cb.currentData()
        self._show()

    def _family_changed(self, *_):
        self._show()

    def _targets(self) -> list[tuple]:
        seen, out = set(), []
        for r in self.all_rows:
            if self.scope == "level":
                k, lab = r["level_id"], r["level"] or "—"
            elif self.scope == "specialty":
                k, lab = r["specialty_id"], f"{r['level']} — {r['specialty'] or 'بلا اختصاص'}"
            elif self.scope == "section":
                k, lab = r["section_id"], f"{r['section']} — {r['section_name']}"
            else:
                return []
            if k not in seen:
                seen.add(k)
                out.append((k, lab))
        return out

    def _update_controls(self):
        tg = self._targets()
        self.target_cb.blockSignals(True)
        self.target_cb.clear()
        for k, lab in tg:
            self.target_cb.addItem(lab, k)
        if tg:
            i = self.target_cb.findData(self.target)
            self.target_cb.setCurrentIndex(max(0, i))
            self.target = self.target_cb.currentData()
        self.target_cb.blockSignals(False)
        self.target_cb.setVisible(self.scope != "formation")
        self.detail_cb.blockSignals(True)
        self.detail_cb.setCurrentIndex(max(0, self.detail_cb.findData(self.detail)))
        self.detail_cb.blockSignals(False)
        self.detail_cb.setVisible(self.scope in ("level", "specialty"))

    # ------------------------------------------------------------------ البيانات
    def refresh(self):
        ctx = self.page.ctx
        self.all_rows = P.simple_progress(ctx.db, ctx.formation_ids(), self.page.today(), None)
        ps = self.page.section.currentData()
        if ps != self._last_page_sec:                      # اختيار قسم من أعلى الصفحة = عرض القسم
            self._last_page_sec = ps
            if ps:
                self.scope, self.target = "section", ps
                self.scope_cb.blockSignals(True)
                self.scope_cb.setCurrentIndex(self.scope_cb.findData("section"))
                self.scope_cb.blockSignals(False)
        self._update_controls()
        self._show()

    def _scope_rows(self) -> list[dict]:
        key = {"level": "level_id", "specialty": "specialty_id", "section": "section_id"}.get(self.scope)
        rows = self.all_rows if not key else [r for r in self.all_rows if r[key] == self.target]
        fam = self.family.currentData()
        return [r for r in rows if not fam or r["family"] == fam]

    def _groups(self, rows) -> list[dict]:
        if self.scope == "formation":
            by, lab, key = "level_id", lambda r: r["level"] or "—", ("level",)
        elif self.scope == "section" or self.detail == "subjects":
            by, lab, key = "subject_id", lambda r: r["subject"], None
        else:
            by, lab, key = "section_id", lambda r: r["section"], ("section",)
        groups: dict = {}
        for r in rows:
            groups.setdefault(r[by], []).append(r)
        out = []
        for k, rs in groups.items():
            s = P.summarize_simple(rs)
            if not s["hours"]:
                continue
            tip = f"{lab(rs[0])}"
            if by == "section_id":
                tip = rs[0]["section_name"]
            tip += f"\n{s['done']:g} من {s['hours']:g} سا ({s['pct']:g}%) · باقي {s['remaining']:g} سا"
            if by != "subject_id":
                tip += f"\n{len({r['section_id'] for r in rs})} قسم · {len({r['subject_id'] for r in rs})} مادة"
                if s["missing"]:
                    tip += f"\n{s['missing']} مادة بلا مقرر"
                tip += "\nانقر للتفصيل"
            out.append({"label": lab(rs[0]), "done": s["done"], "hours": s["hours"], "pct": s["pct"] or 0,
                        "remaining": s["remaining"], "tip": tip,
                        "key": (key[0], k) if key else None})
        if self.scope == "section" or self.detail == "subjects":
            out.sort(key=lambda x: -x["pct"])
        return out

    def _drill(self, key):
        kind, k = key
        if kind == "level":
            self.set_scope("level", k, "sections")
        elif kind == "section":
            self.set_scope("section", k)

    def _show(self):
        self.rows = self._scope_rows()
        s = P.summarize_simple(self.rows)
        t = theme.CURRENT
        parts = [f"{len({r['section_id'] for r in self.rows})} قسماً · {len(self.rows)} مادة"]
        if s["pct"] is not None:
            parts.append(f"<b>{s['pct']:g}%</b> من المقرر ({s['done']:g} من {s['hours']:g} سا) · باقي {s['remaining']:g} سا")
        if s["complete"]:
            parts.append(f"<span style='color:{t['ok']}'>{s['complete']} مادة مكتملة</span>")
        if s["over"]:
            parts.append(f"<span style='color:{t['warn']}'>{s['over']} مادة تجاوزت المقرر</span>")
        if s["missing"]:
            parts.append(f"<span style='color:{t['warn']}'>{s['missing']} مادة بلا مقرر (راجع «التنبيهات»)</span>")
        self.summary.setText(" · ".join(parts))
        self.chart.set_items(self._groups(self.rows), self.shape)
        self.chart_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded if self.shape == "vbar"
                                                       else Qt.ScrollBarAlwaysOff)
        self.table.setColumnHidden(0, self.scope == "section")
        self.table_mode.setVisible(self.scope in ("level", "specialty"))
        if self._compare_mode():
            self.tstack.setCurrentWidget(self.matrix)
            self._fill_matrix()
        else:
            self.tstack.setCurrentWidget(self.table)
            self._fill_table()
            self.fit_columns()

    def _fill_table(self):
        t = self.table
        warn, ok = QColor(theme.CURRENT["warn"]), QColor(theme.CURRENT["ok"])
        t.setSortingEnabled(False)
        t.setUpdatesEnabled(False)
        t.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            note = ("بلا مقرر" if not r["hours"] else "تجاوز المقرر" if r["over"]
                    else "مكتملة" if r["remaining"] == 0 else "")
            items = [QTableWidgetItem(r["section"]), QTableWidgetItem(r["subject"]),
                     QTableWidgetItem(FAMILY_LABELS.get(r["family"], "")), Num(r["hours"]), Num(r["done"]),
                     Num(r["pct"], "%"), Num(r["remaining"]), Num(r["sessions"]), QTableWidgetItem(note)]
            items[0].setData(Qt.UserRole, i)
            items[0].setToolTip(r["section_name"])
            items[2].setForeground(QColor(FAMILY_BASE.get(r["family"], "#777")))
            items[3].setToolTip("انقر مرتين لتعديل المقرر")
            items[5].setBackground(QBrush(pct_color(r["pct"])))
            if not r["hours"]:
                items[3].setForeground(warn)
                items[8].setForeground(warn)
            elif r["over"]:
                items[8].setForeground(warn)
            elif note:
                items[8].setForeground(ok)
            for j, it in enumerate(items):
                t.setItem(i, j, it)
        t.setSortingEnabled(True)
        t.setUpdatesEnabled(True)
        self._filter()

    def _filter(self, *_):
        if self._compare_mode() and self.sender() is self.search:
            self._fill_matrix()
            return
        q = self.search.text().strip()
        fam = self.family.currentData()
        for i in range(self.table.rowCount()):
            r = self.rows[self.table.item(i, 0).data(Qt.UserRole)]
            hide = (q and q not in r["subject"] and q not in r["section"]) \
                or (self.only_missing.isChecked() and bool(r["hours"])) \
                or (self.only_open.isChecked() and r["hours"] and (r["remaining"] or 0) <= 0) \
                or (fam and r["family"] != fam)
            self.table.setRowHidden(i, bool(hide))

    def _row(self, i):
        it = self.table.item(i, 0)
        return self.rows[it.data(Qt.UserRole)] if it else None

    def _double(self, row, col):
        r = self._row(row)
        if r and col == 3 and r["level_id"]:
            self.page.edit_total_hours(r)

    def _menu(self, pos):
        it = self.table.itemAt(pos)
        r = self._row(it.row()) if it else None
        if not r:
            return
        m = QMenu(self)
        m.addAction(icon("mdi6.pencil"), "تعديل المقرر لهذا الاختصاص", lambda: self.page.edit_total_hours(r))
        m.addAction(icon("mdi6.table-large"), "فتح القسم في الجدول العام",
                    lambda: self.page.ctx.navigate.emit("master", ("section", r["section_id"])))
        m.exec(self.table.viewport().mapToGlobal(pos))


# ====================================================================== مخطط المقرر والمنجز (دوائر / أعمدة)
def plan_color() -> QColor:
    c = QColor(theme.CURRENT["muted"])
    c.setAlpha(70)
    return c


def done_color(pct: float) -> str:
    t = theme.CURRENT
    return t["ok"] if pct >= 66 else t["warn"] if pct >= 33 else t["accent"]


class ProgressChart(QWidget):
    """يرسم عناصر {label, done, hours, pct, remaining, tip, key} بثلاثة أشكال: دوائر، أعمدة أفقية، أعمدة عمودية.
    يملأ العرض المتاح ويحسب ارتفاعه بنفسه (داخل منطقة تمرير)، والنقر على عنصر يرسل مفتاحه."""
    clicked = Signal(object)

    DONUT_W, DONUT_H = 150, 178
    HBAR_H = 30
    VBAR_W = 70

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self.shape = "donut"
        self.setMouseTracking(True)
        self._rects: list[tuple[QRectF, dict]] = []
        self.setLayoutDirection(Qt.RightToLeft)

    def set_items(self, items: list[dict], shape: str):
        self.items, self.shape = items, shape
        self._relayout()
        self.update()

    def _cols(self, w: int) -> int:
        return max(1, int(w // self.DONUT_W))

    def _needed(self, w: int) -> tuple[int, int]:
        n = len(self.items)
        if not n:
            return 0, 60
        if self.shape == "donut":
            return 0, ((n + self._cols(w) - 1) // self._cols(w)) * self.DONUT_H + 8
        if self.shape == "hbar":
            return 0, n * self.HBAR_H + 34
        return n * self.VBAR_W + 60, 230

    def _relayout(self):
        mw, mh = self._needed(max(200, self.width()))
        self.setMinimumHeight(mh)
        self.setMinimumWidth(mw)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        mh = self._needed(max(200, self.width()))[1]
        if mh != self.minimumHeight():
            self.setMinimumHeight(mh)

    def _tip(self, it) -> str:
        return it.get("tip") or (f"{it['label']}\n{it['done']:g} من {it['hours']:g} سا ({it['pct']:g}%)"
                                 f" · باقي {it['remaining']:g} سا")

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme.CURRENT
        self._rects = []
        p.fillRect(self.rect(), QColor(t["surface"]))
        if not self.items:
            p.setPen(QColor(t["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "لا يوجد مقرر لهذا الاختيار بعد.")
            return
        getattr(self, "_paint_" + self.shape)(p, t)

    def _paint_donut(self, p, t):
        W = self.width()
        cols = self._cols(W)
        cw = W / cols
        f = QFont(self.font())
        for i, it in enumerate(self.items):
            r, c = divmod(i, cols)
            x = W - (c + 1) * cw                       # من اليمين إلى اليسار
            cell = QRectF(x + 4, r * self.DONUT_H + 4, cw - 8, self.DONUT_H - 8)
            self._rects.append((cell, it))
            p.setPen(QPen(QColor(t["border"]), 1))
            p.setBrush(QColor(t["surface"]))
            p.drawRoundedRect(cell, 8, 8)
            d = 96
            ring = QRectF(cell.center().x() - d / 2, cell.top() + 10, d, d)
            pen = QPen(QColor(t["grid"]), 12)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawArc(ring, 0, 360 * 16)
            pct = max(0.0, min(100.0, it["pct"] or 0))
            pen.setColor(QColor(done_color(pct)))
            p.setPen(pen)
            p.drawArc(ring, 90 * 16, int(-pct * 3.6 * 16))
            f.setPointSizeF(12.5)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(t["text"]))
            p.drawText(ring, Qt.AlignCenter, f"{it['pct'] or 0:.0f}%")
            f.setPointSizeF(9)
            p.setFont(f)
            fm = p.fontMetrics()
            p.drawText(QRectF(cell.left() + 4, ring.bottom() + 6, cell.width() - 8, 18), Qt.AlignCenter,
                       fm.elidedText(it["label"], Qt.ElideMiddle, int(cell.width() - 8)))
            f.setBold(False)
            f.setPointSizeF(8.5)
            p.setFont(f)
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(cell.left(), ring.bottom() + 24, cell.width(), 16), Qt.AlignCenter,
                       f"{it['done']:g} من {it['hours']:g} سا")
            p.drawText(QRectF(cell.left(), ring.bottom() + 40, cell.width(), 16), Qt.AlignCenter,
                       f"باقي {it['remaining']:g} سا")

    def _paint_hbar(self, p, t):
        W = self.width()
        f = QFont(self.font())
        f.setPointSizeF(9)
        p.setFont(f)
        fm = p.fontMetrics()
        lab_w = min(260, max(110, max(fm.horizontalAdvance(it["label"]) for it in self.items) + 16))
        val_w = 150
        track_l, track_r = val_w + 8, W - lab_w - 8
        tw = max(40.0, track_r - track_l)
        mx = max(it["hours"] for it in self.items) or 1
        # محور النسب في الأعلى
        p.setPen(QColor(t["muted"]))
        p.drawText(QRectF(track_l, 4, tw, 18), Qt.AlignCenter, "الطول = المقرر · الجزء الملوّن = المنجز")
        for i, it in enumerate(self.items):
            y = 26 + i * self.HBAR_H
            row = QRectF(0, y, W, self.HBAR_H)
            self._rects.append((row, it))
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(W - lab_w, y, lab_w - 6, self.HBAR_H), Qt.AlignRight | Qt.AlignVCenter,
                       fm.elidedText(it["label"], Qt.ElideMiddle, int(lab_w - 8)))
            full = tw * (it["hours"] / mx)
            bar = QRectF(track_r - full, y + 6, full, self.HBAR_H - 12)
            p.setPen(Qt.NoPen)
            p.setBrush(plan_color())
            p.drawRoundedRect(bar, 4, 4)
            pct = max(0.0, min(100.0, it["pct"] or 0))
            dn = QRectF(track_r - full * pct / 100, y + 6, full * pct / 100, self.HBAR_H - 12)   # يمتلئ من اليمين
            p.setBrush(QColor(done_color(pct)))
            p.drawRoundedRect(dn, 4, 4)
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(0, y, val_w, self.HBAR_H), Qt.AlignLeft | Qt.AlignVCenter,
                       f"{it['pct'] or 0:g}% · {it['done']:g}/{it['hours']:g} سا")

    def _paint_vbar(self, p, t):
        W, H = self.width(), self.height()
        f = QFont(self.font())
        f.setPointSizeF(8.5)
        p.setFont(f)
        fm = p.fontMetrics()
        top, bottom = 34, H - 58
        mx = max(it["hours"] for it in self.items) or 1
        n = len(self.items)
        slot = max(self.VBAR_W, (W - 20) / n)
        # مفتاح الألوان (من اليمين)
        x = W - 12
        for col, lab in ((plan_color(), "المقرر"), (QColor(t["warn"]), "المنجز (اللون حسب النسبة)")):
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRect(QRectF(x - 12, 10, 12, 12))
            tw = fm.horizontalAdvance(lab) + 4
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(x - 18 - tw, 6, tw, 20), Qt.AlignRight | Qt.AlignVCenter, lab)
            x -= 18 + tw + 20
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawLine(10, bottom, W - 10, bottom)
        for i, it in enumerate(self.items):
            x = W - 10 - (i + 1) * slot
            col = QRectF(x, top, slot, H - top)
            self._rects.append((col, it))
            bw = min(22.0, slot / 2 - 6)
            cx = x + slot / 2
            hh = (bottom - top) * it["hours"] / mx
            dh = (bottom - top) * min(it["done"], it["hours"]) / mx
            pct = max(0.0, min(100.0, it["pct"] or 0))
            p.setPen(Qt.NoPen)
            p.setBrush(plan_color())
            p.drawRect(QRectF(cx, bottom - hh, bw, hh))                 # المقرر (يمين)
            p.setBrush(QColor(done_color(pct)))
            p.drawRect(QRectF(cx - bw - 2, bottom - dh, bw, dh))        # المنجز (يسار)
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(x, bottom - hh - 18, slot, 16), Qt.AlignCenter, f"{pct:.0f}%")
            lines = fm.elidedText(it["label"], Qt.ElideMiddle, int(slot * 2 - 8))
            p.drawText(QRectF(x + 2, bottom + 4, slot - 4, 50), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                       lines)

    def _item_at(self, pos):
        for r, it in self._rects:
            if r.contains(pos):
                return it
        return None

    def mouseMoveEvent(self, e):
        it = self._item_at(e.position())
        self.setCursor(Qt.PointingHandCursor if it and it.get("key") is not None else Qt.ArrowCursor)
        QToolTip.showText(e.globalPosition().toPoint(), self._tip(it) if it else "", self)

    def mousePressEvent(self, e):
        it = self._item_at(e.position())
        if it and it.get("key") is not None and e.button() == Qt.LeftButton:
            self.clicked.emit(it["key"])


# ====================================================================== التحليلات
class AnalyticsView(QWidget):
    KINDS = [("heat", "خريطة الأقسام × المواد", "mdi6.grid"),
             ("compare", "مقارنة أقسام نفس الاختصاص", "mdi6.compare-horizontal"),
             ("eta", "تاريخ الانتهاء المتوقع", "mdi6.calendar-clock"),
             ("curve", "منحنى الساعات الأسبوعية", "mdi6.chart-line")]

    def __init__(self, page):
        super().__init__()
        self.page = page
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        bar = QHBoxLayout()
        self.btns = {}
        for k, lab, ic in self.KINDS:
            b = QPushButton(icon(ic), lab)
            b.setCheckable(True)
            b.setAutoExclusive(True)
            b.clicked.connect(lambda _=False, k=k: self.show_kind(k))
            bar.addWidget(b)
            self.btns[k] = b
        bar.addStretch()
        v.addLayout(bar)
        self.hint = QLabel()
        self.hint.setObjectName("Muted")
        self.hint.setWordWrap(True)
        v.addWidget(self.hint)
        self.stack = QStackedWidget()
        self.heat = _table([])
        self.heat.setSelectionMode(QAbstractItemView.NoSelection)
        self.compare = _table(["الطور", "الاختصاص", "المادة", "المقرر"])
        self.eta = _table(["القسم", "المادة", "المقرر", "المنجز", "الباقي", "الوتيرة (سا/أسبوع)", "المطلوب أسبوعياً",
                           "الانتهاء المتوقع", "نهاية التكوين", "الحالة"])
        self.eta.setSortingEnabled(True)
        self.curve = LineChart()
        for w in (self.heat, self.compare, self.eta, self.curve):
            self.stack.addWidget(w)
        v.addWidget(self.stack, 1)
        self.kind = "heat"
        self.btns["heat"].setChecked(True)

    def show_kind(self, k):
        self.kind = k
        self.btns[k].setChecked(True)
        self.refresh()

    def refresh(self):
        ctx = self.page.ctx
        rows = P.simple_progress(ctx.db, ctx.formation_ids(), self.page.today(), self.page.section.currentData())
        getattr(self, f"_{self.kind}")(rows)

    # خريطة: الأقسام أسطر، المواد أعمدة، الخانة ملوّنة بنسبة الإنجاز
    def _heat(self, rows):
        self.stack.setCurrentWidget(self.heat)
        self.hint.setText("كل خانة نسبة إنجاز المادة في القسم: الأحمر الفاتح قليل، والأخضر مكتمل، والرمادي بلا مقرر. "
                          "اختر قسماً أو طوراً من الأعلى لتصغير الخريطة؛ مرّر المؤشر لترى الساعات.")
        subs: dict[int, str] = {}
        cnt: dict[int, int] = {}
        for r in rows:
            subs[r["subject_id"]] = r["subject"]
            cnt[r["subject_id"]] = cnt.get(r["subject_id"], 0) + (1 if r["hours"] else 0)
        cols = sorted(subs, key=lambda s: (-cnt[s], subs[s]))[:120]
        secs = []
        for r in rows:
            if r["section_id"] not in [x[0] for x in secs]:
                secs.append((r["section_id"], r["section"]))
        t = self.heat
        t.clear()
        t.setColumnCount(len(cols))
        t.setRowCount(len(secs))
        t.setHorizontalHeaderLabels([subs[c] for c in cols])
        t.setVerticalHeaderLabels([s[1] for s in secs])
        t.verticalHeader().setVisible(True)
        idx = {(r["section_id"], r["subject_id"]): r for r in rows}
        for i, (sid, _n) in enumerate(secs):
            for j, sub in enumerate(cols):
                r = idx.get((sid, sub))
                if not r:
                    continue
                it = QTableWidgetItem("—" if r["pct"] is None else f"{r['pct']:.0f}")
                it.setTextAlignment(Qt.AlignCenter)
                it.setBackground(QBrush(pct_color(r["pct"])))
                it.setForeground(QBrush(QColor("#1B1F24") if not theme.is_dark() else QColor("#E8ECEF")))
                it.setToolTip(f"{r['section']} — {r['subject']}\nالمنجز {r['done']:g} من "
                              + (f"{r['hours']:g} سا" if r["hours"] else "— (بلا مقرر)"))
                t.setItem(i, j, it)
        t.horizontalHeader().setDefaultSectionSize(84)
        t.horizontalHeader().setMinimumSectionSize(40)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Fixed)
        t.setWordWrap(True)
        hh.setFixedHeight(96)
        hh.setDefaultAlignment(Qt.AlignCenter | Qt.TextWordWrap)

    def _compare(self, rows):
        self.stack.setCurrentWidget(self.compare)
        self.hint.setText("الأقسام التي تدرس نفس الاختصاص جنباً إلى جنب: الساعات المنجزة لكل مادة. "
                          "عمود «الفرق» بين الأكثر والأقل؛ المواد ذات الفرق الكبير في الأعلى.")
        data = P.compare_specialty(rows)
        n = max((len(d["sections"]) for d in data), default=0)
        t = self.compare
        t.setSortingEnabled(False)
        t.clear()
        t.setColumnCount(5 + n)
        t.setHorizontalHeaderLabels(["الطور", "الاختصاص", "المادة", "المقرر", "الفرق"] + [f"قسم {k + 1}" for k in range(n)])
        t.setRowCount(len(data))
        warn = QColor(theme.CURRENT["warn"])
        for i, d in enumerate(data):
            vals = [d["level"], d["specialty"], d["subject"]]
            for j, x in enumerate(vals):
                t.setItem(i, j, QTableWidgetItem(x))
            t.setItem(i, 3, Num(d["hours"]))
            sp = Num(d["spread"])
            if d["hours"] and d["spread"] >= max(4, 0.15 * d["hours"]):
                sp.setForeground(warn)
            t.setItem(i, 4, sp)
            mx = max(d["values"]) if d["values"] else 0
            for k, (sec, v) in enumerate(zip(d["sections"], d["values"])):
                it = Num(v)
                it.setText(f"{sec}: {v:g}")
                if d["hours"]:
                    it.setBackground(QBrush(pct_color(v / d["hours"] * 100)))
                if mx and v == mx:
                    f = it.font()
                    f.setBold(True)
                    it.setFont(f)
                t.setItem(i, 5 + k, it)
        t.resizeColumnsToContents()
        t.setColumnWidth(2, min(300, t.columnWidth(2)))

    def _eta(self, rows):
        self.stack.setCurrentWidget(self.eta)
        self.hint.setText("الوتيرة = متوسط الساعات المنجزة في آخر 4 أسابيع. «المطلوب أسبوعياً» لإنهاء المقرر قبل نهاية "
                          "التكوين. «متوقفة»: لم تُدرَّس في آخر 4 أسابيع.")
        data = P.forecast(self.page.ctx.db, rows, self.page.today())
        labels = {"ok": "في الموعد", "late": "تتجاوز نهاية التكوين", "stalled": "متوقفة", "done": "مكتملة"}
        order = {"late": 0, "stalled": 1, "ok": 2, "done": 3}
        data.sort(key=lambda r: (order[r["status"]], r["section"], r["subject"]))
        t = self.eta
        t.setSortingEnabled(False)
        t.setRowCount(len(data))
        bad, warn, ok = QColor(theme.CURRENT["bad"]), QColor(theme.CURRENT["warn"]), QColor(theme.CURRENT["ok"])
        for i, r in enumerate(data):
            st = QTableWidgetItem(labels[r["status"]])
            st.setForeground({"late": bad, "stalled": warn, "ok": ok, "done": ok}[r["status"]])
            items = [QTableWidgetItem(r["section"]), QTableWidgetItem(r["subject"]), Num(r["hours"]), Num(r["done"]),
                     Num(r["remaining"]), Num(r["pace"]), Num(r["need"]),
                     QTableWidgetItem(r["eta"].strftime("%d/%m/%Y") if r["eta"] else "—"),
                     QTableWidgetItem(r["end"].strftime("%d/%m/%Y") if r["end"] else "—"), st]
            for j, it in enumerate(items):
                t.setItem(i, j, it)
        t.setSortingEnabled(True)
        if not getattr(self, "_eta_sized", False) and data:
            t.resizeColumnsToContents()
            t.setColumnWidth(1, min(300, t.columnWidth(1)))
            self._eta_sized = True

    def _curve(self, rows):
        self.stack.setCurrentWidget(self.curve)
        sec = self.page.section.currentData()
        self.hint.setText("الساعات المبرمجة والمنجزة أسبوعاً بأسبوع حسب نوع المادة"
                          + (" للقسم المحدد." if sec else " لكل الأقسام المعروضة (اختر قسماً من الأعلى)."))
        d = P.weekly_family_hours(self.page.ctx.db, self.page.ctx.formation_ids(), sec, self.page.today())
        from ...services.grid import week_number
        labels = [f"أ{week_number(self.page.ctx.db, date.fromisoformat(w))}" for w in d["weeks"]]
        self.curve.set_data(labels, [(FAMILY_LABELS[f], FAMILY_BASE[f], d["series"][f])
                                     for f in ("specialty", "military", "general")])


# ====================================================================== التنبيهات
class AlertsView(QWidget):
    """تنبيهات المقرر والبيانات: تبقى حتى تُصلح أو تؤكَّد."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        top = QLabel("كل مشكلة في ملف المقرر أو في البيانات تبقى هنا حتى تصلحها أو تضغط «تم التأكيد». "
                     "نقر مزدوج يفتح المكان الذي يُصلح فيه.")
        top.setObjectName("Muted")
        top.setWordWrap(True)
        v.addWidget(top)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["الخطورة", "المصدر", "التنبيه", "التفاصيل"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setWordWrap(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.open_target(it))
        self.tree.header().setSectionResizeMode(2, QHeaderView.Interactive)
        v.addWidget(self.tree, 1)
        bar = QHBoxLayout()
        b = QPushButton(icon("mdi6.check-circle-outline"), "تم التأكيد")
        b.setToolTip("إخفاء التنبيه المحدد بعد التأكد منه أو إصلاحه")
        b.clicked.connect(self.resolve_selected)
        bar.addWidget(b)
        b2 = QPushButton(icon("mdi6.open-in-app"), "فتح للإصلاح")
        b2.clicked.connect(lambda: self.open_target(self.tree.currentItem()))
        bar.addWidget(b2)
        self.show_done = QCheckBox("إظهار المؤكدة")
        self.show_done.toggled.connect(self.refresh)
        bar.addWidget(self.show_done)
        bar.addStretch()
        b3 = QPushButton(icon("mdi6.file-refresh-outline"), "إعادة فحص ملف المقرر المرفق")
        b3.setToolTip("يعيد قراءة ملف المقرر المرفق مع البرنامج وإدراجه (ما أدخلته يدوياً لا يُمس)")
        b3.clicked.connect(self.recheck)
        bar.addWidget(b3)
        v.addLayout(bar)

    def items(self) -> list[dict]:
        db = self.page.ctx.db
        out = AL.open_alerts(db)
        if self.show_done.isChecked():
            out += [dict(r) | {"done": True} for r in db.q("SELECT * FROM data_alerts WHERE resolved=1")]
        n = db.scalar("SELECT COUNT(*) FROM curriculum_issues WHERE resolved=0", (), 0)
        if n:
            out.insert(0, {"id": None, "severity": "high", "kind": "curriculum",
                           "title": f"{n} سطر من المقرر يحتاج مراجعة",
                           "details": "مواد لم يُعرف مقابلها في البرنامج، أو بقيمتين مختلفتين. "
                                      "افتح تبويب «المقرر» ← «مواد تحتاج مراجعة».",
                           "target": "curriculum_issues"})
        for a in P.progress_alerts(db, self.page.ctx.formation_ids(), self.page.today()):
            out.append(dict(a, id=None))
        return out

    def refresh(self):
        self.tree.clear()
        t = theme.CURRENT
        col = {"high": t["bad"], "medium": t["warn"], "low": t["muted"]}
        lst = self.items()
        for a in lst:
            it = QTreeWidgetItem([AL.SEVERITY_LABELS.get(a["severity"], ""), AL.KIND_LABELS.get(a["kind"], ""),
                                  a["title"], (a.get("details") or "").replace("\n", " · ")[:400]])
            it.setForeground(0, QBrush(QColor(col.get(a["severity"], t["text"]))))
            it.setToolTip(2, a["title"])
            it.setToolTip(3, a.get("details") or "")
            it.setData(0, Qt.UserRole, a)
            if a.get("done"):
                for k in range(4):
                    it.setForeground(k, QBrush(QColor(t["muted"])))
            self.tree.addTopLevelItem(it)
        for k, w in enumerate((80, 90, 420)):
            self.tree.setColumnWidth(k, w)
        self.page.set_alert_count(sum(1 for a in lst if not a.get("done")))

    def resolve_selected(self):
        sel = [it.data(0, Qt.UserRole) for it in self.tree.selectedItems()]
        ids = [a["id"] for a in sel if a.get("id")]
        if not ids:
            info(self, "هذا التنبيه محسوب من البيانات: يختفي وحده بمجرد إصلاح سببه.")
            return
        for i in ids:
            AL.resolve(self.page.ctx.db, i)
        self.refresh()

    def open_target(self, it):
        if not it:
            return
        a = it.data(0, Qt.UserRole)
        tgt = a.get("target") or ""
        if tgt.startswith("curriculum"):
            self.page.show_curriculum(issues=tgt == "curriculum_issues")
        elif tgt == "progress" and a.get("section_id"):
            self.page.select_section(a["section_id"])
        elif tgt in ("subjects", "sections"):
            self.page.ctx.navigate.emit(tgt, None)
        elif tgt.startswith("excel:"):
            info(self, f"{a['title']}\n\n{a.get('details') or ''}\n\nصحّح هذا في ملف Excel الأصلي (السطر "
                       f"{tgt.split(':')[1]}) ثم أعد الاستيراد، أو أدخل القيمة الصحيحة في تبويب «المقرر».",
                 "تنبيه من ملف المقرر")

    def recheck(self):
        from ...importers import curriculum as CI
        if not CI.bundled_file():
            info(self, "لا يوجد ملف مقرر مرفق مع هذه النسخة.")
            return
        if not confirm(self, "إعادة إدراج المقرر من الملف المرفق؟\nالقيم التي أدخلتها يدوياً تبقى كما هي."):
            return
        res = CI.bootstrap(self.page.ctx.db, force=True)
        if res:
            info(self, f"أُدرج {res['imported']} سطر مقرر، و{res['created']} مادة جديدة، و{res['issues']} سطر للمراجعة.")
        self.page.ctx.changed("curriculum")
