"""شبكة المخطط الأسبوعي: رسم مخصص، اتجاه RTL، سحب وإفلات.

ثلاثة أوضاع:
- main: كل الفروع صفوف، الأيام × الأوقات أعمدة (على طريقة aSc).
- days_rows: فرع واحد، الأيام صفوف والأوقات أعمدة (مثل الورقة المطبوعة).
- time_grid: فرع واحد، الشبكة الزمنية (الأيام أعمدة والأوقات صفوف).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QPixmap,
                           QTextOption)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from dpp.models import DAY_NAMES
from dpp.services.timeutil import SLOT, fmt, fmt_duration
from dpp.ui.theme import T, text_on

MIME_CARD = "application/x-dpp-card"
MIME_LESSON = "application/x-dpp-lesson"

MAIN, DAYS_ROWS, TIME_GRID = "main", "days_rows", "time_grid"


@dataclass
class LaneVM:
    section_id: int | None
    day: int | None
    label: str
    sublabel: str = ""


@dataclass
class CardVM:
    id: int
    section_id: int
    day: int
    start: int
    duration: int
    title: str
    teacher: str
    color: QColor
    kind_label: str = ""
    conflict: bool = False
    full_day: bool = False
    tooltip: str = ""

    @property
    def end(self) -> int:
        return self.start + self.duration


@dataclass
class BlockVM:
    section_id: int | None  # None = كل الفروع
    day: int
    start: int
    end: int
    kind: str  # lunch / event
    title: str = ""


@dataclass
class Ghost:
    section_id: int
    day: int
    start: int
    duration: int


@dataclass
class GridModel:
    mode: str = MAIN
    days: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    t0: int = 8 * 60
    t1: int = 16 * 60 + 30
    lanes: list[LaneVM] = field(default_factory=list)
    cards: list[CardVM] = field(default_factory=list)
    blocks: list[BlockVM] = field(default_factory=list)
    section_id: int | None = None  # للوضعين الخاصين بفرع واحد

    @property
    def nslots(self) -> int:
        return max(1, math.ceil((self.t1 - self.t0) / SLOT))


class PlannerGrid(QWidget):
    cardDropped = Signal(dict, int, int, int)        # payload, section_id, day, minute
    lessonMoved = Signal(int, int, int, int)         # lesson_id, section_id, day, minute
    contextRequested = Signal(int, int, int, int, QPoint)  # lesson_id(0), section_id, day, minute, global
    lessonActivated = Signal(int)
    deleteRequested = Signal(int)
    selectionChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.m = GridModel()
        self.zoom = 1.0
        self.rtl = True
        self.selected_id = 0
        self.ghost: Ghost | None = None
        self.default_duration = 60
        self.avail_w = 0  # عرض المساحة المتاحة لملء العرض في وضعي الفرع الواحد
        self._press: tuple[QPoint, int, int] | None = None  # pos, lesson_id, grab offset minutes
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    # ------------------------------------------------------------- الهندسة
    @property
    def horizontal(self) -> bool:
        return self.m.mode != TIME_GRID

    def metrics(self):
        z = self.zoom
        if self.m.mode == MAIN:
            return dict(LHW=140, TH=46, LH=int(54 * min(1.4, max(0.8, z))), UW=30 * z)
        if self.m.mode == DAYS_ROWS:
            uw = max(48 * z, (self.avail_w - 100) / max(1, self.m.nslots) * z)
            return dict(LHW=100, TH=26, LH=int(78 * min(1.4, max(0.8, z))), UW=uw)
        lw = max(190 * min(1.5, max(0.8, z)), (self.avail_w - 62) / max(1, len(self.m.lanes)) * z)
        return dict(LHW=62, TH=30, LW=int(lw), UH=30 * z)

    def nunits(self) -> int:
        return self.m.nslots * (len(self.m.days) if self.m.mode == MAIN else 1)

    def sizeHint(self) -> QSize:
        g = self.metrics()
        if self.horizontal:
            return QSize(int(g["LHW"] + self.nunits() * g["UW"]) + 1, g["TH"] + len(self.m.lanes) * g["LH"] + 1)
        return QSize(g["LHW"] + len(self.m.lanes) * g["LW"] + 1, int(g["TH"] + self.nunits() * g["UH"]) + 1)

    def set_model(self, model: GridModel) -> None:
        self.m = model
        self.relayout()

    def relayout(self) -> None:
        self.setFixedSize(self.sizeHint())
        self.update()

    def set_zoom(self, z: float) -> None:
        self.zoom = max(0.5, min(3.0, z))
        self.relayout()

    def lane_index(self, section_id: int, day: int) -> int | None:
        for i, ln in enumerate(self.m.lanes):
            if self.m.mode == MAIN and ln.section_id == section_id:
                return i
            if self.m.mode != MAIN and ln.day == day:
                return i
        return None

    def unit(self, day: int, minute: int) -> float | None:
        if day not in self.m.days:
            return None
        base = self.m.days.index(day) * self.m.nslots if self.m.mode == MAIN else 0
        return base + (minute - self.m.t0) / SLOT

    def _mirror(self, r: QRectF) -> QRectF:
        if not self.rtl:
            return r
        return QRectF(self.width() - r.x() - r.width(), r.y(), r.width(), r.height())

    def rect_for(self, lane: int, u0: float, u1: float) -> QRectF:
        g = self.metrics()
        if self.horizontal:
            r = QRectF(g["LHW"] + u0 * g["UW"], g["TH"] + lane * g["LH"], (u1 - u0) * g["UW"], g["LH"])
        else:
            r = QRectF(g["LHW"] + lane * g["LW"], g["TH"] + u0 * g["UH"], g["LW"], (u1 - u0) * g["UH"])
        return self._mirror(r)

    def span_rect(self, section_id: int, day: int, start: int, end: int) -> QRectF | None:
        lane = self.lane_index(section_id, day)
        if lane is None:
            return None
        s = max(start, self.m.t0)
        e = min(end, self.m.t1)
        if e <= s:
            return None
        u0, u1 = self.unit(day, s), self.unit(day, e)
        if u0 is None:
            return None
        return self.rect_for(lane, u0, u1)

    def hit(self, pos) -> tuple[int, int, int] | None:
        """نقطة → (section_id, day, minute) أو None إن كانت في الرؤوس."""
        g = self.metrics()
        x, y = pos.x(), pos.y()
        if self.rtl:
            x = self.width() - x
        if x < g["LHW"] or y < g["TH"]:
            return None
        if self.horizontal:
            lane = int((y - g["TH"]) // g["LH"])
            u = (x - g["LHW"]) / g["UW"]
        else:
            lane = int((x - g["LHW"]) // g["LW"])
            u = (y - g["TH"]) / g["UH"]
        if not (0 <= lane < len(self.m.lanes)) or not (0 <= u < self.nunits()):
            return None
        ln = self.m.lanes[lane]
        if self.m.mode == MAIN:
            day = self.m.days[int(u // self.m.nslots)]
            minute = self.m.t0 + int(u % self.m.nslots) * SLOT
            return ln.section_id, day, minute
        minute = self.m.t0 + int(u) * SLOT
        return self.m.section_id, ln.day, minute

    def card_at(self, pos) -> CardVM | None:
        for c in reversed(self.m.cards):
            r = self.span_rect(c.section_id, c.day, c.start, c.end)
            if r and r.contains(QPointF(pos)):
                return c
        return None

    def card(self, lesson_id: int) -> CardVM | None:
        return next((c for c in self.m.cards if c.id == lesson_id), None)

    # ------------------------------------------------------------- الرسم
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("white"))
        self._paint_lanes(p)
        self._paint_blocks(p)
        self._paint_gridlines(p)
        self._paint_headers(p)
        for c in self.m.cards:
            self._paint_card(p, c)
        if self.ghost:
            r = self.span_rect(self.ghost.section_id, self.ghost.day, self.ghost.start,
                               self.ghost.start + self.ghost.duration)
            if r:
                p.setPen(QPen(QColor(T["accent"]), 2, Qt.DashLine))
                p.setBrush(QColor(21, 128, 61, 40))
                p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 5, 5)
        p.end()

    def _paint_lanes(self, p: QPainter) -> None:
        for i, _ln in enumerate(self.m.lanes):
            if i % 2:
                r = self.rect_for(i, 0, self.nunits())
                p.fillRect(r, QColor("#FAFBFC"))

    def _paint_blocks(self, p: QPainter) -> None:
        for b in self.m.blocks:
            sections = [b.section_id] if b.section_id is not None else [ln.section_id for ln in self.m.lanes]
            if self.m.mode != MAIN:
                sections = [self.m.section_id] if b.section_id in (None, self.m.section_id) else []
            for sid in sections:
                r = self.span_rect(sid, b.day, b.start, b.end)
                if not r:
                    continue
                if b.kind == "lunch":
                    p.fillRect(r, QColor(T["lunch"]))
                else:
                    p.fillRect(r, QColor(37, 99, 235, 28))
                    p.fillRect(r, QBrush(QColor(37, 99, 235, 60), Qt.BDiagPattern))
                    if b.title and r.width() > 40:
                        p.setPen(QColor("#1E3A8A"))
                        f = QFont(self.font())
                        f.setPointSizeF(7.5)
                        p.setFont(f)
                        p.drawText(r.adjusted(3, 2, -3, -2), Qt.AlignTop | Qt.AlignRight | Qt.TextWordWrap, b.title)

    def _paint_gridlines(self, p: QPainter) -> None:
        g = self.metrics()
        n = self.nunits()
        for u in range(n + 1):
            minute = self.m.t0 + (u % self.m.nslots) * SLOT
            day_edge = self.m.mode == MAIN and u % self.m.nslots == 0
            if day_edge:
                pen = QPen(QColor(T["grid_strong"]), 2)
            elif minute % 60 == 0:
                pen = QPen(QColor("#CBD5E1"), 1)
            else:
                pen = QPen(QColor("#EEF2F6"), 1)
            p.setPen(pen)
            if self.horizontal:
                r = self.rect_for(0, u, u)
                p.drawLine(QPointF(r.x(), g["TH"]), QPointF(r.x(), self.height()))
            else:
                y = g["TH"] + u * g["UH"]
                x0 = self._mirror(QRectF(g["LHW"], 0, 0, 0)).x()
                x1 = self._mirror(QRectF(self.width(), 0, 0, 0)).x()
                p.drawLine(QPointF(x0, y), QPointF(x1, y))
        p.setPen(QPen(QColor(T["border_strong"]), 1))
        for i in range(len(self.m.lanes) + 1):
            if self.horizontal:
                y = g["TH"] + i * g["LH"]
                p.drawLine(QPointF(0, y), QPointF(self.width(), y))
            else:
                r = self.rect_for(i, 0, 0)
                p.drawLine(QPointF(r.x(), 0), QPointF(r.x(), self.height()))

    def _paint_headers(self, p: QPainter) -> None:
        g = self.metrics()
        hdr = QColor("#F8FAFC")
        p.setPen(Qt.NoPen)
        if self.horizontal:
            p.fillRect(self._mirror(QRectF(0, 0, g["LHW"], self.height())), hdr)
            p.fillRect(QRectF(0, 0, self.width(), g["TH"]), hdr)
        else:
            p.fillRect(self._mirror(QRectF(0, 0, g["LHW"], self.height())), hdr)
            p.fillRect(QRectF(0, 0, self.width(), g["TH"]), hdr)
        f = QFont(self.font())
        bold = QFont(f)
        bold.setBold(True)
        small = QFont(f)
        small.setPointSizeF(7.5)
        muted = QColor(T["muted"])
        # رؤوس الممرات
        for i, ln in enumerate(self.m.lanes):
            if self.horizontal:
                r = self._mirror(QRectF(0, g["TH"] + i * g["LH"], g["LHW"], g["LH"]))
            else:
                r = self._mirror(QRectF(g["LHW"] + i * g["LW"], 0, g["LW"], g["TH"]))
            p.setPen(QColor(T["text"]))
            p.setFont(bold)
            inner = r.adjusted(6, 2, -6, -2)
            if ln.sublabel and self.horizontal:
                p.drawText(inner.adjusted(0, 0, 0, -inner.height() / 2), Qt.AlignVCenter | Qt.AlignRight, ln.label)
                p.setFont(small)
                p.setPen(muted)
                p.drawText(inner.adjusted(0, inner.height() / 2, 0, 0), Qt.AlignVCenter | Qt.AlignRight,
                           ln.sublabel)
            else:
                p.drawText(inner, Qt.AlignCenter, ln.label + (f"  ({ln.sublabel})" if ln.sublabel else ""))
        # رؤوس الأوقات/الأيام
        p.setFont(small)
        if self.m.mode == MAIN:
            day_h = 22
            for di, d in enumerate(self.m.days):
                u0 = di * self.m.nslots
                r = self.rect_for(0, u0, u0 + self.m.nslots)
                rr = QRectF(r.x(), 0, r.width(), day_h)
                p.setFont(bold)
                p.setPen(QColor(T["text"]))
                p.drawText(rr, Qt.AlignCenter, DAY_NAMES[d])
                p.setFont(small)
                p.setPen(muted)
                for k in range(self.m.nslots):
                    minute = self.m.t0 + k * SLOT
                    if minute % 60 == 0 and g["UW"] * 2 >= 30 and k + 2 <= self.m.nslots:
                        rk = self.rect_for(0, u0 + k, u0 + k + 2)
                        p.drawText(QRectF(rk.x(), day_h, rk.width(), g["TH"] - day_h), Qt.AlignCenter, fmt(minute))
        elif self.m.mode == DAYS_ROWS:
            for k in range(self.m.nslots):
                minute = self.m.t0 + k * SLOT
                if minute % 60 == 0 and k + 2 <= self.m.nslots:
                    rk = self.rect_for(0, k, k + 2)
                    p.setPen(muted)
                    p.drawText(QRectF(rk.x(), 0, rk.width(), g["TH"]), Qt.AlignCenter, fmt(minute))
        else:
            for k in range(self.m.nslots):
                minute = self.m.t0 + k * SLOT
                r = self._mirror(QRectF(0, g["TH"] + k * g["UH"], g["LHW"], g["UH"]))
                p.setPen(muted if minute % 60 else QColor(T["text"]))
                p.drawText(r.adjusted(4, 0, -4, 0), Qt.AlignVCenter | Qt.AlignHCenter, fmt(minute))

    def _paint_card(self, p: QPainter, c: CardVM) -> None:
        r = self.span_rect(c.section_id, c.day, c.start, c.end)
        if r is None:
            return
        r = r.adjusted(1.5, 2, -1.5, -2)
        path = QPainterPath()
        path.addRoundedRect(r, 5, 5)
        col = QColor(c.color)
        p.fillPath(path, col)
        if c.full_day:
            p.fillPath(path, QBrush(QColor(255, 255, 255, 70), Qt.Dense6Pattern))
        border = QColor(T["danger"]) if c.conflict else col.darker(130)
        width = 2.4 if c.conflict else 1
        if c.id == self.selected_id:
            border, width = QColor("#0F172A"), 2.4
        p.setPen(QPen(border, width))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        if c.conflict:
            dot = QRectF(r.left() + 3, r.bottom() - 10, 7, 7)
            p.setBrush(QColor(T["danger"]))
            p.setPen(Qt.NoPen)
            p.drawEllipse(dot)
        fg = text_on(col)
        inner = r.adjusted(4, 2, -4, -2)
        if inner.width() < 8 or inner.height() < 8:
            return
        f = QFont(self.font())
        f.setPointSizeF(8.0 if self.m.mode == MAIN else 9.0)
        f.setBold(True)
        p.setFont(f)
        p.setPen(fg)
        opt = QTextOption(Qt.AlignRight | Qt.AlignTop)
        opt.setWrapMode(QTextOption.WordWrap)
        opt.setTextDirection(Qt.RightToLeft)
        fm = p.fontMetrics()
        teacher_h = fm.height() if c.teacher else 0
        title_rect = QRectF(inner.x(), inner.y(), inner.width(), max(fm.height(), inner.height() - teacher_h))
        p.save()
        p.setClipRect(title_rect)
        p.drawText(title_rect, c.title, opt)
        p.restore()
        if c.teacher and inner.height() >= fm.height() * 2 - 2:
            f2 = QFont(f)
            f2.setBold(False)
            p.setFont(f2)
            tr = QRectF(inner.x(), inner.bottom() - teacher_h, inner.width(), teacher_h)
            p.drawText(tr, Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(c.teacher, Qt.ElideLeft, int(tr.width())))

    # ------------------------------------------------------------- الفأرة
    def mousePressEvent(self, ev) -> None:
        c = self.card_at(ev.position().toPoint())
        self.selected_id = c.id if c else 0
        self.selectionChanged.emit(self.selected_id)
        self.update()
        if c and ev.button() == Qt.LeftButton:
            h = self.hit(ev.position().toPoint())
            offset = (h[2] - c.start) if h else 0
            self._press = (ev.position().toPoint(), c.id, max(0, offset))
        else:
            self._press = None

    def mouseMoveEvent(self, ev) -> None:
        if self._press and (ev.position().toPoint() - self._press[0]).manhattanLength() > 8:
            _, lid, offset = self._press
            self._press = None
            self._start_drag(lid, offset)
            return
        c = self.card_at(ev.position().toPoint())
        if c and c.tooltip:
            QToolTip.showText(ev.globalPosition().toPoint(), c.tooltip, self)

    def mouseReleaseEvent(self, _ev) -> None:
        self._press = None

    def mouseDoubleClickEvent(self, ev) -> None:
        c = self.card_at(ev.position().toPoint())
        if c:
            self.lessonActivated.emit(c.id)

    def keyPressEvent(self, ev) -> None:
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected_id:
            self.deleteRequested.emit(self.selected_id)
        else:
            super().keyPressEvent(ev)

    def contextMenuEvent(self, ev) -> None:
        c = self.card_at(ev.pos())
        h = self.hit(ev.pos())
        if c:
            self.selected_id = c.id
            self.update()
            self.contextRequested.emit(c.id, c.section_id, c.day, c.start, ev.globalPos())
        elif h:
            self.contextRequested.emit(0, h[0], h[1], h[2], ev.globalPos())

    def _start_drag(self, lesson_id: int, offset: int) -> None:
        c = self.card(lesson_id)
        if not c:
            return
        mime = QMimeData()
        mime.setData(MIME_LESSON, json.dumps({"id": lesson_id, "offset": offset,
                                              "duration": c.duration}).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(card_pixmap(c.title, c.color))
        drag.exec(Qt.MoveAction)
        self.ghost = None
        self.update()

    # ------------------------------------------------------------- الإفلات
    def _payload(self, mime) -> tuple[str, dict] | None:
        if mime.hasFormat(MIME_LESSON):
            return MIME_LESSON, json.loads(bytes(mime.data(MIME_LESSON)).decode())
        if mime.hasFormat(MIME_CARD):
            return MIME_CARD, json.loads(bytes(mime.data(MIME_CARD)).decode())
        return None

    def _target(self, ev) -> tuple[str, dict, tuple[int, int, int]] | None:
        pl = self._payload(ev.mimeData())
        h = self.hit(ev.position().toPoint())
        if not pl or not h or h[0] is None:
            return None
        kind, data = pl
        sec, day, minute = h
        if kind == MIME_LESSON:
            minute = max(self.m.t0, minute - (data.get("offset", 0) // SLOT) * SLOT)
        return kind, data, (sec, day, minute)

    def dragEnterEvent(self, ev) -> None:
        if self._payload(ev.mimeData()):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev) -> None:
        t = self._target(ev)
        if not t:
            self.ghost = None
            self.update()
            ev.ignore()
            return
        kind, data, (sec, day, minute) = t
        dur = data.get("duration") or self.default_duration
        self.ghost = Ghost(sec, day, minute, dur)
        self.update()
        ev.acceptProposedAction()

    def dragLeaveEvent(self, _ev) -> None:
        self.ghost = None
        self.update()

    def dropEvent(self, ev) -> None:
        t = self._target(ev)
        self.ghost = None
        self.update()
        if not t:
            return
        kind, data, (sec, day, minute) = t
        ev.acceptProposedAction()
        if kind == MIME_LESSON:
            self.lessonMoved.emit(int(data["id"]), sec, day, minute)
        else:
            self.cardDropped.emit(data, sec, day, minute)


def card_pixmap(title: str, color: QColor, w: int = 150, h: int = 40) -> QPixmap:
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(color)
    p.setPen(QPen(color.darker(130), 1))
    p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 6, 6)
    p.setPen(text_on(color))
    f = QFont()
    f.setBold(True)
    f.setPointSizeF(8.5)
    p.setFont(f)
    p.drawText(QRectF(6, 2, w - 12, h - 4), Qt.AlignCenter | Qt.TextWordWrap, title)
    p.end()
    return pm


def tooltip_for(title: str, teacher: str, start: int, duration: int, section: str, extra: str = "") -> str:
    lines = [f"<b>{title}</b>", f"الأستاذ: {teacher or '—'}", f"الفرع: {section}",
             f"{fmt(start)} – {fmt(start + duration)} ({fmt_duration(duration)})"]
    if extra:
        lines.append(extra)
    return "<br>".join(lines)
