"""صفحة «الأسابيع»: كل الأسابيع المبرمجة مع معلوماتها، وملاحظة لكل أسبوع، وأوامر: فتح، تصدير، نسخ، اعتماد."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QLabel, QMenu, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...services import weeks as WK
from ...utils import iso, to_date, week_start
from .. import theme
from ..widgets import confirm, error, icon, info, page_title

COLS = ["الأسبوع", "من – إلى", "الحصص", "الساعات", "الأقسام", "الحالة", "التعارضات", "منجزة", "مؤجلة", "ملغاة",
        "آخر تعديل", "بواسطة", "ملاحظة"]
NOTE_COL = len(COLS) - 1


class WeeksPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.rows: list[dict] = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("الأسابيع", "كل أسبوع فيه حصص: معلوماته وحالته ونسب التنفيذ وآخر تعديل. "
                                              "نقر مزدوج يفتحه في الجدول العام؛ الملاحظة تُكتب مباشرة في عمودها."))
        bar = QHBoxLayout()
        for ic, lab, fn, tip in (("mdi6.table-large", "فتح في الجدول العام", self.open_week, ""),
                                 ("mdi6.folder-zip-outline", "تصدير الأسبوع…", self.export_week,
                                  "مجلد فيه Word وPDF لكل قسم وملف يجمع الأقسام"),
                                 ("mdi6.content-copy", "نسخ إلى أسبوع…", self.copy_week, ""),
                                 ("mdi6.check-decagram-outline", "اعتماد", self.approve, ""),
                                 ("mdi6.lock-open-variant-outline", "إعادة فتح", self.reopen, ""),
                                 ("mdi6.refresh", "تحديث", self.refresh, "")):
            b = QPushButton(icon(ic), lab)
            b.setToolTip(tip or lab)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        bar.addWidget(self.summary)
        lay.addLayout(bar)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        hh = self.table.horizontalHeader()
        for i in range(len(COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(NOTE_COL, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed |
                                   QAbstractItemView.SelectedClicked)
        self.table.setAlternatingRowColors(True)
        self.table.cellDoubleClicked.connect(lambda r, c: self.open_week() if c != NOTE_COL else None)
        self.table.itemChanged.connect(self._note_changed)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.table, 1)
        ctx.data_changed.connect(lambda w: self.refresh() if self.isVisible() and
                                 w in ("*", "sessions", "sessions_grid", "timetables") else None)
        self.refresh()

    def showEvent(self, e):
        super().showEvent(e)
        self.refresh()

    def refresh(self):
        fids = None if self.ctx.all_formations else self.ctx.formation_ids()
        try:
            self.rows = WK.weeks(self.db, fids)
        except Exception as e:
            error(self, f"تعذر قراءة الأسابيع: {e}")
            self.rows = []
        t = theme.CURRENT
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.rows))
        cur = iso(week_start(date.today()))
        for i, w in enumerate(self.rows):
            st = WK.STATUS_LABELS[w["status"]] + (" · مستورد من aSc" if w["imported"] else "")
            vals = [f"{w['number']}", f"{to_date(w['ws']).strftime('%d/%m')} – {to_date(w['we']).strftime('%d/%m/%Y')}",
                    str(w["sessions"]), f"{w['hours']:g}", str(w["sections"]), st,
                    str(w["conflicts"]) if w["conflicts"] else "—", f"{w['done_pct']}%", f"{w['postponed_pct']}%",
                    f"{w['cancelled_pct']}%", (w["last"] or "")[:16], w["by"], w["note"]]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if c != NOTE_COL:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    it.setTextAlignment(Qt.AlignCenter)
                if c == 0:
                    it.setData(Qt.UserRole, w["ws"])
                    if w["ws"] == cur:
                        f = it.font()
                        f.setBold(True)
                        it.setFont(f)
                        it.setText(f"{w['number']} (الحالي)")
                if c == 5 and w["status"] == "approved":
                    it.setForeground(QBrush(QColor(t["ok"])))
                if c == 6 and w["conflicts"]:
                    it.setForeground(QBrush(QColor(t["bad"])))
                self.table.setItem(i, c, it)
        self.table.blockSignals(False)
        n_app = sum(1 for w in self.rows if w["status"] == "approved")
        self.summary.setText(f"{len(self.rows)} أسبوعاً · {n_app} معتمد · "
                             f"{sum(w['sessions'] for w in self.rows)} حصة")

    def current(self) -> dict | None:
        r = self.table.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _need(self) -> dict | None:
        w = self.current()
        if w is None:
            info(self, "اختر أسبوعاً.")
        return w

    def _note_changed(self, it: QTableWidgetItem):
        if it.column() != NOTE_COL or not (0 <= it.row() < len(self.rows)):
            return
        w = self.rows[it.row()]
        WK.set_note(self.db, to_date(w["ws"]), it.text())
        w["note"] = it.text().strip()

    def _menu(self, pos):
        if self.table.itemAt(pos) is None:
            return
        m = QMenu(self)
        m.addAction(icon("mdi6.table-large"), "فتح في الجدول العام", self.open_week)
        m.addAction(icon("mdi6.folder-zip-outline"), "تصدير الأسبوع…", self.export_week)
        m.addAction(icon("mdi6.content-copy"), "نسخ إلى أسبوع…", self.copy_week)
        m.addSeparator()
        m.addAction(icon("mdi6.check-decagram-outline"), "اعتماد", self.approve)
        m.addAction(icon("mdi6.lock-open-variant-outline"), "إعادة فتح كمسودة", self.reopen)
        m.addAction(icon("mdi6.note-edit-outline"), "تعديل الملاحظة",
                    lambda: self.table.editItem(self.table.item(self.table.currentRow(), NOTE_COL)))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def open_week(self):
        w = self._need()
        if not w:
            return
        win = self.window()
        if hasattr(win, "show_page"):
            page = win.show_page("master")
            page.set_week(to_date(w["ws"]))

    def export_week(self):
        w = self._need()
        if w:
            from ..word_ui import export_week_dialog
            export_week_dialog(self, self.ctx, to_date(w["ws"]))

    def copy_week(self):
        w = self._need()
        if not w:
            return
        src = to_date(w["ws"])
        dlg = QDialog(self)
        dlg.setWindowTitle("نسخ أسبوع")
        v = QVBoxLayout(dlg)
        f = QFormLayout()
        de = QDateEdit()
        nxt = src + timedelta(days=7)
        de.setDate(QDate(nxt.year, nxt.month, nxt.day))
        de.setCalendarPopup(True)
        de.setDisplayFormat("dd/MM/yyyy")
        f.addRow(f"نسخ الأسبوع {w['number']} إلى الأسبوع الذي فيه", de)
        v.addLayout(f)
        hint = QLabel("تُنسخ الحصص كحصص جديدة مبرمجة؛ ما يتعارض أو يقع في يوم محجوب لا يُنسخ ويُذكر سببه.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        v.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        dst = week_start(de.date().toPython())
        if dst == src:
            error(self, "الأسبوع الهدف هو نفسه.")
            return
        fids = None if self.ctx.all_formations else self.ctx.formation_ids()
        try:
            n, skipped = WK.copy_week(self.db, src, dst, fids)
        except Exception as e:
            error(self, f"تعذر النسخ: {e}")
            return
        msg = f"نُسخت {n} حصة."
        if skipped:
            msg += f"\n\nلم يُنسخ {len(skipped)}:\n• " + "\n• ".join(skipped[:10])
        info(self, msg)
        self.ctx.changed("sessions")
        self.refresh()

    def approve(self):
        w = self._need()
        if w and confirm(self, f"اعتماد الأسبوع {w['number']}؟ تُحفظ نسخة، ولا يُعدَّل إلا بعد إعادة فتحه."):
            n = WK.approve_week(self.db, to_date(w["ws"]), None if self.ctx.all_formations else self.ctx.formation_ids())
            self.ctx.changed("timetables")
            self.refresh()
            info(self, f"اعتُمد {n} جدول." if n else "الأسبوع معتمد أصلاً.")

    def reopen(self):
        w = self._need()
        if w and confirm(self, f"إعادة فتح الأسبوع {w['number']} كمسودة؟"):
            WK.reopen_week(self.db, to_date(w["ws"]), None if self.ctx.all_formations else self.ctx.formation_ids())
            self.ctx.changed("timetables")
            self.refresh()
