"""المخطط الأسبوعي التفاعلي: عرض، سحب وإفلات، قائمة سياقية، شريط بطاقات المواد."""
from __future__ import annotations

import json
from datetime import date, timedelta

from PySide6.QtCore import QDate, QMimeData, QPoint, QRectF, QSize, Qt, QTime, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QDateEdit, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton, QScrollArea,
                               QSlider, QTimeEdit, QToolButton, QVBoxLayout, QWidget)

from ...services import absences as A
from ...services import timetables as T
from ...utils import (ALLOWED_DURATIONS, DAY_NAMES, FULL_DAY, STATUS_LABELS, hm, hm_range, iso, parse_rest_days, to_date,
                      week_days, week_start)
from .. import theme
from ..context import AppContext
from ..widgets import confirm, error, icon, info, warn

MIME = "application/x-dpp-requirement"
HEADER_H = 44
TIME_W = 74


def _text_on(bg: str) -> str:
    c = QColor(bg)
    return "#111111" if (c.red() * 299 + c.green() * 587 + c.blue() * 114) / 1000 > 150 else "#FFFFFF"


# ===================================================================== لوحة الشبكة
class PlannerGrid(QWidget):
    session_moved = Signal(int, object, int)          # id، التاريخ، دقيقة البداية
    requirement_dropped = Signal(int, object, int)    # requirement id، التاريخ، الدقيقة
    session_menu = Signal(int, QPoint)
    session_activated = Signal(int)
    empty_menu = Signal(object, int, QPoint)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.days: list[date] = []
        self.sessions: list[dict] = []
        self.start, self.end, self.slot = 480, 990, 30
        self.lunch = (720, 780)
        self.col_w, self.row_h = 170, 26
        self.zoom = 1.0
        self.selected: int | None = None
        self.blocked: set[date] = set()
        self._press: tuple | None = None
        self._ghost: tuple | None = None   # (date, minute, length)
        self._rects: list[tuple[QRectF, dict]] = []

    # -------------------------------------------------------------- إعداد
    def configure(self, days, sessions, start, end, slot, lunch, blocked):
        self.days, self.sessions = days, sessions
        self.start, self.end, self.slot, self.lunch = start, end, slot, lunch
        self.blocked = blocked
        self._relayout()

    def set_sizes(self, col_w=None, row_h=None, zoom=None):
        if col_w:
            self.col_w = col_w
        if row_h:
            self.row_h = row_h
        if zoom:
            self.zoom = zoom
        self._relayout()

    def base_cw(self):
        return int(self.col_w * self.zoom)

    def cw(self):
        """عرض العمود: الحجم المختار، ويتمدد لملء المساحة المتاحة إن كانت أوسع."""
        n = max(1, len(self.days))
        return max(self.base_cw(), int((self.width() - TIME_W - 2) / n))

    def rh(self):
        return int(self.row_h * self.zoom)

    def nslots(self):
        return max(1, (self.end - self.start) // self.slot)

    def _relayout(self):
        self.setMinimumSize(TIME_W + self.base_cw() * max(1, len(self.days)) + 2, HEADER_H + self.rh() * self.nslots() + 2)
        self._compute_rects()
        self.update()

    # إحداثيات RTL: عمود الوقت يمين، اليوم الأول بعده نحو اليسار
    def col_x(self, ci: int) -> float:
        return self.width() - TIME_W - (ci + 1) * self.cw()

    def y_of(self, minute: int) -> float:
        return HEADER_H + (minute - self.start) / self.slot * self.rh()

    def hit(self, pos) -> tuple[date | None, int | None]:
        x, y = pos.x(), pos.y()
        if y < HEADER_H:
            return None, None
        ci = int((self.width() - TIME_W - x) // self.cw())
        if ci < 0 or ci >= len(self.days):
            return None, None
        m = self.start + int((y - HEADER_H) // self.rh()) * self.slot
        return self.days[ci], min(max(self.start, m), self.end - self.slot)

    def _compute_rects(self):
        self._rects = []
        for ci, d in enumerate(self.days):
            day = sorted([s for s in self.sessions if s["date"] == iso(d)], key=lambda s: (s["start_min"], -s["end_min"]))
            lanes: list[int] = []      # نهاية كل مسار
            assign = {}
            clusters, cur, cur_end = [], [], -1
            for s in day:
                if cur and s["start_min"] >= cur_end:
                    clusters.append(cur)
                    cur, cur_end = [], -1
                cur.append(s)
                cur_end = max(cur_end, s["end_min"])
            if cur:
                clusters.append(cur)
            for cl in clusters:
                lanes = []
                for s in cl:
                    for li, e in enumerate(lanes):
                        if e <= s["start_min"]:
                            lanes[li] = s["end_min"]
                            assign[s["id"]] = li
                            break
                    else:
                        lanes.append(s["end_min"])
                        assign[s["id"]] = len(lanes) - 1
                n = len(lanes)
                for s in cl:
                    li = assign[s["id"]]
                    w = (self.cw() - 6) / n
                    x = self.col_x(ci) + self.cw() - 3 - (li + 1) * w   # المسار الأول يمين
                    y0 = self.y_of(max(self.start, s["start_min"]))
                    y1 = self.y_of(min(self.end, s["end_min"]))
                    self._rects.append((QRectF(x + 1, y0 + 1, w - 2, y1 - y0 - 2), s))

    # -------------------------------------------------------------- الرسم
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._compute_rects()

    def paintEvent(self, _):
        self._compute_rects()
        t = theme.CURRENT
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(t["surface"]))
        W = self.width()
        n = self.nslots()
        # الخلفيات: أيام محجوبة واستراحة الغداء
        for ci, d in enumerate(self.days):
            if d in self.blocked:
                p.fillRect(QRectF(self.col_x(ci), HEADER_H, self.cw(), n * self.rh()), QColor(t["grid"]))
        ls, le = self.lunch
        if ls < le:
            y0, y1 = self.y_of(ls), self.y_of(le)
            c = QColor(t["warn"])
            c.setAlpha(28)
            p.fillRect(QRectF(self.col_x(len(self.days) - 1), y0, self.cw() * len(self.days), y1 - y0), c)
        # خطوط الشبكة
        pen = QPen(QColor(t["grid"]))
        for i in range(n + 1):
            y = HEADER_H + i * self.rh()
            m = self.start + i * self.slot
            pen.setStyle(Qt.SolidLine if m % 60 == 0 else Qt.DotLine)
            p.setPen(pen)
            p.drawLine(0, int(y), W, int(y))
            if m % 60 == 0 and i < n:
                p.setPen(QColor(t["muted"]))
                p.drawText(QRectF(W - TIME_W, y, TIME_W - 8, self.rh()), Qt.AlignRight | Qt.AlignTop, hm(m))
        p.setPen(QPen(QColor(t["border"])))
        for ci in range(len(self.days) + 1):
            x = W - TIME_W - ci * self.cw()
            p.drawLine(int(x), 0, int(x), HEADER_H + n * self.rh())
        # رؤوس الأيام
        p.fillRect(QRectF(0, 0, W, HEADER_H), QColor(t["header"]))
        today = date.today()
        for ci, d in enumerate(self.days):
            r = QRectF(self.col_x(ci), 0, self.cw(), HEADER_H)
            f = QFont(self.font())
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor(t["accent"] if d == today else t["text"]))
            p.drawText(r.adjusted(0, 4, 0, -HEADER_H / 2), Qt.AlignCenter, DAY_NAMES[(d.weekday() + 1) % 7])
            f.setBold(False)
            p.setFont(f)
            p.setPen(QColor(t["muted"]))
            lab = d.strftime("%d/%m/%Y") + ("  (محجوب)" if d in self.blocked else "")
            p.drawText(r.adjusted(0, HEADER_H / 2, 0, -2), Qt.AlignCenter, lab)
        p.setPen(QColor(t["muted"]))
        p.drawText(QRectF(W - TIME_W, 0, TIME_W, HEADER_H), Qt.AlignCenter, "التوقيت")
        # الحصص
        fm = QFontMetrics(self.font())
        for r, s in self._rects:
            base = s.get("color") or "#4F7CAC"
            bg = QColor(base)
            if s["status"] in ("cancelled", "postponed"):
                bg.setAlpha(90)
            p.setPen(QPen(QColor(t["accent"]) if s["id"] == self.selected else bg.darker(130),
                          2.5 if s["id"] == self.selected else 1))
            p.setBrush(bg)
            p.drawRoundedRect(r, 5, 5)
            p.setPen(QColor(_text_on(base)))
            lines = [s.get("sshort") if r.width() < 90 else s["sname"]]
            if s.get("gtext"):
                lines.append(s["gtext"])
            teacher = s.get("stname") or s.get("tname")
            if teacher:
                lines.append(("↻ " if s.get("stname") else "") + teacher)
            if s.get("rname"):
                lines.append(s["rname"])
            lines.append(hm_range(s["start_min"], s["end_min"]))
            tag = []
            if s["status"] != "planned":
                tag.append(STATUS_LABELS[s["status"]])
            if s.get("is_makeup"):
                tag.append("تعويضية")
            if tag:
                lines.append("[" + "، ".join(tag) + "]")
            maxl = max(1, int((r.height() - 4) // fm.height()))
            text = "\n".join(fm.elidedText(l, Qt.ElideLeft, int(r.width() - 8)) for l in lines[:maxl])
            p.drawText(r.adjusted(4, 2, -4, -2), Qt.AlignRight | Qt.AlignTop, text)
            if s["status"] == "done":
                p.drawText(r.adjusted(3, 2, -3, -2), Qt.AlignLeft | Qt.AlignTop, "✓")
        # معاينة الإفلات
        if self._ghost:
            d, m, length = self._ghost
            if d in self.days:
                ci = self.days.index(d)
                g = QRectF(self.col_x(ci) + 3, self.y_of(m), self.cw() - 6, self.y_of(m + length) - self.y_of(m))
                c = QColor(t["accent"])
                c.setAlpha(60)
                p.setBrush(c)
                p.setPen(QPen(QColor(t["accent"]), 1.5, Qt.DashLine))
                p.drawRoundedRect(g, 5, 5)
        p.end()

    # -------------------------------------------------------------- الفأرة
    def session_at(self, pos):
        for r, s in reversed(self._rects):
            if r.contains(pos):
                return s
        return None

    def mousePressEvent(self, e):
        s = self.session_at(e.position())
        self.selected = s["id"] if s else None
        self.update()
        if e.button() == Qt.LeftButton and s:
            self._press = (e.position(), s)
        elif e.button() == Qt.RightButton:
            if s:
                self.session_menu.emit(s["id"], e.globalPosition().toPoint())
            else:
                d, m = self.hit(e.position())
                if d:
                    self.empty_menu.emit(d, m, e.globalPosition().toPoint())

    def mouseMoveEvent(self, e):
        if self._press and (e.position() - self._press[0]).manhattanLength() > 8:
            s = self._press[1]
            self._press = None
            drag = QDrag(self)
            md = QMimeData()
            md.setData("application/x-dpp-session", json.dumps({"id": s["id"], "len": s["end_min"] - s["start_min"]}).encode())
            drag.setMimeData(md)
            drag.exec(Qt.MoveAction)
            self._ghost = None
            self.update()
        else:
            s = self.session_at(e.position())
            self.setToolTip(s["tooltip"] if s else "")

    def mouseReleaseEvent(self, e):
        self._press = None

    def mouseDoubleClickEvent(self, e):
        s = self.session_at(e.position())
        if s:
            self.session_activated.emit(s["id"])

    # -------------------------------------------------------------- السحب والإفلات
    def _payload(self, e):
        md = e.mimeData()
        if md.hasFormat("application/x-dpp-session"):
            return "s", json.loads(bytes(md.data("application/x-dpp-session")).decode())
        if md.hasFormat(MIME):
            return "r", json.loads(bytes(md.data(MIME)).decode())
        return None, None

    def dragEnterEvent(self, e):
        kind, _ = self._payload(e)
        if kind:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        kind, data = self._payload(e)
        d, m = self.hit(e.position())
        if not kind or d is None:
            self._ghost = None
            e.ignore()
        else:
            length = data["len"] if data["len"] else (self.end - self.start)
            if data["len"] == 0:
                m = self.start
            self._ghost = (d, m, length)
            e.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, e):
        self._ghost = None
        self.update()

    def dropEvent(self, e):
        kind, data = self._payload(e)
        d, m = self.hit(e.position())
        self._ghost = None
        self.update()
        if not kind or d is None:
            return
        if data.get("len") == 0:
            m = self.start
        e.acceptProposedAction()
        if kind == "s":
            self.session_moved.emit(data["id"], d, m)
        else:
            self.requirement_dropped.emit(data["id"], d, m)


# ===================================================================== بطاقات المواد
class CardList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setFlow(QListWidget.LeftToRight)
        self.setViewMode(QListWidget.IconMode)
        self.setWrapping(False)
        self.setDragEnabled(True)
        self.setFixedHeight(88)
        self.setSpacing(6)
        self.setLayoutDirection(Qt.RightToLeft)

    def startDrag(self, actions):
        it = self.currentItem()
        if not it:
            return
        d = it.data(Qt.UserRole)
        drag = QDrag(self)
        md = QMimeData()
        md.setData(MIME, json.dumps(d).encode())
        drag.setMimeData(md)
        drag.exec(Qt.CopyAction)


# ===================================================================== نافذة تعديل حصة
class SessionDialog(QDialog):
    def __init__(self, parent, db, session: dict):
        super().__init__(parent)
        self.db, self.s = db, session
        self.setWindowTitle(f"الحصة: {session['sname']}")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.teacher = QComboBox()
        self.teacher.addItem("—", None)
        qual = {r[0] for r in db.q("SELECT teacher_id FROM teacher_subjects WHERE subject_id=?", (session["subject_id"],))}
        for r in db.q("SELECT id, full_name FROM teachers WHERE active=1 ORDER BY full_name"):
            self.teacher.addItem(("✓ " if r["id"] in qual else "   ") + r["full_name"], r["id"])
        self.teacher.setCurrentIndex(max(0, self.teacher.findData(session["teacher_id"])))
        self.room = QComboBox()
        self.room.addItem("—", None)
        for r in db.q("SELECT id, name FROM rooms ORDER BY name"):
            self.room.addItem(r["name"], r["id"])
        self.room.setCurrentIndex(max(0, self.room.findData(session["room_id"])))
        self.date = QDateEdit(QDate.fromString(session["date"], "yyyy-MM-dd"))
        self.date.setCalendarPopup(True)
        self.date.setDisplayFormat("dd/MM/yyyy")
        self.start = QTimeEdit(QTime(session["start_min"] // 60, session["start_min"] % 60))
        self.start.setDisplayFormat("HH:mm")
        self.dur = QComboBox()
        cur = session["end_min"] - session["start_min"]
        opts = sorted(set(ALLOWED_DURATIONS) | {cur})
        for m in opts:
            self.dur.addItem(f"{m / 60:g} سا", m)
        self.dur.addItem("يوم كامل", FULL_DAY)
        self.dur.setCurrentIndex(self.dur.findData(cur))
        self.status = QComboBox()
        for k, v in STATUS_LABELS.items():
            self.status.addItem(v, k)
        self.status.setCurrentIndex(self.status.findData(session["status"]))
        self.note = QPlainTextEdit(session.get("note") or "")
        self.note.setMaximumHeight(70)
        form.addRow("الأستاذ (✓ مؤهل)", self.teacher)
        form.addRow("القاعة", self.room)
        form.addRow("التاريخ", self.date)
        form.addRow("البداية", self.start)
        form.addRow("المدة", self.dur)
        form.addRow("الحالة", self.status)
        form.addRow("ملاحظة", self.note)
        lay.addLayout(form)
        self.err = QLabel()
        self.err.setWordWrap(True)
        self.err.setStyleSheet(f"color:{theme.CURRENT['bad']}")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def changes(self) -> dict:
        st = self.start.time().hour() * 60 + self.start.time().minute()
        dur = self.dur.currentData()
        if dur == FULL_DAY:
            st, en = self.db.get_int("day_start"), self.db.get_int("day_end")
        else:
            en = st + dur
        out = {"teacher_id": self.teacher.currentData(), "room_id": self.room.currentData(),
               "date": self.date.date().toString("yyyy-MM-dd"), "start_min": st, "end_min": en,
               "status": self.status.currentData(), "note": self.note.toPlainText().strip()}
        return {k: v for k, v in out.items() if v != self.s.get(k)}

    def _ok(self):
        ch = self.changes()
        if not ch:
            self.reject()
            return
        try:
            T.update_session(self.db, self.s["id"], **ch)
            self.accept()
        except T.ConflictError as e:
            self.err.setText("تعارضات:\n• " + "\n• ".join(e.conflicts))
            if confirm(self, "توجد تعارضات:\n• " + "\n• ".join(e.conflicts) + "\n\nهل تريد الحفظ رغم ذلك؟", danger=True):
                T.update_session(self.db, self.s["id"], force=True, **ch)
                self.accept()


# ===================================================================== الصفحة
class PlannerPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.ws = week_start(date.today())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 0)
        lay.setSpacing(6)

        # --- شريط التحكم
        bar = QHBoxLayout()
        self.prev_b = QToolButton()
        self.prev_b.setIcon(icon("mdi6.chevron-right"))
        self.prev_b.setToolTip("الأسبوع السابق (Ctrl+PgUp)")
        self.next_b = QToolButton()
        self.next_b.setIcon(icon("mdi6.chevron-left"))
        self.next_b.setToolTip("الأسبوع التالي (Ctrl+PgDown)")
        self.date_e = QDateEdit()
        self.date_e.setCalendarPopup(True)
        self.date_e.setDisplayFormat("dd/MM/yyyy")
        self.today_b = QPushButton("هذا الأسبوع")
        self.week_lbl = QLabel()
        self.week_lbl.setObjectName("SectionTitle")
        self.prev_b.clicked.connect(lambda: self.set_week(self.ws - timedelta(days=7)))
        self.next_b.clicked.connect(lambda: self.set_week(self.ws + timedelta(days=7)))
        self.today_b.clicked.connect(lambda: self.set_week(date.today()))
        self.date_e.dateChanged.connect(lambda q: self.set_week(q.toPython()))
        self.mode = QComboBox()
        for k, v in [("section", "حسب القسم"), ("group", "حسب الفوج"), ("teacher", "حسب الأستاذ"), ("room", "حسب القاعة"),
                     ("all", "كل الحصص")]:
            self.mode.addItem(v, k)
        self.target = QComboBox()
        self.target.setMinimumWidth(260)
        self.mode.currentIndexChanged.connect(self._fill_targets)
        self.target.currentIndexChanged.connect(self.refresh)
        for w in (self.prev_b, self.date_e, self.next_b, self.today_b, self.week_lbl):
            bar.addWidget(w)
        bar.addStretch()
        bar.addWidget(QLabel("العرض:"))
        bar.addWidget(self.mode)
        bar.addWidget(self.target)
        lay.addLayout(bar)

        # --- شريط الحالة والأحجام
        bar2 = QHBoxLayout()
        self.tt_status = QLabel()
        bar2.addWidget(self.tt_status)
        bar2.addStretch()

        def slider(label, lo, hi, val):
            bar2.addWidget(QLabel(label))
            s = QSlider(Qt.Horizontal)
            s.setRange(lo, hi)
            s.setValue(val)
            s.setFixedWidth(110)
            bar2.addWidget(s)
            return s
        self.col_s = slider("عرض الأعمدة", 90, 360, 170)
        self.row_s = slider("ارتفاع الصفوف", 16, 60, 26)
        self.zoom_s = slider("تكبير", 50, 200, 100)
        reset = QToolButton()
        reset.setIcon(icon("mdi6.restore"))
        reset.setToolTip("إعادة الحجم الافتراضي")
        reset.clicked.connect(self.reset_sizes)
        bar2.addWidget(reset)
        lay.addLayout(bar2)

        # --- أدوات الأسبوع
        bar3 = QHBoxLayout()
        for ic, lab, tip, fn in (
                ("mdi6.auto-fix", "برمجة هذا القسم آلياً", "يكمل الأسبوع للقسم المعروض فقط (بالأولويات، والحصص المقفلة لا تتحرك)",
                 self.auto_section),
                ("mdi6.content-save-cog-outline", "حفظ كأسبوع نموذجي", "يحفظ حصص هذا الأسبوع للقسم كنموذج", self.save_tpl),
                ("mdi6.file-replace-outline", "تطبيق الأسبوع النموذجي", "يضع حصص النموذج في هذا الأسبوع (يتجاوز المتعارض)",
                 self.apply_tpl),
                ("mdi6.content-duplicate", "نسخ يوم…", "نسخ حصص يوم إلى يوم آخر", self.copy_day),
                ("mdi6.clipboard-check-outline", "فحص الأسبوع", "تعارضات، حصص بلا أستاذ، أيام طويلة أو بلا غداء، ساعات ناقصة",
                 self.check_week)):
            b = QPushButton(icon(ic), lab)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            bar3.addWidget(b)
        bar3.addStretch()
        lay.addLayout(bar3)

        self.grid = PlannerGrid()
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.grid)
        from PySide6.QtWidgets import QSplitter, QTableWidget, QTableWidgetItem
        self._QTWI = QTableWidgetItem
        side = QFrame()
        side.setObjectName("Card")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(8, 6, 8, 6)
        t1 = QLabel("ما ينقص هذا الأسبوع")
        t1.setObjectName("PanelTitle")
        sv.addWidget(t1)
        self.need_t = QTableWidget(0, 4)
        self.need_t.setHorizontalHeaderLabels(["المادة", "المطلوب", "الموضوع", "الباقي"])
        self.need_t.verticalHeader().setVisible(False)
        self.need_t.setEditTriggers(QTableWidget.NoEditTriggers)
        self.need_t.setSelectionBehavior(QTableWidget.SelectRows)
        self.need_t.cellDoubleClicked.connect(self._place_need)
        self.need_t.setToolTip("انقر مرتين على مادة لوضعها في أول وقت متاح للقسم والأستاذ")
        sv.addWidget(self.need_t, 3)
        t2 = QLabel("ملخص الأيام (الدراسة من 7 سا + الغداء)")
        t2.setObjectName("PanelTitle")
        sv.addWidget(t2)
        self.day_t = QTableWidget(0, 3)
        self.day_t.setHorizontalHeaderLabels(["اليوم", "الدراسة", "الغداء"])
        self.day_t.verticalHeader().setVisible(False)
        self.day_t.setEditTriggers(QTableWidget.NoEditTriggers)
        sv.addWidget(self.day_t, 2)
        self.body = QSplitter(Qt.Horizontal)
        self.body.addWidget(self.scroll)
        self.body.addWidget(side)
        self.body.setStretchFactor(0, 4)
        self.body.setStretchFactor(1, 1)
        self.body.setSizes([900, 300])
        lay.addWidget(self.body, 1)
        for s in (self.col_s, self.row_s, self.zoom_s):
            s.valueChanged.connect(self._sizes_changed)

        # --- شريط البطاقات
        strip = QFrame()
        strip.setObjectName("CardStrip")
        sl = QVBoxLayout(strip)
        sl.setContentsMargins(6, 4, 6, 4)
        self.strip_lbl = QLabel("بطاقات المواد — اسحب بطاقة إلى الخانة المطلوبة لإنشاء حصة")
        self.strip_lbl.setObjectName("Muted")
        sl.addWidget(self.strip_lbl)
        self.cards = CardList()
        sl.addWidget(self.cards)
        lay.addWidget(strip)

        self.grid.session_moved.connect(self._moved)
        self.grid.requirement_dropped.connect(self._dropped)
        self.grid.session_menu.connect(self._menu)
        self.grid.session_activated.connect(self.edit_session)
        self.grid.empty_menu.connect(self._empty_menu)
        ctx.data_changed.connect(lambda w: self.refresh() if w in ("*", "sessions", "timetables", "requirements",
                                                                  "calendar_events", "subjects") else None)
        ctx.data_changed.connect(lambda w: self._fill_targets() if w in ("*", "sections", "groups_", "teachers", "rooms")
                                 else None)
        ctx.formation_changed.connect(lambda _: self._fill_targets())
        self._restore_sizes()
        self._fill_targets()
        self.set_week(self.ws)

    # -------------------------------------------------------------- أحجام
    def _restore_sizes(self):
        try:
            d = json.loads(self.ctx.db.get_setting("planner_sizes") or "{}")
            self.col_s.setValue(d.get("col", 170))
            self.row_s.setValue(d.get("row", 26))
            self.zoom_s.setValue(d.get("zoom", 100))
        except (ValueError, TypeError):
            pass

    def _sizes_changed(self):
        self.grid.set_sizes(self.col_s.value(), self.row_s.value(), self.zoom_s.value() / 100)
        self.ctx.db.set_setting("planner_sizes", json.dumps({"col": self.col_s.value(), "row": self.row_s.value(),
                                                             "zoom": self.zoom_s.value()}))

    def reset_sizes(self):
        self.col_s.setValue(170)
        self.row_s.setValue(26)
        self.zoom_s.setValue(100)

    def zoom_in(self):
        self.zoom_s.setValue(min(200, self.zoom_s.value() + 10))

    def zoom_out(self):
        self.zoom_s.setValue(max(50, self.zoom_s.value() - 10))

    # -------------------------------------------------------------- مرشحات
    def _fill_targets(self):
        db, fid = self.ctx.db, self.ctx.formation_id
        mode = self.mode.currentData()
        cur = self.target.currentData()
        self.target.blockSignals(True)
        self.target.clear()
        if mode == "section":
            for r in self.ctx.q("SELECT id, short, name FROM sections WHERE formation_id=? ORDER BY short", (fid or -1,)):
                self.target.addItem(f"{r['short']} — {r['name']}", r["id"])
        elif mode == "group":
            for r in self.ctx.q("""SELECT g.id, sec.short, g.name FROM groups_ g JOIN sections sec ON sec.id=g.section_id
                             WHERE sec.formation_id=? ORDER BY sec.short, g.is_whole DESC""", (fid or -1,)):
                self.target.addItem(f"{r['short']} / {r['name']}", r["id"])
        elif mode == "teacher":
            for r in db.q("SELECT id, full_name, rank FROM teachers WHERE active=1 ORDER BY full_name"):
                self.target.addItem(r["full_name"] + (f" ({r['rank']})" if r["rank"] else ""), r["id"])
        elif mode == "room":
            for r in db.q("SELECT id, name FROM rooms ORDER BY name"):
                self.target.addItem(r["name"], r["id"])
        else:
            self.target.addItem("كل حصص التكوين", None)
        i = self.target.findData(cur)
        self.target.setCurrentIndex(i if i >= 0 else 0)
        self.target.blockSignals(False)
        self.refresh()

    def select(self, mode: str, target_id):
        self.mode.setCurrentIndex(self.mode.findData(mode))
        i = self.target.findData(target_id)
        if i >= 0:
            self.target.setCurrentIndex(i)

    def set_week(self, d):
        self.ws = week_start(d)
        self.date_e.blockSignals(True)
        self.date_e.setDate(QDate(self.ws.year, self.ws.month, self.ws.day))
        self.date_e.blockSignals(False)
        days = week_days(self.ws)
        self.week_lbl.setText(f"الأسبوع {days[0].strftime('%d/%m')} – {days[-1].strftime('%d/%m/%Y')}")
        self.refresh()

    # -------------------------------------------------------------- تحميل البيانات
    def _fid(self):
        """التكوين المعني: تكوين القسم/الفوج المعروض، وإلا التكوين الحالي."""
        mode, tid = self.mode.currentData(), self.target.currentData()
        if mode == "section" and tid:
            return self.ctx.db.scalar("SELECT formation_id FROM sections WHERE id=?", (tid,), self.ctx.formation_id)
        if mode == "group" and tid:
            return self.ctx.db.scalar("""SELECT s.formation_id FROM groups_ g JOIN sections s ON s.id=g.section_id
                                         WHERE g.id=?""", (tid,), self.ctx.formation_id)
        return self.ctx.formation_id

    def timetable_id(self, create=False):
        fid = self._fid()
        if not fid:
            return None
        r = self.ctx.db.one("SELECT id FROM timetables WHERE formation_id=? AND week_start=? ORDER BY version DESC LIMIT 1",
                            (fid, iso(self.ws)))
        if r:
            return r["id"]
        return T.get_or_create_timetable(self.ctx.db, fid, self.ws) if create else None

    def _load_sessions(self) -> list[dict]:
        db, fid = self.ctx.db, self.ctx.formation_id
        days = week_days(self.ws)
        rows = db.q("""SELECT s.*, sub.name sname, sub.short sshort, sub.color, t.full_name tname, st.full_name stname,
                              rm.name rname, GROUP_CONCAT(sec.short || '/' || g.name, '، ') gtext,
                              GROUP_CONCAT(g.id) gids, GROUP_CONCAT(DISTINCT sec.id) secids, tt.formation_id fid
                       FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                       LEFT JOIN teachers t ON t.id=s.teacher_id LEFT JOIN teachers st ON st.id=s.substitute_id
                       LEFT JOIN rooms rm ON rm.id=s.room_id LEFT JOIN session_groups sg ON sg.session_id=s.id
                       LEFT JOIN groups_ g ON g.id=sg.group_id LEFT JOIN sections sec ON sec.id=g.section_id
                       LEFT JOIN timetables tt ON tt.id=s.timetable_id
                       WHERE s.date>=? AND s.date<=? GROUP BY s.id""", (iso(days[0]), iso(days[-1])))
        mode, tid = self.mode.currentData(), self.target.currentData()
        fids = set(self.ctx.formation_ids())
        units = T._group_units(db)
        out = []
        for r in rows:
            d = dict(r)
            gids = [int(x) for x in (d["gids"] or "").split(",") if x]
            if mode == "section" and str(tid) not in (d["secids"] or "").split(","):
                continue
            if mode == "group":
                mine = units.get(tid, {tid}) if tid else set()
                if not any(mine & units.get(g, {g}) for g in gids):
                    continue
            if mode == "teacher" and (d["substitute_id"] or d["teacher_id"]) != tid and d["teacher_id"] != tid:
                continue
            if mode == "room" and d["room_id"] != tid:
                continue
            if mode == "all" and d["fid"] not in fids:
                continue
            d["tooltip"] = (f"{d['sname']}\n{d['gtext'] or ''}\nالأستاذ: {d['tname'] or '—'}"
                            + (f"\nالمستخلف: {d['stname']}" if d["stname"] else "")
                            + f"\nالقاعة: {d['rname'] or '—'}\n{hm_range(d['start_min'], d['end_min'])}"
                            + f"\nالحالة: {STATUS_LABELS[d['status']]}" + (f"\n{d['note']}" if d["note"] else ""))
            out.append(d)
        return out

    def refresh(self):
        db = self.ctx.db
        if not hasattr(self, "grid"):
            return
        fid = self._fid()
        days = week_days(self.ws)
        rest = parse_rest_days(db.scalar("SELECT rest_days FROM formations WHERE id=?", (fid,), "")) if fid else set()
        from ...services.calendar import blocked_dates
        blocked = blocked_dates(db, fid, days[0], days[-1]) if fid else set()
        sessions = self._load_sessions()
        shown = [d for i, d in enumerate(days) if i not in rest or any(s["date"] == iso(d) for s in sessions)]
        self.grid.configure(shown, sessions, db.get_int("day_start"), db.get_int("day_end"), db.get_int("slot_minutes"),
                            (db.get_int("lunch_start"), db.get_int("lunch_end")), blocked)
        tt = self.timetable_id()
        if tt:
            r = db.one("SELECT status, version, note FROM timetables WHERE id=?", (tt,))
            st = "معتمد ✓" if r["status"] == "approved" else "مسودة"
            self.tt_status.setText(f"حالة الجدول: {st} — النسخة {r['version']}" + (f" — {r['note']}" if r["note"] else ""))
            self.tt_status.setStyleSheet(f"color:{theme.CURRENT['ok'] if r['status'] == 'approved' else theme.CURRENT['warn']}")
        else:
            self.tt_status.setText("لا يوجد جدول لهذا الأسبوع بعد.")
            self.tt_status.setStyleSheet(f"color:{theme.CURRENT['muted']}")
        self._fill_cards(sessions)
        self._fill_side()
        self.ctx.status.emit(f"{len(sessions)} حصة معروضة")

    def _fill_cards(self, sessions):
        self.cards.clear()
        db, fid = self.ctx.db, self.ctx.formation_id
        mode, tid = self.mode.currentData(), self.target.currentData()
        if mode not in ("section", "group") or not tid:
            self.strip_lbl.setText("بطاقات المواد تظهر عند العرض حسب القسم أو الفوج.")
            return
        if mode == "section":
            reqs = db.q("""SELECT r.*, s.name sname, s.short sshort, s.color, g.name gname FROM requirements r
                           JOIN subjects s ON s.id=r.subject_id JOIN groups_ g ON g.id=r.group_id
                           WHERE g.section_id=?""", (tid,))
        else:
            reqs = db.q("""SELECT r.*, s.name sname, s.short sshort, s.color, g.name gname FROM requirements r
                           JOIN subjects s ON s.id=r.subject_id JOIN groups_ g ON g.id=r.group_id
                           WHERE r.group_id=?""", (tid,))
        self.strip_lbl.setText("بطاقات المواد — اسحب بطاقة إلى الخانة المطلوبة لإنشاء حصة (الرقم = الساعات المتبقية هذا الأسبوع)")
        for r in reqs:
            done = sum((s["end_min"] - s["start_min"]) / 60 for s in sessions
                       if s["subject_id"] == r["subject_id"] and str(r["group_id"]) in (s["gids"] or "").split(",")
                       and s["status"] in ("planned", "done"))
            left = max(0.0, (r["weekly_hours"] or 0) - done)
            it = QListWidgetItem(f"{r['sshort'] or r['sname'][:8]}\n{r['gname']}\n{left:g} سا")
            it.setToolTip(f"{r['sname']} — {r['gname']}\nأسبوعياً: {r['weekly_hours']:g} سا، المتبقي: {left:g} سا")
            it.setData(Qt.UserRole, {"id": r["id"], "len": r["session_minutes"]})
            it.setBackground(QColor(r["color"] or "#4F7CAC"))
            it.setForeground(QColor(_text_on(r["color"] or "#4F7CAC")))
            it.setTextAlignment(Qt.AlignCenter)
            it.setSizeHint(QSize(100, 66))
            self.cards.addItem(it)

    # -------------------------------------------------------------- اللوحة الجانبية وأدوات الأسبوع
    def _section(self):
        mode, tid = self.mode.currentData(), self.target.currentData()
        if mode == "section":
            return tid
        if mode == "group" and tid:
            return self.ctx.db.scalar("SELECT section_id FROM groups_ WHERE id=?", (tid,))
        return None

    def _fill_side(self):
        from ...services import planner_tools as PT
        from ...services import priorities as PRI
        sec = self._section()
        W = self._QTWI
        self.need_t.setRowCount(0)
        self.day_t.setRowCount(0)
        if not sec:
            return
        rows = PT.needs(self.ctx.db, sec, self.ws)
        self._needs = rows
        self.need_t.setRowCount(len(rows))
        for i, r in enumerate(rows):
            vals = [r["subject"], f"{r['need']:g}", f"{r['placed']:g}", f"{r['left']:g}"]
            for j, v in enumerate(vals):
                it = W(v)
                if j == 0:
                    it.setToolTip(r["reason"])
                if j == 3 and r["left"] >= 1:
                    it.setForeground(QColor(theme.CURRENT["warn"]))
                self.need_t.setItem(i, j, it)
        from PySide6.QtWidgets import QHeaderView
        hh = self.need_t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for j in (1, 2, 3):
            hh.setSectionResizeMode(j, QHeaderView.ResizeToContents)
        dh = float(PRI.load(self.ctx.db)["rules"].get("day_hours") or 7)
        days = PT.day_summary(self.ctx.db, sec, self.ws, dh)
        self.day_t.setRowCount(len(days))
        for i, d in enumerate(days):
            col = {"over": theme.CURRENT["bad"], "nolunch": theme.CURRENT["warn"]}.get(d["state"])
            for j, v in enumerate([DAY_NAMES[(d["day"].weekday() + 1) % 7], f"{d['study']:g} سا",
                                   "✓" if d["lunch"] else ("—" if not d["n"] else "✗")]):
                it = W(v)
                if col:
                    it.setForeground(QColor(col))
                self.day_t.setItem(i, j, it)
        hd = self.day_t.horizontalHeader()
        hd.setSectionResizeMode(QHeaderView.Stretch)

    def _place_need(self, row, _col):
        from ...services import planner_tools as PT
        sec = self._section()
        r = (getattr(self, "_needs", None) or [None] * (row + 1))[row]
        if not sec or not r:
            return
        mins = min(int(r["mins"] or 120), max(60, int(round(max(r["left"], 1) * 60))))
        try:
            sid, msg = PT.place_first(self.ctx.db, sec, self.ws, r["subject_id"], mins, r["teacher"])
        except Exception as e:
            error(self, str(e))
            return
        from .. import sounds
        if sid:
            sounds.play("ok", self.ctx.db)
            self.ctx.changed("sessions")
            self.ctx.status.emit(f"وُضعت «{r['subject']}»: {msg}")
        else:
            sounds.play("conflict", self.ctx.db)
            info(self, f"«{r['subject']}»: {msg}")

    def auto_section(self):
        from PySide6.QtWidgets import QApplication
        from ...scheduler.engine import Scheduler
        from ...services import priorities as PRI
        sec = self._section()
        if not sec:
            info(self, "اختر العرض حسب القسم أو الفوج.")
            return
        db = self.ctx.db
        fid = db.scalar("SELECT formation_id FROM sections WHERE id=?", (sec,))
        groups = [r[0] for r in db.q("SELECT id FROM groups_ WHERE section_id=?", (sec,))]
        if not confirm(self, "برمجة هذا القسم آلياً لهذا الأسبوع؟ تبقى الحصص الموجودة كما هي، ويُكمل المحرك الباقي."):
            return
        cfg = PRI.load(db)
        override, rules = None, None
        if cfg.get("enabled"):
            override, _rows = PRI.week_plan(db, fid, self.ws, groups, cfg)
            rules = cfg.get("rules")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            tt = self.timetable_id(create=True)
            res = Scheduler(db, time_limit=float(db.get_setting("engine_time_limit", "20") or 20)).schedule_week(
                fid, self.ws, groups, hours_override=override, rules=rules, exclude_timetable=-1)
            if res.placements:
                for p in res.placements:
                    T.create_session(db, tt, p.day, p.start_min, p.end_min, p.meeting.subject_id, p.meeting.teacher_id,
                                     p.room_id, p.meeting.group_ids,
                                     p.meeting.requirement_ids[0] if p.meeting.requirement_ids else None,
                                     manual=False, force=True)
        finally:
            QApplication.restoreOverrideCursor()
        self.ctx.changed("sessions")
        msg = res.summary()
        if res.unplaced:
            msg += "\n\n" + "\n".join(f"• {u.meeting.label}: {u.reason}" for u in res.unplaced[:10])
        info(self, msg)

    def save_tpl(self):
        from ...services import planner_tools as PT
        sec = self._section()
        if not sec:
            info(self, "اختر العرض حسب القسم.")
            return
        n = PT.save_template(self.ctx.db, sec, self.ws)
        info(self, f"حُفظ الأسبوع النموذجي لهذا القسم ({n} حصة).")

    def apply_tpl(self):
        from ...services import planner_tools as PT
        sec = self._section()
        if not sec:
            info(self, "اختر العرض حسب القسم.")
            return
        tpl = PT.template_info(self.ctx.db, sec)
        if not tpl:
            info(self, "لا يوجد أسبوع نموذجي محفوظ لهذا القسم. احفظه أولاً من أسبوع مكتمل.")
            return
        if not confirm(self, f"تطبيق الأسبوع النموذجي (من أسبوع {tpl['from']}، {len(tpl['items'])} حصة) على هذا الأسبوع؟"):
            return
        n, skipped = PT.apply_template(self.ctx.db, sec, self.ws)
        self.ctx.changed("sessions")
        msg = f"وُضعت {n} حصة."
        if skipped:
            msg += f"\nتُجاوزت {len(skipped)}:\n" + "\n".join(skipped[:12])
        info(self, msg)

    def copy_day(self):
        from ...services import planner_tools as PT
        sec = self._section()
        if not sec:
            info(self, "اختر العرض حسب القسم.")
            return
        src = self._pick_dt("اليوم المنسوخ منه", self.ws, 480)
        if not src:
            return
        dst = self._pick_dt("اليوم المنسوخ إليه", src[0] + timedelta(days=1), 480)
        if not dst:
            return
        n, skipped = PT.copy_day(self.ctx.db, sec, src[0], dst[0])
        self.ctx.changed("sessions")
        info(self, f"نُسخت {n} حصة." + (f"\nتُجاوزت {len(skipped)}:\n" + "\n".join(skipped[:12]) if skipped else ""))

    def check_week(self):
        from ...services import planner_tools as PT
        from ...services import priorities as PRI
        sec = self._section()
        db = self.ctx.db
        secs = [sec] if sec else [r[0] for r in db.q("SELECT id FROM sections WHERE formation_id IN (%s)" %
                                                    ",".join("?" * len(self.ctx.formation_ids() or [0])),
                                                    self.ctx.formation_ids() or [0])]
        dh = float(PRI.load(db)["rules"].get("day_hours") or 7)
        out = PT.check_week(db, secs, self.ws, dh)
        if not out:
            info(self, "لا توجد ملاحظات: الأسبوع جاهز للطباعة.", "فحص الأسبوع")
            return
        info(self, "\n".join(f"[{sev}] {msg}" for sev, msg in out[:40]) + ("\n…" if len(out) > 40 else ""),
             f"فحص الأسبوع — {len(out)} ملاحظة")

    def _lock(self, sid, on):
        from ...services import planner_tools as PT
        PT.set_lock(self.ctx.db, [sid], on)
        self.ctx.changed("sessions")

    def _swap(self, s):
        from ...services import planner_tools as PT
        others = [x for x in self._load_sessions() if x["id"] != s["id"]]
        if not others:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("تبديل الحصة مع…")
        f = QFormLayout(dlg)
        cb = QComboBox()
        for x in sorted(others, key=lambda x: (x["date"], x["start_min"])):
            d = to_date(x["date"])
            cb.addItem(f"{DAY_NAMES[(d.weekday() + 1) % 7]} {hm_range(x['start_min'], x['end_min'])} — {x['sname']}", x["id"])
        f.addRow("الحصة الأخرى", cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            PT.swap(self.ctx.db, s["id"], cb.currentData())
            self.ctx.changed("sessions")

    # -------------------------------------------------------------- عمليات
    def _session(self, sid) -> dict | None:
        r = self.ctx.db.one("""SELECT s.*, sub.name sname FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                               WHERE s.id=?""", (sid,))
        return dict(r) if r else None

    def _apply(self, fn, *args, **kw):
        try:
            fn(*args, **kw)
            self.ctx.changed("sessions")
            return True
        except T.ConflictError as e:
            if confirm(self, "توجد تعارضات:\n• " + "\n• ".join(e.conflicts) + "\n\nهل تريد المتابعة رغم ذلك؟", danger=True):
                kw["force"] = True
                fn(*args, **kw)
                self.ctx.changed("sessions")
                return True
        except ValueError as e:
            error(self, str(e))
        return False

    def _moved(self, sid, d, m):
        s = self._session(sid)
        length = s["end_min"] - s["start_min"]
        self._apply(T.update_session, self.ctx.db, sid, date=iso(d), start_min=m, end_min=m + length)

    def _dropped(self, rid, d, m):
        db = self.ctx.db
        r = db.one("SELECT * FROM requirements WHERE id=?", (rid,))
        if not r:
            return
        mins = r["session_minutes"]
        if mins == FULL_DAY:
            m, end = db.get_int("day_start"), db.get_int("day_end")
        else:
            end = m + mins
        tt = self.timetable_id(create=True)
        teacher = r["teacher_id"] or db.scalar("SELECT teacher_id FROM teacher_subjects WHERE subject_id=? LIMIT 1",
                                               (r["subject_id"],))
        groups = [r["group_id"]]
        sub = db.one("SELECT shareable FROM subjects WHERE id=?", (r["subject_id"],))
        if r["share_code"] and sub["shareable"]:
            groups = [x[0] for x in db.q("""SELECT group_id FROM requirements WHERE formation_id=? AND share_code=?
                                            AND subject_id=?""", (r["formation_id"], r["share_code"], r["subject_id"]))]
        self._apply(T.create_session, db, tt, d, m, end, r["subject_id"], teacher, r["room_id"], groups, rid)

    def edit_session(self, sid):
        s = self._session(sid)
        if s and SessionDialog(self, self.ctx.db, s).exec() == QDialog.Accepted:
            self.ctx.changed("sessions")

    def _menu(self, sid, gpos):
        s = self._session(sid)
        if not s:
            return
        m = QMenu(self)
        m.addAction(icon("mdi6.pencil"), "تعديل (الأستاذ، القاعة، التوقيت، المدة)…", lambda: self.edit_session(sid))
        m.addAction(icon("mdi6.content-copy"), "نسخ إلى…", lambda: self._copy_to(s))
        m.addAction(icon("mdi6.swap-horizontal"), "تبديل مع حصة أخرى…", lambda: self._swap(s))
        if s.get("manual"):
            m.addAction(icon("mdi6.lock-open-variant-outline"), "فتح القفل (تحركها البرمجة الآلية)",
                        lambda: self._lock(sid, False))
        else:
            m.addAction(icon("mdi6.lock-outline"), "قفل (لا تحركها البرمجة الآلية)", lambda: self._lock(sid, True))
        m.addSeparator()
        m.addAction(icon("mdi6.check-circle-outline"), "تسجيل كمنجزة",
                    lambda: self._apply(T.set_status, self.ctx.db, sid, "done"))
        m.addAction(icon("mdi6.clock-outline"), "تأجيل", lambda: self._apply(T.set_status, self.ctx.db, sid, "postponed"))
        m.addAction(icon("mdi6.cancel"), "إلغاء الحصة", lambda: self._apply(T.set_status, self.ctx.db, sid, "cancelled"))
        m.addAction(icon("mdi6.backup-restore"), "إعادة إلى «مبرمجة»",
                    lambda: self._apply(T.set_status, self.ctx.db, sid, "planned"))
        mk = m.addAction(icon("mdi6.calendar-plus"), "إنشاء حصة تعويضية…", lambda: self._makeup(s))
        mk.setEnabled(s["status"] in ("postponed", "cancelled"))
        m.addAction(icon("mdi6.account-switch"), "استخلاف…", lambda: self._substitute(s))
        m.addSeparator()
        m.addAction(icon("mdi6.history"), "سجل التغييرات", lambda: self._history(sid))
        m.addAction(icon("mdi6.delete-outline"), "حذف", lambda: self._delete(sid))
        m.exec(gpos)

    def _empty_menu(self, d, minute, gpos):
        m = QMenu(self)
        m.addAction(icon("mdi6.plus"), f"إضافة حصة يوم {d.strftime('%d/%m')} {hm(minute)}…", lambda: self._quick_add(d, minute))
        m.exec(gpos)

    def _pick_dt(self, title, d: date, minute: int):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        f = QFormLayout(dlg)
        de = QDateEdit(QDate(d.year, d.month, d.day))
        de.setCalendarPopup(True)
        de.setDisplayFormat("dd/MM/yyyy")
        te = QTimeEdit(QTime(minute // 60, minute % 60))
        te.setDisplayFormat("HH:mm")
        f.addRow("التاريخ", de)
        f.addRow("البداية", te)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            return de.date().toPython(), te.time().hour() * 60 + te.time().minute()
        return None

    def _copy_to(self, s):
        r = self._pick_dt("نسخ الحصة إلى", to_date(s["date"]) + timedelta(days=7), s["start_min"])
        if r:
            d, m = r
            tt = T.get_or_create_timetable(self.ctx.db, s.get("fid") or self._fid(), d)
            self._apply(T.create_session, self.ctx.db, tt, d, m, m + s["end_min"] - s["start_min"], s["subject_id"],
                        s["teacher_id"], s["room_id"], T.session_groups(self.ctx.db, s["id"]), s["requirement_id"])

    def _makeup(self, s):
        r = self._pick_dt("حصة تعويضية", to_date(s["date"]) + timedelta(days=1), s["start_min"])
        if r:
            self._apply(T.create_makeup, self.ctx.db, s["id"], r[0], r[1])

    def _substitute(self, s):
        db = self.ctx.db
        cands = A.suggest_substitutes(db, s["id"], 30)
        dlg = QDialog(self)
        dlg.setWindowTitle("اختيار مستخلف")
        dlg.resize(420, 420)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("أساتذة مؤهلون ومتفرغون في توقيت الحصة (الأقل عبئاً أولاً):"))
        lst = QListWidget()
        for c in cands:
            it = QListWidgetItem(f"{c['name']}  —  {c['rank'] or ''}  —  عبء الأسبوع: {c['week_load']:g} سا")
            it.setData(Qt.UserRole, c["id"])
            lst.addItem(it)
        if not cands:
            lst.addItem("لا يوجد أستاذ مؤهل ومتفرغ.")
        v.addWidget(lst)
        other = QComboBox()
        other.addItem("— اختيار يدوي من كل الأساتذة —", None)
        for r in db.q("SELECT id, full_name FROM teachers WHERE active=1 ORDER BY full_name"):
            other.addItem(r["full_name"], r["id"])
        v.addWidget(other)
        bb = QDialogButtonBox()
        ok = bb.addButton("تعيين", QDialogButtonBox.AcceptRole)
        rm = bb.addButton("إلغاء الاستخلاف", QDialogButtonBox.DestructiveRole)
        bb.addButton("إغلاق", QDialogButtonBox.RejectRole)
        result = {}
        ok.clicked.connect(lambda: (result.update(act="set"), dlg.accept()))
        rm.clicked.connect(lambda: (result.update(act="clear"), dlg.accept()))
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        if result.get("act") == "clear":
            self._apply(A.assign_substitute, db, s["id"], None)
            return
        tid = other.currentData() or (lst.currentItem().data(Qt.UserRole) if lst.currentItem() else None)
        if tid:
            self._apply(A.assign_substitute, db, s["id"], tid)

    def _history(self, sid):
        rows = self.ctx.db.q("SELECT ts, username, action, details FROM audit_log WHERE entity='sessions' AND entity_id=? "
                             "ORDER BY id DESC", (sid,))
        info(self, "\n".join(f"{r['ts']} — {r['username'] or ''} — {r['action']}" + (f"\n    {r['details']}" if r['details'] else "")
                             for r in rows) or "لا يوجد سجل.", "سجل تغييرات الحصة")

    def _delete(self, sid):
        if confirm(self, "حذف هذه الحصة؟", danger=True):
            self._apply(T.delete_session, self.ctx.db, sid)

    def _quick_add(self, d, minute):
        mode, tid = self.mode.currentData(), self.target.currentData()
        if mode not in ("section", "group"):
            info(self, "اختر العرض حسب القسم أو الفوج، ثم اسحب بطاقة مادة أو استعمل هذه القائمة.")
            return
        db = self.ctx.db
        reqs = db.q("""SELECT r.id, s.name||' — '||g.name lab FROM requirements r JOIN subjects s ON s.id=r.subject_id
                       JOIN groups_ g ON g.id=r.group_id WHERE (g.section_id=? AND ?='section') OR (g.id=? AND ?='group')""",
                    (tid, mode, tid, mode))
        if not reqs:
            info(self, "لا توجد متطلبات لهذا القسم/الفوج. أضفها من صفحة المتطلبات.")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("إضافة حصة")
        f = QFormLayout(dlg)
        cb = QComboBox()
        for r in reqs:
            cb.addItem(r["lab"], r["id"])
        f.addRow("المادة / الفوج", cb)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() == QDialog.Accepted:
            self._dropped(cb.currentData(), d, minute)

    # -------------------------------------------------------------- أوامر على مستوى الأسبوع
    def approve(self):
        tt = self.timetable_id()
        if not tt:
            info(self, "لا يوجد جدول لهذا الأسبوع.")
            return
        if confirm(self, "اعتماد جدول هذا الأسبوع؟ لن يُعدّل تلقائياً بعد الاعتماد."):
            T.approve(self.ctx.db, tt)
            self.ctx.changed("timetables")
            self.ctx.status.emit("تم اعتماد الجدول.")

    def reopen(self):
        tt = self.timetable_id()
        if tt and confirm(self, "إعادة فتح الجدول المعتمد كمسودة للتعديل؟"):
            T.reopen(self.ctx.db, tt)
            self.ctx.changed("timetables")

    def copy_week(self):
        r = self._pick_dt("نسخ هذا الأسبوع إلى الأسبوع الذي يحتوي التاريخ", self.ws + timedelta(days=7), 480)
        if not r:
            return
        try:
            n, skipped = 0, []
            for f in ([self._fid()] if self.mode.currentData() in ("section", "group") else self.ctx.formation_ids()):
                a, b = T.copy_week(self.ctx.db, f, self.ws, r[0])
                n += a
                skipped += b
        except T.ConflictError as e:
            error(self, "\n".join(e.conflicts))
            return
        self.ctx.changed("sessions")
        msg = f"نُسخت {n} حصة."
        if skipped:
            msg += f"\nتُجاوزت {len(skipped)}:\n" + "\n".join(skipped[:15])
        info(self, msg)

    def versions(self):
        tt = self.timetable_id()
        if not tt:
            info(self, "لا يوجد جدول لهذا الأسبوع.")
            return
        db = self.ctx.db
        snaps = db.q("SELECT id, created_at, label FROM timetable_snapshots WHERE timetable_id=? ORDER BY id DESC", (tt,))
        dlg = QDialog(self)
        dlg.setWindowTitle("النسخ السابقة للجدول")
        dlg.resize(420, 360)
        v = QVBoxLayout(dlg)
        lst = QListWidget()
        for s in snaps:
            it = QListWidgetItem(f"{s['created_at']} — {s['label']}")
            it.setData(Qt.UserRole, s["id"])
            lst.addItem(it)
        v.addWidget(lst)
        row = QHBoxLayout()
        save_b = QPushButton("حفظ نسخة الآن")
        rest_b = QPushButton("الرجوع إلى النسخة المحددة")
        row.addWidget(save_b)
        row.addWidget(rest_b)
        v.addLayout(row)

        def do_save():
            T.snapshot(db, tt, "يدوية")
            dlg.accept()
            info(self, "تم حفظ نسخة.")

        def do_restore():
            it = lst.currentItem()
            if it and confirm(self, "الرجوع إلى هذه النسخة؟ ستُحفظ الحالة الحالية كنسخة أولاً."):
                try:
                    T.restore_snapshot(db, it.data(Qt.UserRole))
                    self.ctx.changed("sessions")
                    dlg.accept()
                except T.ConflictError as e:
                    error(self, "\n".join(e.conflicts))
        save_b.clicked.connect(do_save)
        rest_b.clicked.connect(do_restore)
        dlg.exec()

    def compare(self):
        r = self._pick_dt("مقارنة هذا الأسبوع مع الأسبوع الذي يحتوي التاريخ", self.ws - timedelta(days=7), 480)
        if not r:
            return
        cmp = {}
        for f in self.ctx.formation_ids():
            for k, (a, b) in T.compare_weeks(self.ctx.db, f, self.ws, r[0]).items():
                x = cmp.get(k, (0, 0))
                cmp[k] = (x[0] + a, x[1] + b)
        lines = [f"{k}: {a:g} سا ← → {b:g} سا" + ("" if a == b else "  ⟵ فرق") for k, (a, b) in cmp.items()]
        info(self, "\n".join(lines) or "لا توجد حصص.", "مقارنة أسبوعين (هذا ← → الآخر)")
