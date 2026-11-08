"""النافذة الرئيسية للنسخة الخفيفة: إعداد الجدول الأسبوعي ومتابعة الأسابيع السابقة."""
from __future__ import annotations

import datetime as dt

from dpp.db.database import Database, default_data_dir
from dpp.services.grid import WeekGrid, week_number
from dpp.utils import iso, week_start

from . import theme
from .gridview import WeekGridView
from .qt import (QKeySequence, QPainter, QPrintDialog, QPrinter, QRectF, QShortcut, Qt, QtWidgets,
                 page_rect, run, set_landscape)


class LiteWindow(QtWidgets.QMainWindow):
    def __init__(self, db: Database):
        super().__init__()
        self.db = db
        self.setWindowTitle("DPP خفيف — الجدول الأسبوعي")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1180, 760)
        self.grid = WeekGrid(db, week_start(dt.date.today()))

        central = QtWidgets.QWidget()
        root = QtWidgets.QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._bar())
        self.view = WeekGridView()
        self.view.changed.connect(self.on_changed)
        self.view.status.connect(lambda m: self.statusBar().showMessage(m, 6000))
        root.addWidget(self.view, 1)
        root.addWidget(self._tray())
        self.setCentralWidget(central)
        self.setStatusBar(QtWidgets.QStatusBar())

        for keys, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+P", self.print_week)):
            QShortcut(QKeySequence(keys), self).activated.connect(fn)

        self.fill_formations()
        self.refresh()

    # ------------------------------------------------------------------ الشريط
    def _bar(self):
        f = QtWidgets.QFrame()
        f.setObjectName("Bar")
        h = QtWidgets.QHBoxLayout(f)
        h.setContentsMargins(12, 8, 12, 8)
        h.setSpacing(8)
        t = QtWidgets.QLabel("DPP خفيف")
        t.setObjectName("Title")
        h.addWidget(t)

        h.addWidget(QtWidgets.QLabel("التكوين:"))
        self.cb_form = QtWidgets.QComboBox()
        self.cb_form.setMinimumWidth(180)
        self.cb_form.currentIndexChanged.connect(self.fill_sections)
        h.addWidget(self.cb_form)

        h.addWidget(QtWidgets.QLabel("القسم:"))
        self.cb_sec = QtWidgets.QComboBox()
        self.cb_sec.setMinimumWidth(170)
        self.cb_sec.currentIndexChanged.connect(self.refresh)
        h.addWidget(self.cb_sec)

        prev = QtWidgets.QPushButton("‹")
        prev.setFixedWidth(34)
        prev.clicked.connect(lambda: self.shift_week(-1))
        self.lb_week = QtWidgets.QLabel("—")
        self.lb_week.setMinimumWidth(190)
        self.lb_week.setAlignment(Qt.AlignCenter)
        nxt = QtWidgets.QPushButton("›")
        nxt.setFixedWidth(34)
        nxt.clicked.connect(lambda: self.shift_week(1))
        today = QtWidgets.QPushButton("هذا الأسبوع")
        today.clicked.connect(lambda: self.goto_week(week_start(dt.date.today())))
        for w in (prev, self.lb_week, nxt, today):
            h.addWidget(w)

        weeks = QtWidgets.QPushButton("الأسابيع السابقة…")
        weeks.clicked.connect(self.show_weeks)
        h.addWidget(weeks)
        h.addStretch(1)

        self.b_undo = QtWidgets.QPushButton("تراجع")
        self.b_undo.clicked.connect(self.undo)
        self.b_redo = QtWidgets.QPushButton("إعادة")
        self.b_redo.clicked.connect(self.redo)
        pr = QtWidgets.QPushButton("طباعة")
        pr.clicked.connect(self.print_week)
        pdf = QtWidgets.QPushButton("PDF")
        pdf.clicked.connect(self.export_pdf)
        op = QtWidgets.QPushButton("فتح قاعدة…")
        op.clicked.connect(self.open_db)
        for w in (self.b_undo, self.b_redo, pr, pdf, op):
            h.addWidget(w)
        return f

    def _tray(self):
        f = QtWidgets.QFrame()
        f.setObjectName("Tray")
        v = QtWidgets.QVBoxLayout(f)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(6)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("بطاقات المواد — اختر مادة ثم اسحب في اليوم لتحديد الوقت:"))
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة…")
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(self.fill_tray)
        row.addStretch(1)
        row.addWidget(self.search)
        v.addLayout(row)
        self.tray = QtWidgets.QListWidget()
        self.tray.setFlow(QtWidgets.QListView.LeftToRight)
        self.tray.setWrapping(False)
        self.tray.setFixedHeight(76)
        self.tray.setSpacing(4)
        self.tray.currentItemChanged.connect(self.on_tray_pick)
        v.addWidget(self.tray)
        return f

    # ------------------------------------------------------------------ تعبئة
    def fill_formations(self):
        self.cb_form.blockSignals(True)
        self.cb_form.clear()
        for r in self.db.q("SELECT id, name FROM formations WHERE archived=0 ORDER BY name"):
            self.cb_form.addItem(r[1], r[0])
        self.cb_form.blockSignals(False)
        self.fill_sections()

    def fill_sections(self):
        fid = self.cb_form.currentData()
        self.cb_sec.blockSignals(True)
        self.cb_sec.clear()
        if fid:
            for s in self.grid.sections:
                if s.formation_id == fid:
                    self.cb_sec.addItem(f"{s.short} — {s.name}", s.id)
        self.cb_sec.blockSignals(False)
        self.refresh()

    def fill_tray(self):
        sec = self.cb_sec.currentData()
        self.tray.clear()
        if not sec:
            return
        items = self.grid.subject_items(sec, only_section=False, search=self.search.text())
        for it in items[:60]:
            li = QtWidgets.QListWidgetItem(it.sname)
            li.setData(Qt.UserRole, it)
            col = theme.subject_color(it.color, it.category)
            li.setBackground(col)
            li.setForeground(theme.text_on(col))
            li.setToolTip(f"{it.sname}\nالمدة الافتراضية: {it.minutes} دقيقة"
                          + (f"\nدُرّست {it.history} مرة لهذا القسم" if it.history else ""))
            self.tray.addItem(li)

    def on_tray_pick(self, cur, _prev=None):
        self.view.armed = cur.data(Qt.UserRole) if cur else None
        if cur:
            self.statusBar().showMessage(f"المادة المختارة: {cur.text()} — اسحب في اليوم لتحديد الوقت.", 8000)

    # ------------------------------------------------------------------ تحديث
    def refresh(self):
        sec = self.cb_sec.currentData()
        self.view.set_grid(self.grid, sec)
        n = week_number(self.db, self.grid.ws)
        d1, d2 = self.grid.ws, self.grid.ws + dt.timedelta(days=6)
        self.lb_week.setText(f"الأسبوع {n} · {d1.strftime('%d/%m')} – {d2.strftime('%d/%m/%Y')}")
        self.fill_tray()
        self.update_status()

    def update_status(self):
        self.b_undo.setEnabled(bool(self.grid.undo_stack))
        self.b_redo.setEnabled(bool(getattr(self.grid, "redo_stack", [])))
        sec = self.cb_sec.currentData()
        cards = [c for c in self.grid.by_section.get(sec, [])] if sec else []
        hours = sum(c.minutes for c in cards) / 60
        conf = getattr(self.grid, "conflict_by_sid", {})
        bad = len({c.sid for c in cards if c.sid in conf})
        msg = f"{len(cards)} حصة · {hours:g} سا"
        if bad:
            msg += f" · ⚠ {bad} تعارض"
        self.statusBar().showMessage(msg)

    def on_changed(self):
        self.grid.reload()
        self.view.set_grid(self.grid, self.cb_sec.currentData())
        self.fill_tray()
        self.update_status()

    # ------------------------------------------------------------------ أسابيع
    def shift_week(self, k: int):
        self.goto_week(self.grid.ws + dt.timedelta(days=7 * k))

    def goto_week(self, ws):
        self.grid.set_week(week_start(ws))
        self.refresh()

    def show_weeks(self):
        rows = self.db.q("""SELECT t.week_start, COUNT(s.id) n, MAX(t.status)
                            FROM timetables t LEFT JOIN sessions s ON s.timetable_id=t.id
                            GROUP BY t.week_start ORDER BY t.week_start DESC""")
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("الأسابيع السابقة")
        dlg.resize(460, 460)
        v = QtWidgets.QVBoxLayout(dlg)
        v.addWidget(QtWidgets.QLabel("اختر أسبوعاً لفتحه:"))
        lst = QtWidgets.QListWidget()
        for r in rows:
            ws = r[0]
            n = week_number(self.db, ws)
            lst.addItem(f"الأسبوع {n} — {ws} — {r[1]} حصة")
            lst.item(lst.count() - 1).setData(Qt.UserRole, ws)
        v.addWidget(lst, 1)
        if not rows:
            v.addWidget(QtWidgets.QLabel("لا توجد أسابيع محفوظة في هذه القاعدة بعد."))
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Open | QtWidgets.QDialogButtonBox.Close)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        lst.itemDoubleClicked.connect(lambda _i: dlg.accept())
        if run(dlg) == QtWidgets.QDialog.Accepted and lst.currentItem():
            self.goto_week(lst.currentItem().data(Qt.UserRole))

    # ------------------------------------------------------------------ تراجع
    def undo(self):
        try:
            lab = self.grid.undo()
        except Exception as e:                       # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "تعذّر التراجع", str(e))
            return
        if lab:
            self.statusBar().showMessage(f"تراجع: {lab}", 5000)
        self.on_changed()

    def redo(self):
        try:
            lab = self.grid.redo()
        except Exception as e:                       # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "تعذّرت الإعادة", str(e))
            return
        if lab:
            self.statusBar().showMessage(f"إعادة: {lab}", 5000)
        self.on_changed()

    # ------------------------------------------------------------------ طباعة
    def _render(self, printer):
        p = QPainter(printer)
        r = page_rect(printer)
        rect = QRectF(0, 0, r.width(), r.height())
        p.save()
        sx = rect.width() / max(1, self.view.width())
        sy = rect.height() / max(1, self.view.height())
        s = min(sx, sy)
        p.scale(s, s)
        self.view.paint_grid(p, QRectF(0, 0, self.view.width(), self.view.height()), for_print=True)
        p.restore()
        p.end()

    def print_week(self):
        if not self.cb_sec.currentData():
            return
        pr = QPrinter(QPrinter.HighResolution)
        set_landscape(pr)
        dlg = QPrintDialog(pr, self)
        if run(dlg) != QtWidgets.QDialog.Accepted:
            return
        self._render(pr)
        self.statusBar().showMessage("أُرسل الجدول إلى الطابعة.", 6000)

    def export_pdf(self):
        if not self.cb_sec.currentData():
            return
        name = f"{self.cb_sec.currentText().split(' — ')[0]} — الأسبوع {week_number(self.db, self.grid.ws)}.pdf"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "حفظ PDF", name, "PDF (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        pr = QPrinter(QPrinter.HighResolution)
        set_landscape(pr)
        pr.setOutputFormat(QPrinter.PdfFormat)
        pr.setOutputFileName(path)
        self._render(pr)
        self.statusBar().showMessage(f"حُفظ: {path}", 8000)

    # ------------------------------------------------------------------ قاعدة البيانات
    def open_db(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "فتح قاعدة بيانات DPP",
                                                        str(default_data_dir()), "SQLite (*.sqlite *.db *.sqlite3)")
        if not path:
            return
        try:
            db = Database(path)
        except Exception as e:                       # noqa: BLE001
            QtWidgets.QMessageBox.critical(self, "تعذّر الفتح", str(e))
            return
        self.db = db
        self.grid = WeekGrid(db, self.grid.ws)
        self.fill_formations()
        self.statusBar().showMessage(f"فُتحت: {path}", 8000)
