"""شبكة الأسبوع لقسم واحد: الأيام أعمدة والوقت صفوف، مع الوضع والنقل والتمديد.

الرسم والتفاعل فقط؛ كل المنطق (الوضع، النقل، التعارضات، التراجع) في
`dpp.services.grid.WeekGrid` المشتركة مع النسخة الكاملة.
"""
from __future__ import annotations

from datetime import date, timedelta

from dpp.services.grid import Card, GridError, TrayItem
from dpp.utils import hm, ltr, parse_rest_days

from . import theme
from .qt import QColor, QPainter, QPen, QPoint, QRectF, Qt, QtWidgets, Signal, ev_pos, popup, run

DAY_NAMES = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]
HEAD_H = 40
TIME_W = 62
MIN_CARD = 18


class WeekGridView(QtWidgets.QWidget):
    """عرض أسبوع قسم واحد وتحريره."""

    changed = Signal()
    status = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.grid = None                 # WeekGrid
        self.section_id = None
        self.armed: TrayItem | None = None     # المادة المختارة من الشريط السفلي
        self.read_only = False
        self.setMouseTracking(True)
        self.setMinimumHeight(420)
        self._drag = None                # حالة السحب الجارية
        self._hover = None
        self.day_start, self.day_end, self.slot = 480, 1000, 30
        self.lunch = (720, 780)
        self.days: list[date] = []

    # ------------------------------------------------------------------ بيانات
    def set_grid(self, grid, section_id: int | None):
        self.grid = grid
        self.section_id = section_id
        self.reload_axes()
        self.update()

    def reload_axes(self):
        if not self.grid:
            return
        db = self.grid.db
        self.day_start = db.get_int("day_start") or 480
        self.day_end = max(self.day_start + 60, db.get_int("day_end") or 1000)
        self.slot = db.get_int("slot_minutes") or 30
        self.lunch = (db.get_int("lunch_start") or 720, db.get_int("lunch_end") or 780)
        rest: set[int] = set()
        sec = self.grid.sec_by_id.get(self.section_id) if self.section_id else None
        if sec:
            row = self.grid.db.q("SELECT rest_days FROM formations WHERE id=?", (sec.formation_id,))
            if row:
                rest = parse_rest_days(row[0][0])
        self.days = [d for i, d in enumerate(self.grid.days()) if i not in rest]

    def cards(self) -> list[Card]:
        if not self.grid or not self.section_id:
            return []
        return [c for c in self.grid.by_section.get(self.section_id, []) if c.status != "tray"]

    # ------------------------------------------------------------------ هندسة
    def _col_w(self) -> float:
        n = max(1, len(self.days))
        return max(60.0, (self.width() - TIME_W - 2) / n)

    def _px_per_min(self) -> float:
        return max(0.25, (self.height() - HEAD_H - 4) / max(1, self.day_end - self.day_start))

    def _day_rect(self, i: int) -> QRectF:
        w = self._col_w()
        # RTL: الأحد في أقصى اليمين
        x = self.width() - TIME_W - (i + 1) * w
        return QRectF(x, HEAD_H, w, self.height() - HEAD_H)

    def _y(self, minute: int) -> float:
        return HEAD_H + (minute - self.day_start) * self._px_per_min()

    def _minute(self, y: float) -> int:
        m = self.day_start + (y - HEAD_H) / self._px_per_min()
        return int(max(self.day_start, min(self.day_end, round(m / self.slot) * self.slot)))

    def _day_at(self, x: float) -> int | None:
        for i in range(len(self.days)):
            r = self._day_rect(i)
            if r.left() <= x < r.right():
                return i
        return None

    def _card_rect(self, c: Card) -> QRectF | None:
        if c.day not in self.days:
            return None
        i = self.days.index(c.day)
        r = self._day_rect(i)
        y1, y2 = self._y(c.start), self._y(c.end)
        return QRectF(r.left() + 3, y1 + 1, r.width() - 6, max(MIN_CARD, y2 - y1 - 2))

    def card_at(self, p: QPoint) -> Card | None:
        for c in self.cards():
            r = self._card_rect(c)
            if r and r.contains(p.x(), p.y()):
                return c
        return None

    # ------------------------------------------------------------------ الرسم
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_grid(p, self.rect())
        p.end()

    def paint_grid(self, p: QPainter, rect, for_print: bool = False):
        t = theme.T
        p.fillRect(rect, QColor("#FFFFFF" if for_print else t["surface"]))
        if not self.grid or not self.section_id or not self.days:
            p.setPen(QColor(t["muted"]))
            p.drawText(rect, Qt.AlignCenter, "اختر تكويناً وقسماً لعرض الجدول.")
            return
        f = p.font()
        ppm = self._px_per_min()

        # استراحة الغداء
        ls, le = self.lunch
        grid_w = self.width() - TIME_W
        if le > ls:
            p.fillRect(QRectF(0, self._y(ls), grid_w, (le - ls) * ppm), QColor(t["lunch"]))

        # خطوط الوقت وعموده
        p.setPen(QPen(QColor(t["grid"]), 1))
        f.setPointSizeF(8.5)
        p.setFont(f)
        m = self.day_start
        while m <= self.day_end:
            y = self._y(m)
            full = m % 60 == 0
            p.setPen(QPen(QColor(t["border"] if full else t["grid"]), 1))
            p.drawLine(0, int(y), int(grid_w), int(y))
            if full:
                p.setPen(QColor(t["muted"]))
                p.drawText(QRectF(grid_w + 5, y - 9, TIME_W - 10, 18),
                           Qt.AlignLeft | Qt.AlignVCenter | Qt.AlignAbsolute, ltr(hm(m)))
            m += self.slot

        # رؤوس الأيام
        p.fillRect(QRectF(0, 0, self.width(), HEAD_H), QColor(t["header"]))
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawLine(0, HEAD_H, self.width(), HEAD_H)
        f.setPointSizeF(9.5)
        f.setBold(True)
        p.setFont(f)
        today = date.today()
        for i, d in enumerate(self.days):
            r = self._day_rect(i)
            p.setPen(QPen(QColor(t["border"]), 1))
            p.drawLine(int(r.left()), 0, int(r.left()), int(self.height()))
            is_today = d == today
            if is_today and not for_print:
                p.fillRect(QRectF(r.left(), 0, r.width(), HEAD_H), QColor(t["sel"]))
            p.setPen(QColor(t["text"]))
            wd = (d.weekday() + 1) % 7
            p.drawText(QRectF(r.left(), 0, r.width(), HEAD_H),
                       Qt.AlignCenter, f"{DAY_NAMES[wd]}  {d.strftime('%d/%m')}")
        f.setBold(False)

        # البطاقات
        conf = getattr(self.grid, "conflict_by_sid", {})
        for c in self.cards():
            r = self._card_rect(c)
            if r is None:
                continue
            col = theme.subject_color(c.color, c.category)
            p.fillRect(r, col)
            bad = c.sid in conf
            p.setPen(QPen(QColor(theme.T["bad"]) if bad else QColor(0, 0, 0, 40), 2 if bad else 1))
            p.drawRect(r)
            fg = theme.text_on(col)
            p.setPen(fg)
            f.setPointSizeF(9.0)
            f.setBold(True)
            p.setFont(f)
            inner = r.adjusted(6, 3, -6, -3)
            p.drawText(inner, Qt.AlignTop | Qt.AlignRight | Qt.AlignAbsolute | Qt.TextWordWrap, c.sname)
            f.setBold(False)
            f.setPointSizeF(8.0)
            p.setFont(f)
            tn = self.grid.tshort.get(c.teacher, c.tname) if c.teacher else "بلا أستاذ"
            sub = f"{ltr(hm(c.start) + '–' + hm(c.end))}  ·  {tn}"
            p.drawText(inner, Qt.AlignBottom | Qt.AlignRight | Qt.AlignAbsolute, sub)

        # معاينة السحب
        if self._drag and self._drag.get("preview"):
            i, a, b = self._drag["preview"]
            r = self._day_rect(i)
            pr = QRectF(r.left() + 3, self._y(min(a, b)), r.width() - 6, abs(self._y(b) - self._y(a)))
            p.setPen(QPen(QColor(theme.T["accent"]), 2, Qt.DashLine))
            p.setBrush(QColor(21, 128, 61, 40))
            p.drawRect(pr)
            p.setBrush(Qt.NoBrush)
            p.setPen(QColor(theme.T["text"]))
            p.drawText(pr, Qt.AlignCenter, ltr(f"{hm(min(a, b))} – {hm(max(a, b))}"))

    # ------------------------------------------------------------------ تفاعل
    def mousePressEvent(self, ev):
        if not self.grid or not self.section_id or self.read_only:
            return
        pos = ev_pos(ev)
        card = self.card_at(pos)
        if ev.button() == Qt.RightButton:
            if card:
                self._menu(card, ev)
            return
        if ev.button() != Qt.LeftButton:
            return
        if card:
            self._drag = {"mode": "move", "card": card, "grab": self._minute(pos.y()) - card.start,
                          "preview": None}
            return
        if not self.armed:
            self.status.emit("اختر مادة من الشريط السفلي أولاً، ثم اسحب في اليوم لتحديد الوقت.")
            return
        i = self._day_at(pos.x())
        if i is None:
            return
        m = self._minute(pos.y())
        self._drag = {"mode": "new", "day": i, "from": m, "preview": (i, m, m + self.slot)}
        self.update()

    def mouseMoveEvent(self, ev):
        pos = ev_pos(ev)
        if not self._drag:
            c = self.card_at(pos) if self.grid and self.section_id else None
            if c is not self._hover:
                self._hover = c
                self.setToolTip(self._tip(c) if c else "")
            return
        if self._drag["mode"] == "new":
            i = self._day_at(pos.x())
            if i is None:
                return
            m = self._minute(pos.y())
            a = self._drag["from"]
            if m == a:
                m = a + self.slot
            self._drag["preview"] = (i, a, m)
        else:
            card = self._drag["card"]
            i = self._day_at(pos.x())
            if i is None:
                return
            start = self._minute(pos.y()) - self._drag["grab"]
            start = max(self.day_start, min(self.day_end - card.minutes, start))
            start = int(round(start / self.slot) * self.slot)
            self._drag["preview"] = (i, start, start + card.minutes)
        self.update()

    def mouseReleaseEvent(self, ev):
        d, self._drag = self._drag, None
        if not d or not d.get("preview"):
            self.update()
            return
        i, a, b = d["preview"]
        start, end = min(a, b), max(a, b)
        if end - start < self.slot:
            end = start + self.slot
        day = self.days[i]
        try:
            if d["mode"] == "new":
                self._place(day, start, end)
            else:
                card = d["card"]
                if (card.day, card.start) != (day, start):
                    msgs = self.grid.check_card(card, day, start, end)
                    if msgs and not self._confirm(msgs):
                        self.update()
                        return
                    self.grid.move(card, day, start, end)
                    self.changed.emit()
        except GridError as e:
            QtWidgets.QMessageBox.warning(self, "تعذّر", str(e))
        self.update()

    def _place(self, day: date, start: int, end: int):
        item = self.armed
        msgs = self.grid.check_free(item, self.section_id, day, start, end)
        if msgs and not self._confirm(msgs):
            return
        teacher = self.grid.usual_teacher(self.section_id, item.subject)
        self.grid.place_free(item, self.section_id, teacher, day, start, end)
        self.changed.emit()
        self.status.emit(f"أُضيفت {item.sname} — {DAY_NAMES[(day.weekday() + 1) % 7]} {hm(start)}")

    def _confirm(self, msgs: list) -> bool:
        txt = "\n".join(f"• {m}" for m in msgs[:8])
        box = QtWidgets.QMessageBox(QtWidgets.QMessageBox.Warning, "تعارض", txt + "\n\nهل تضعها رغم ذلك؟", parent=self)
        yes = box.addButton("ضعها رغم التعارض", QtWidgets.QMessageBox.YesRole)
        box.addButton("إلغاء", QtWidgets.QMessageBox.NoRole)
        run(box)
        return box.clickedButton() is yes

    def _tip(self, c: Card) -> str:
        conf = getattr(self.grid, "conflict_by_sid", {}).get(c.sid, [])
        tip = f"{c.sname}\n{hm(c.start)} – {hm(c.end)}\n{c.tname or 'بلا أستاذ'}"
        for x in conf[:3]:
            tip += f"\n⚠ {getattr(x, 'text', '')}"
        return tip

    # ------------------------------------------------------------------ قائمة الزر الأيمن
    def _menu(self, card: Card, ev):
        m = QtWidgets.QMenu(self)
        m.addAction("تغيير الأستاذ…", lambda: self._pick_teacher(card))
        dur = m.addMenu("المدة")
        for mins in (30, 60, 90, 120, 150, 180, 210, 240):
            lab = hm(mins).replace(":", " سا ") + " د" if mins % 60 else f"{mins // 60} سا"
            act = dur.addAction(lab, lambda mm=mins: self._resize(card, mm))
            act.setCheckable(True)
            act.setChecked(card.minutes == mins)
        m.addSeparator()
        m.addAction("حذف الحصة", lambda: self._delete(card))
        popup(m, ev)

    def _resize(self, card: Card, minutes: int):
        end = min(self.day_end, card.start + minutes)
        msgs = self.grid.check_card(card, card.day, card.start, end)
        if msgs and not self._confirm(msgs):
            return
        try:
            self.grid.resize(card, card.start, end)
        except GridError as e:
            QtWidgets.QMessageBox.warning(self, "تعذّر", str(e))
            return
        self.changed.emit()

    def _delete(self, card: Card):
        if QtWidgets.QMessageBox.question(self, "حذف", f"حذف حصة {c_name(card)}؟") != QtWidgets.QMessageBox.Yes:
            return
        try:
            self.grid.delete(card.sid)
        except GridError as e:
            QtWidgets.QMessageBox.warning(self, "تعذّر", str(e))
            return
        self.changed.emit()

    def _pick_teacher(self, card: Card):
        cands = self.grid.teacher_candidates(self.section_id, card.subject, card.day, card.start, card.end)
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"أستاذ — {card.sname}")
        v = QtWidgets.QVBoxLayout(dlg)
        lst = QtWidgets.QListWidget()
        lst.addItem("— بلا أستاذ —")
        for c in cands:
            name = c.get("name") or c.get("full_name") or ""
            busy = " (مشغول)" if c.get("busy") else ""
            it = QtWidgets.QListWidgetItem(f"{name}{busy}")
            it.setData(Qt.UserRole, c.get("id"))
            lst.addItem(it)
        v.addWidget(lst)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        if run(dlg) != QtWidgets.QDialog.Accepted or lst.currentRow() < 0:
            return
        tid = lst.currentItem().data(Qt.UserRole)
        try:
            self.grid.set_teacher(card, tid)
        except GridError as e:
            QtWidgets.QMessageBox.warning(self, "تعذّر", str(e))
            return
        self.changed.emit()


def c_name(card: Card) -> str:
    return f"{card.sname} — {DAY_NAMES[(card.day.weekday() + 1) % 7]} {hm(card.start)}"
