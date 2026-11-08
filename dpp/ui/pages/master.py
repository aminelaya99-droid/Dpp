"""الجدول العام (مثل aSc): كل الأقسام في شاشة واحدة، الأيام × الحصص (أو مقياس زمني)، بطاقات تُرفع وتوضع.

* النقر على بطاقة يرفعها (تتبع المؤشر) وتتلوّن خانات صفها: أخضر ممكن، أحمر تعارض؛ النقر مرة ثانية يضعها.
  السحب والإفلات يعمل أيضاً. Esc أو الزر الأيمن يلغي الرفع.
* طرف البطاقة يُسحب لتمديدها أو تقصيرها بخطوة 30 دقيقة (البداية أو النهاية)، مع فحص التعارض أثناء السحب.
* الشريط السفلي (يُكبَّر ويُصغَّر بالسحب): بطاقات مواد حرة تُوضع في أي قسم ثم يُختار الأستاذ،
  أو بطاقات الحجم الساعي، والحصص المُزالة. بحث، «مواد القسم فقط»، «المواد السابقة أولاً».
* Delete يعيد البطاقة إلى الشريط؛ Ctrl+Z / Ctrl+Y للتراجع والإعادة. الزر الأيمن: الحالة، الأستاذ، التعارض…
"""
from __future__ import annotations

import colorsys
import json
from dataclasses import dataclass
from datetime import date, timedelta

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QFontMetrics, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QAbstractScrollArea, QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMenu, QMessageBox, QPushButton, QSpinBox, QSplitter, QStyle,
                               QStyledItemDelegate, QToolButton, QToolTip, QVBoxLayout, QWidget)

from ...services import conflicts as CF
from ...services.grid import Card, GridError, TrayItem, WeekGrid, week_of_number
from ...services.structure import CATEGORY_LABELS
from ...utils import DAY_NAMES, STATUS_LABELS, hm, hm_range, iso
from .. import theme
from ..colors import subject_shade
from ..widgets import FlowLayout, confirm, error, icon, info

SIZES = {"s": (36, 62, 7.5), "m": (50, 80, 8.5), "l": (66, 104, 10)}         # ارتفاع الصف، عرض الحصة، الخط
TRAY_SIZES = {"s": (132, 44), "m": (172, 56), "l": (220, 72)}
DEFAULT_OPTIONS = {
    "show_teacher": True, "show_room": False, "show_time": False, "show_nonteach": True, "show_fri": True,
    "show_sat": True, "show_night": True, "show_conflicts": True, "show_tray": True, "show_done_mark": True,
    "level_stripe": True, "row_h": 50, "col_w": 80, "label_w": 184, "font_pt": 8.5, "size": "m",
    "layout": "periods", "card_style": "filled", "full_name": True, "fill_cell": True,
    "color_sections": "shade", "color_teachers": "level", "color_rooms": "level",
    "hidden_levels": [], "tray_all": False, "tray_mode": "free", "tray_only_section": False,
    "tray_history_first": True, "tray_size": "m", "tray_scale": 1.0, "tray_h": 190, "tray_side": False,
    # أحجام الأعمدة بالسحب: معامل لكل يوم، ومعامل لكل حصة/خانة (لكل شكل جدول)، وخانات مخفية
    "day_w": {}, "unit_w": {}, "hidden_units": {}, "grid_line_w": 1, "day_sep_w": 2, "freeze": True,
    "tray_sort": "default", "ask_duration": True,
}
LAYOUTS = [("periods", "حسب الحصص (مثل aSc)"), ("hours", "بالساعات (خانة لكل ساعة)"), ("time", "بنصف ساعة")]
COLOR_MODES = [("shade", "نوع المادة (درجة لكل مادة)"), ("subject", "لون المادة المحفوظ"), ("level", "الطور"),
               ("section", "القسم")]
VIEWS = [("sections", "الأقسام", "mdi6.google-classroom"), ("teachers", "الأساتذة", "mdi6.human-male-board"),
         ("rooms", "القاعات", "mdi6.door")]
SLOT = 30
DURATIONS = [30, 60, 90, 120, 150, 180, 210, 240]          # بالدقائق: من نصف ساعة إلى 4 ساعات


def duration_label(m: int) -> str:
    return {30: "30 دقيقة", 60: "ساعة", 90: "ساعة ونصف", 120: "ساعتان", 150: "ساعتان ونصف", 180: "3 ساعات",
            210: "3 ساعات ونصف", 240: "4 ساعات"}.get(m, f"{m / 60:g} سا")


DURATION_LABELS = {1: "ساعة", 2: "ساعتان", 3: "3 ساعات", 4: "4 ساعات"}     # توافق قديم


def load_options(db) -> dict:
    o = dict(DEFAULT_OPTIONS)
    try:
        o.update(json.loads(db.get_setting("grid_options", "") or "{}"))
    except Exception:
        pass
    o.pop("show_info", None)
    # الإصدار 1.4: الاسم الكامل للمادة، وألوان حسب نوع المادة بدرجة لكل مادة، والبطاقة تملأ خانة الحصة
    if db.get_setting("grid_options_v14", "") != "1":
        o.update({"full_name": True, "fill_cell": True, "color_sections": "shade",
                  "row_h": max(50, int(o.get("row_h") or 0)), "col_w": max(80, int(o.get("col_w") or 0)),
                  "tray_size": "m" if o.get("tray_size") == "s" else o.get("tray_size", "m")})
        db.set_setting("grid_options_v14", "1")
        save_options(db, o)
    if db.get_setting("grid_options_v141", "") != "1":     # 1.4.1: الشريط في الأسفل افتراضياً في كل الواجهات
        o["tray_side"] = False
        o["show_tray"] = True
        db.set_setting("grid_options_v141", "1")
        save_options(db, o)
    return o


def save_options(db, o: dict):
    db.set_setting("grid_options", json.dumps(o, ensure_ascii=False))


def wrap_text(text: str, fm: QFontMetrics, width: int, max_lines: int) -> list[str]:
    """يلف النص كلمةً كلمة في حدود العرض، ويختصر السطر الأخير بـ … إذا لم يتسع."""
    words = (text or "").split()
    if not words or width <= 4:
        return [text or ""]
    lines: list[str] = []
    cur = ""
    for i, w in enumerate(words):
        t = f"{cur} {w}".strip()
        if fm.horizontalAdvance(t) <= width or not cur:
            cur = t
            continue
        lines.append(cur)
        cur = w
        if len(lines) == max_lines - 1:
            cur = " ".join(words[i:])
            break
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
    lines[-1] = fm.elidedText(lines[-1], Qt.ElideRight, width)
    return lines


def fit_lines(text: str, font: QFont, width: int, height: int, min_pt: float = 6.5) -> tuple[QFont, list[str]]:
    """يختار أكبر خط (حتى min_pt) يتسع فيه الاسم كاملاً داخل المستطيل، بلا اختصار بـ «…» ما أمكن."""
    f = QFont(font)
    pt = f.pointSizeF() if f.pointSizeF() > 0 else 9.0
    while True:
        f.setPointSizeF(pt)
        fm = QFontMetrics(f)
        n = max(1, int(height // max(1, fm.lineSpacing())))
        lines = wrap_text(text, fm, width, 99)
        if (len(lines) <= n and all(fm.horizontalAdvance(x) <= width for x in lines)) or pt <= min_pt:
            if len(lines) > n:
                lines = wrap_text(text, fm, width, n)
            return f, lines
        pt -= 0.5


def _text_color(bg: QColor) -> QColor:
    from ..colors import text_for
    return text_for(bg)


def _hash_color(i: int) -> str:
    h = (i * 0.61803398875) % 1
    r, g, b = colorsys.hls_to_rgb(h, 0.78, 0.55)
    return QColor(int(r * 255), int(g * 255), int(b * 255)).name()


@dataclass
class Unit:
    """خانة عمود في اليوم: حصة (وضع الحصص) أو 30 دقيقة (الوضع الزمني)."""
    idx: int          # رقم الحصة (وضع الحصص) أو ترتيب الخانة
    start: int
    end: int
    label: str
    night: bool = False


# ====================================================================== الشبكة
class GridView(QAbstractScrollArea):
    card_selected = Signal(object)          # Card | None
    picked_changed = Signal(object)         # Card | TrayItem | None
    hover_cell = Signal(str)
    request_drop = Signal(object, int, int, int)   # item, row_index, day_idx, unit
    request_resize = Signal(object, int, int)      # card, start, end
    context_card = Signal(object, QPoint)
    section_clicked = Signal(int)
    teacher_clicked = Signal(int)

    HEADER_H = 46
    EDGE = 6

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setLayoutDirection(Qt.RightToLeft)
        self.rows: list[tuple] = []       # (key, label, color, sublabel)
        self.cards_of_row: list[list[Card]] = []
        self.lanes: dict[tuple[int, int], tuple[int, int]] = {}
        self.days: list[int] = [0, 1, 2, 3, 4, 5, 6]
        self.units: list[Unit] = []
        self.selected: Card | None = None
        self.selected_section: int | None = None
        self.picked = None
        self.mouse = QPoint()
        self.validity: dict = {}
        self.valid_row: int | None = None
        self.hover: tuple | None = None
        self._press_pos = None
        self.resizing: dict | None = None

    # ------------------------------------------------------------------ تخطيط
    @property
    def o(self):
        return self.page.options

    @property
    def nu(self) -> int:
        return len(self.units)

    def time_mode(self) -> bool:
        """الخانات زمنية موحّدة لكل الأقسام (بالساعات أو بنصف ساعة)، لا حصص مرقمة حسب القسم."""
        return self.o["layout"] in ("time", "hours")

    def slot(self) -> int:
        return 60 if self.o["layout"] == "hours" else SLOT

    def RH(self):
        return int(self.o["row_h"])

    def UW(self):
        """العرض الأساسي للخانة (قبل معاملات الأيام والخانات)."""
        base = max(14, int(self.o["col_w"]) // 2) if self.o["layout"] == "time" else int(self.o["col_w"])
        if len(self.days) == 1 and self.nu:          # يوم واحد: الخانات تملأ العرض
            fu = sum(self.unit_f(k) for k in range(self.nu)) or 1
            return max(base, int((self.viewport().width() - self.LW() - 2) / fu))
        return base

    def LW(self):
        return int(self.o["label_w"])

    # ------------------------------------------------------------------ أحجام الأعمدة (قابلة للسحب)
    def day_f(self, di: int) -> float:
        return float((self.o.get("day_w") or {}).get(str(di), 1.0))

    def unit_f(self, k: int) -> float:
        u = self.units[k] if k < len(self.units) else None
        key = f"{self.o['layout']}:{u.idx if u else k}"
        return float((self.o.get("unit_w") or {}).get(key, 1.0))

    def _layout_cols(self):
        uw = self.UW()
        self.col_w = []
        for di_i, di in enumerate(self.days):
            fd = self.day_f(di)
            for k in range(self.nu):
                self.col_w.append(max(8, int(round(uw * fd * self.unit_f(k)))))
        self.col_x0 = [0]
        for w in self.col_w:
            self.col_x0.append(self.col_x0[-1] + w)

    def total_w(self) -> int:
        return self.col_x0[-1] if getattr(self, "col_x0", None) else 0

    def col_at(self, fr: float) -> int | None:
        """رقم العمود لمسافة fr من حافة عمود التسميات (داخل منطقة الأيام)."""
        import bisect
        if fr < 0 or not getattr(self, "col_x0", None) or fr >= self.col_x0[-1]:
            return None
        return bisect.bisect_right(self.col_x0, fr) - 1

    def set_data(self, rows, cards_of_row, days, units):
        self.rows, self.cards_of_row, self.days, self.units = rows, cards_of_row, days, units
        self._layout_cols()
        self.lanes.clear()
        self.spans = {}
        for ri, cards in enumerate(cards_of_row):
            by_day = {}
            for c in cards:
                by_day.setdefault(c.wd, []).append(c)
            for lst in by_day.values():
                self._snap_spans(ri, lst)
                sp = lambda c: self.spans.get((ri, c.sid), (c.start, c.end))
                lst.sort(key=lambda c: (sp(c)[0], -sp(c)[1]))
                ends: list[int] = []
                assign = {}
                for c in lst:
                    a, b = sp(c)
                    for li, e in enumerate(ends):
                        if e <= a:
                            ends[li] = b
                            assign[c.sid] = li
                            break
                    else:
                        ends.append(b)
                        assign[c.sid] = len(ends) - 1
                n = max(1, len(ends))
                for c in lst:
                    self.lanes[(ri, c.sid)] = (assign[c.sid], n)
        self._update_scroll()
        self.viewport().update()

    def _snap_spans(self, ri: int, lst: list):
        """في وضع الحصص: البطاقة تملأ خانتها فقط إذا كان الفرق صغيراً (حتى 15 د من كل جهة، مثل 08:00–09:50
        في خانة 08:00–10:00 المستوردة من aSc). البطاقة الأقصر فعلاً من خانتها (30 د أو ساعة في خانة ساعتين)
        تُرسم بحجمها الحقيقي في موضعها، ولا تملأ الخانة إذا كانت فيها حصة أخرى لنفس الصف."""
        if self.time_mode() or not self.o.get("fill_cell", True) or not lst:
            return
        snapped = {}
        for c in lst:
            units = self.row_units(ri, c)
            a = next((u.start for u in units if u.start <= c.start < u.end), c.start)
            b = next((u.end for u in units if u.start < c.end <= u.end), c.end)
            a, b = min(a, c.start), max(b, c.end)
            if c.start - a > 15 or b - c.end > 15:
                a, b = c.start, c.end                      # أقصر من خانتها: حجمها الحقيقي
            snapped[c.sid] = (a, b)
        for c in lst:
            a, b = snapped[c.sid]
            if (a, b) == (c.start, c.end):
                continue
            clash = any(o.sid != c.sid and o.start < b and o.end > a and not (o.start < c.end and o.end > c.start)
                        for o in lst)
            if not clash:
                self.spans[(ri, c.sid)] = (a, b)

    def _update_scroll(self):
        total_w = self.LW() + self.total_w()
        total_h = self.HEADER_H + len(self.rows) * self.RH()
        vw, vh = self.viewport().width(), self.viewport().height()
        self.horizontalScrollBar().setRange(0, max(0, total_w - vw))
        self.horizontalScrollBar().setPageStep(vw)
        self.horizontalScrollBar().setSingleStep(max(10, self.UW()))
        self.verticalScrollBar().setRange(0, max(0, total_h - vh))
        self.verticalScrollBar().setPageStep(vh)
        self.verticalScrollBar().setSingleStep(self.RH())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if len(self.days) == 1:
            self._layout_cols()
        self._update_scroll()

    def scrollContentsBy(self, dx, dy):
        self.viewport().update()

    # إحداثيات: x يُحسب من اليمين (RTL)
    def col_rect(self, col: int, row: int | None = None) -> QRect:
        vw = self.viewport().width()
        hs = self.horizontalScrollBar().value()
        if not getattr(self, "col_x0", None) or col >= len(self.col_w):
            self._layout_cols()
        col = max(0, min(col, len(self.col_w) - 1))
        uw = self.col_w[col]
        x = vw - (self.LW() + self.col_x0[col + 1] - hs)
        if row is None:
            return QRect(x, 0, uw, self.HEADER_H)
        y = self.HEADER_H + row * self.RH() - self.verticalScrollBar().value()
        return QRect(x, y, uw, self.RH())

    def hit(self, p: QPoint):
        """(row, col) أو None؛ col=-1 لعمود التسميات."""
        vw = self.viewport().width()
        fr = vw - p.x()
        if p.y() < self.HEADER_H:
            return None
        row = (p.y() - self.HEADER_H + self.verticalScrollBar().value()) // self.RH()
        if not 0 <= row < len(self.rows):
            return None
        if fr < self.LW():
            return row, -1
        col = self.col_at(fr - self.LW() + self.horizontalScrollBar().value())
        if col is None:
            return None
        return row, col

    def row_section(self, ri: int, card=None) -> int | None:
        key = self.rows[ri][0]
        if key[0] == "s":
            return key[1]
        if isinstance(card, Card) and card.sections:
            return card.sections[0]
        return getattr(card, "section", None)

    def row_units(self, ri: int, card=None) -> list[Unit]:
        """خانات اليوم بأوقات قسم الصف (في وضع الحصص تختلف الأوقات بين الأطوار)."""
        if self.time_mode():
            return self.units
        sec = self.row_section(ri, card)
        ps = {p.idx: p for p in self.page.grid.pm.periods(sec)}
        return [Unit(u.idx, ps[u.idx].start, ps[u.idx].end, u.label, u.night) if u.idx in ps else u
                for u in self.units]

    def minute_x(self, ri: int, di_i: int, minute: int, card=None) -> float:
        """موضع الدقيقة أفقياً داخل يوم (الزمن يجري من اليمين إلى اليسار)."""
        units = self.row_units(ri, card)
        for k, u in enumerate(units):
            cell = self.col_rect(di_i * self.nu + k, ri)
            right = cell.x() + cell.width()
            if minute <= u.start:
                return right
            if minute <= u.end:
                frac = (minute - u.start) / max(1, u.end - u.start)
                return right - frac * cell.width()
        last = self.col_rect(di_i * self.nu + self.nu - 1, ri)
        return last.x()

    def x_minute(self, ri: int, x: float, card=None) -> tuple[int, int] | None:
        """(day_idx_in_days, دقيقة مقربة إلى 30) للموضع الأفقي x."""
        vw = self.viewport().width()
        fr = vw - x - self.LW() + self.horizontalScrollBar().value()
        col = self.col_at(fr)
        if col is None:
            return None
        di_i, k = divmod(col, self.nu)
        u = self.row_units(ri, card)[k]
        frac = (fr - self.col_x0[col]) / max(1, self.col_w[col])
        m = u.start + frac * (u.end - u.start)
        st = self.slot()
        return di_i, int(round(m / st) * st)

    def x_minute_raw(self, ri: int, x: float, card=None) -> int | None:
        """الدقيقة (بلا تقريب) تحت الموضع الأفقي x."""
        vw = self.viewport().width()
        fr = vw - x - self.LW() + self.horizontalScrollBar().value()
        col = self.col_at(fr)
        if col is None:
            return None
        k = col % self.nu
        u = self.row_units(ri, card)[k]
        frac = (fr - self.col_x0[col]) / max(1, self.col_w[col])
        return int(u.start + frac * (u.end - u.start))

    def card_rect(self, ri: int, c: Card) -> QRectF | None:
        if c.wd not in self.days or not self.units:
            return None
        di_i = self.days.index(c.wd)
        a, b = self.spans.get((ri, c.sid), (c.start, c.end))
        x1 = self.minute_x(ri, di_i, a, c)
        x2 = self.minute_x(ri, di_i, b, c)
        if abs(x1 - x2) < 3:
            return None
        y = self.HEADER_H + ri * self.RH() - self.verticalScrollBar().value()
        lane, n = self.lanes.get((ri, c.sid), (0, 1))
        h = self.RH() / n
        left, right = min(x1, x2), max(x1, x2)
        return QRectF(left + 1.5, y + lane * h + 1.5, right - left - 3, h - 3)

    def card_at(self, p: QPoint):
        h = self.hit(p)
        if not h or h[1] < 0:
            return None, h
        ri = h[0]
        for c in self.cards_of_row[ri]:
            r = self.card_rect(ri, c)
            if r and r.adjusted(-2, 0, 2, 0).contains(p):
                return c, h
        return None, h

    def edge_at(self, p: QPoint):
        """(card, row, 'start'|'end') إذا كان المؤشر على طرف بطاقة."""
        c, h = self.card_at(p)
        if not c:
            return None
        r = self.card_rect(h[0], c)
        if abs(p.x() - r.right()) <= self.EDGE:
            return c, h[0], "start"            # اليمين = البداية (RTL)
        if abs(p.x() - r.left()) <= self.EDGE:
            return c, h[0], "end"
        return None

    # ------------------------------------------------------------------ ألوان
    def card_color(self, c) -> QColor:
        col = self._card_color(c)
        sf = QColor(theme.CURRENT["surface"])
        if sf.lightness() < 100:      # في الوضع الداكن: تخفيف السطوع لراحة العين مع بقاء التباين
            k = 0.18
            col = QColor(int(col.red() * (1 - k) + sf.red() * k), int(col.green() * (1 - k) + sf.green() * k),
                         int(col.blue() * (1 - k) + sf.blue() * k))
        return col

    def _card_color(self, c) -> QColor:
        mode = self.page.color_mode()
        if c.subject in getattr(self.page, "fullday_ids", ()) or getattr(c, "full_day", False):
            return QColor(c.color or "#E8A3A3")
        g = self.page.grid
        secs = getattr(c, "sections", None) or ([c.section] if getattr(c, "section", None) else [])
        if mode == "level":
            s = g.sec_by_id.get(secs[0]) if secs else None
            col = QColor(s.level_color if s else "#9AA5A8")
            return col.lighter(150) if c.category != "nonteach" else QColor("#CFD4DA")
        if mode == "section" and secs:
            return QColor(_hash_color(secs[0]))
        if mode == "shade":
            return subject_shade(c.category, c.subject)
        return QColor(c.color or "#CCCCCC")

    # ------------------------------------------------------------------ رسم
    def paintEvent(self, _):
        t = theme.CURRENT
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.Antialiasing)
        vw, vh = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, vw, vh, QColor(t["surface"]))
        if not self.rows or not self.units:
            p.setPen(QColor(t["muted"]))
            p.drawText(self.viewport().rect(), Qt.AlignCenter,
                       "لا توجد أقسام بعد.\nاستورد الأسابيع السابقة من صفحة «الاستيراد» (ملفات aSc .roz) "
                       "أو أنشئ الأطوار والأقسام من «البيانات».")
            p.end()
            return
        RH, UW, LW = self.RH(), self.UW(), self.LW()
        vs = self.verticalScrollBar().value()
        r0 = max(0, vs // RH)
        r1 = min(len(self.rows), (vs + vh) // RH + 1)
        ncols = len(self.days) * self.nu
        grid_pen = QPen(QColor(t["grid"]), float(self.o.get("grid_line_w", 1)))
        day_pen = QPen(QColor(t["border"]), float(self.o.get("day_sep_w", 2)))
        accent = QColor(t["accent"])
        f = QFont(self.font())
        f.setPointSizeF(float(self.o["font_pt"]))
        p.setFont(f)
        fm = QFontMetrics(f)
        # خلفية الصفوف + خطوط
        prev_level = None
        for ri in range(r0, r1):
            y = self.HEADER_H + ri * RH - vs
            key, label, color, sub = self.rows[ri]
            if ri % 2:
                p.fillRect(0, y, vw - LW, RH, QColor(t["surface2"]))
            p.setPen(grid_pen)
            p.drawLine(0, y + RH, vw, y + RH)
            if sub != prev_level and ri > 0 and key[0] == "s":
                p.setPen(QPen(QColor(color), 2))
                p.drawLine(0, y, vw, y)
            prev_level = sub
        # الفترة الليلية مظللة قليلاً
        night_cols = [k for k, u in enumerate(self.units) if u.night]
        if night_cols:
            shade = QColor(t["header"])
            for di_i in range(len(self.days)):
                for k in night_cols:
                    rc = self.col_rect(di_i * self.nu + k)
                    p.fillRect(QRect(rc.x(), self.HEADER_H, rc.width(), vh), shade)
        # عمود اليوم الحالي
        g0 = self.page.grid
        today_idx = (date.today() - g0.ws).days
        if today_idx in self.days:
            a = self.col_rect(self.days.index(today_idx) * self.nu)
            b = self.col_rect(self.days.index(today_idx) * self.nu + self.nu - 1)
            band = a.united(b)
            tint = QColor(accent)
            tint.setAlpha(18)
            p.fillRect(QRect(band.x(), self.HEADER_H, band.width(), vh), tint)
        # تمييز الصف تحت المؤشر والقسم المحدد
        for ri_h, alpha in ((self.hover[0] if self.hover else None, 22),
                            (self._row_of_section(self.selected_section), 34)):
            if ri_h is not None and r0 <= ri_h < r1:
                hy = self.HEADER_H + ri_h * RH - vs
                tint = QColor(accent)
                tint.setAlpha(alpha)
                p.fillRect(0, hy, vw - LW, RH, tint)
        # خانات صالحة/غير صالحة أثناء الرفع
        if self.picked is not None and self.valid_row is not None and r0 <= self.valid_row < r1:
            okc, badc = QColor(t["ok"]), QColor(t["bad"])
            okc.setAlpha(70)
            badc.setAlpha(45)
            for (di, k), (ok, _m) in self.validity.items():
                if di not in self.days or k >= self.nu:
                    continue
                rc = self.col_rect(self.days.index(di) * self.nu + k, self.valid_row)
                p.fillRect(rc.adjusted(1, 1, -1, -1), okc if ok else badc)
        # الخطوط العمودية
        hour_pen = QPen(QColor(t["grid"]))
        hour_pen.setStyle(Qt.DotLine)
        for c in range(ncols):
            rc = self.col_rect(c)
            k = c % self.nu
            if k == 0:
                p.setPen(day_pen)
            elif self.o["layout"] == "time" and self.units[k].start % 60:
                p.setPen(hour_pen)
            else:
                p.setPen(grid_pen)
            p.drawLine(rc.x() + rc.width(), self.HEADER_H, rc.x() + rc.width(), vh)
            if c == ncols - 1:
                p.setPen(day_pen)
                p.drawLine(rc.x(), self.HEADER_H, rc.x(), vh)
        # إطار الخانة الهدف
        if self.hover and self.hover[1] >= 0 and r0 <= self.hover[0] < r1 and not self.resizing:
            rc = self.col_rect(self.hover[1], self.hover[0])
            p.setPen(QPen(accent, 2 if self.picked is not None else 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(rc).adjusted(1, 1, -1, -1), 3, 3)
        # أحداث «اليوم كاملاً» من صفحة الأحداث: شريط مخطط على يوم القسم
        dev = getattr(self.page.grid, "day_events", {}) or {}
        if dev:
            evc = QColor(t["warn"])
            for ri in range(r0, r1):
                key = self.rows[ri][0]
                if key[0] != "s":
                    continue
                for di_i, di in enumerate(self.days):
                    evs = dev.get((key[1], self.page.grid.ws + timedelta(days=di)))
                    if not evs:
                        continue
                    band = self.col_rect(di_i * self.nu, ri).united(self.col_rect(di_i * self.nu + self.nu - 1, ri))
                    fill = QColor(evc)
                    fill.setAlpha(40)
                    p.fillRect(band.adjusted(1, 1, -1, -1), fill)
                    p.fillRect(band.adjusted(1, 1, -1, -1), QBrush(QColor(evc.red(), evc.green(), evc.blue(), 70),
                                                                   Qt.BDiagPattern))
                    p.setPen(QColor(t["text"]))
                    p.drawText(band.adjusted(4, 2, -4, -2), Qt.AlignCenter | Qt.TextWordWrap,
                               " · ".join(x[0] for x in evs[:2]))
        # البطاقات
        conf = self.page.grid.conflict_by_sid if self.o["show_conflicts"] else {}
        for ri in range(r0, r1):
            for c in self.cards_of_row[ri]:
                if self.resizing and self.resizing["card"].sid == c.sid:
                    continue
                rect = self.card_rect(ri, c)
                if rect is None or rect.right() < 0 or rect.left() > vw - LW:
                    continue
                if self.picked is c:
                    p.setOpacity(0.35)
                self._draw_card(p, rect, c, conf.get(c.sid), fm)
                p.setOpacity(1.0)
        # بطاقة قيد التمديد
        if self.resizing:
            rz = self.resizing
            c = rz["card"]
            di_i = self.days.index(c.wd)
            x1 = self.minute_x(rz["row"], di_i, rz["start"], c)
            x2 = self.minute_x(rz["row"], di_i, rz["end"], c)
            y = self.HEADER_H + rz["row"] * RH - vs
            rect = QRectF(min(x1, x2) + 1.5, y + 1.5, abs(x2 - x1) - 3, RH - 3)
            self._draw_card(p, rect, c, None, fm, extra=hm_range(rz["start"], rz["end"]))
            p.setPen(QPen(QColor(t["ok"] if not rz["msgs"] else t["bad"]), 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 6, 6)
        # عمود التسميات (مثبت)
        p.fillRect(vw - LW, self.HEADER_H, LW, vh, QColor(t["header"]))
        bold = QFont(f)
        bold.setBold(True)
        for ri in range(r0, r1):
            y = self.HEADER_H + ri * RH - vs
            key, label, color, sub = self.rows[ri]
            sel = key[0] == "s" and key[1] == self.selected_section
            if sel or (self.hover and self.hover[0] == ri):
                tint = QColor(accent)
                tint.setAlpha(60 if sel else 30)
                p.fillRect(vw - LW, y, LW, RH, tint)
            p.fillRect(vw - 5, y + 1, 5, RH - 2, QColor(color))
            p.setPen(QColor(t["text"]))
            p.setFont(bold)
            p.drawText(QRect(vw - LW + 6, y + 2, LW - 16, RH - 4), Qt.AlignVCenter | Qt.AlignRight | Qt.TextWordWrap,
                       fm.elidedText(label, Qt.ElideRight, (LW - 16) * 2))
            p.setFont(f)
            p.setPen(grid_pen)
            p.drawLine(vw - LW, y + RH, vw, y + RH)
        p.setPen(QPen(QColor(t["border"]), 1))
        p.drawLine(vw - LW, 0, vw - LW, vh)
        self._paint_header(p, f, accent, grid_pen, day_pen)
        # البطاقة المرفوعة تتبع المؤشر
        if self.picked is not None:
            w = max(UW, int(max(60, self.picked.minutes) / 120 * self.o["col_w"]))
            rect = QRectF(self.mouse.x() - w / 2, self.mouse.y() - RH / 2, w, RH - 4)
            p.setOpacity(0.88)
            self._draw_card(p, rect, self.picked, None, fm, ghost=True)
            p.setOpacity(1)
        p.end()

    def _paint_header(self, p, f, accent, grid_pen, day_pen):
        t = theme.CURRENT
        vw = self.viewport().width()
        LW = self.LW()
        p.fillRect(0, 0, vw, self.HEADER_H, QColor(t["header"]))
        g = self.page.grid
        for di_i, di in enumerate(self.days):
            band = self.col_rect(di_i * self.nu).united(self.col_rect(di_i * self.nu + self.nu - 1))
            d = g.ws + timedelta(days=di)
            today = d == date.today()
            bf = QFont(f)
            bf.setBold(True)
            bf.setPointSizeF(float(self.o["font_pt"]) + 1)
            p.setFont(bf)
            txt = f"{DAY_NAMES[di]}  {d.strftime('%d/%m')}"
            if today:
                tw = QFontMetrics(bf).horizontalAdvance(txt) + 18
                pill = QRectF(band.center().x() - tw / 2, 3, tw, 20)
                p.setPen(Qt.NoPen)
                p.setBrush(accent)
                p.drawRoundedRect(pill, 10, 10)
                p.setPen(QColor(t["accent_text"]))
            else:
                p.setPen(QColor(t["text"]))
            p.drawText(QRect(band.x(), 3, band.width(), 20), Qt.AlignCenter, txt)
            p.setFont(f)
            p.setPen(QColor(t["muted"]))
            if self.o["layout"] == "hours":
                for k, u in enumerate(self.units):
                    rc = self.col_rect(di_i * self.nu + k)
                    p.drawText(QRect(rc.x(), 24, rc.width(), 20), Qt.AlignCenter,
                               hm(u.start) if rc.width() >= 40 else f"{u.start // 60:02d}")
            elif self.time_mode():
                for k, u in enumerate(self.units):
                    if u.start % 60 == 0 and (k + 1 < self.nu and self.units[k + 1].start == u.start + SLOT):
                        rc = self.col_rect(di_i * self.nu + k).united(self.col_rect(di_i * self.nu + k + 1))
                        p.drawText(QRect(rc.x(), 24, rc.width(), 20), Qt.AlignCenter, f"{u.start // 60:02d}")
            else:
                for k, u in enumerate(self.units):
                    rc = self.col_rect(di_i * self.nu + k)
                    p.drawText(QRect(rc.x(), 24, rc.width(), 20), Qt.AlignCenter, u.label)
            p.setPen(day_pen)
            p.drawLine(band.x(), 0, band.x(), self.HEADER_H)
        p.setPen(grid_pen)
        p.drawLine(0, self.HEADER_H - 1, vw, self.HEADER_H - 1)
        p.fillRect(vw - LW, 0, LW, self.HEADER_H, QColor(t["header"]))
        p.setPen(QColor(t["muted"]))
        p.drawText(QRect(vw - LW + 4, 0, LW - 10, self.HEADER_H), Qt.AlignCenter,
                   {"sections": "القسم", "teachers": "الأستاذ", "rooms": "القاعة"}[self.page.view])

    def _draw_card(self, p: QPainter, rect: QRectF, c, conf, fm, ghost=False, extra: str | None = None):
        t = theme.CURRENT
        col = self.card_color(c)
        outline = self.o["card_style"] == "outline"
        dark = theme.is_dark()
        if outline:
            bg = QColor(t["surface2"])
            fg = col.lighter(135) if dark else col.darker(185)
            border = QPen(col, 1.8)
        else:
            bg = col
            fg = _text_color(bg)
            border = QPen(bg.darker(118), 1)
        if getattr(c, "status", "planned") in ("postponed", "cancelled"):
            bg = QColor(bg)
            bg.setAlpha(110)
        r_ = 5
        p.setPen(border)
        p.setBrush(bg)
        p.drawRoundedRect(rect, r_, r_)
        p.setPen(Qt.NoPen)
        if self.o["level_stripe"] and self.page.color_mode() in ("subject", "shade"):
            secs = getattr(c, "sections", None) or [getattr(c, "section", None)]
            s = self.page.grid.sec_by_id.get(secs[0]) if secs and secs[0] else None
            if s:
                p.setBrush(QColor(s.level_color))
                p.drawRoundedRect(QRectF(rect.right() - 4, rect.y(), 4, rect.height()), 2, 2)
        sel = (self.selected is not None and not ghost and isinstance(c, Card) and self.selected.sid == c.sid)
        if conf:
            p.setPen(QPen(QColor(t["bad"]), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), r_, r_)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["bad"]))
            x0 = rect.x()
            p.drawPolygon([QPoint(int(x0), int(rect.y())), QPoint(int(x0 + 9), int(rect.y())),
                           QPoint(int(x0), int(rect.y() + 9))])
        if sel:
            p.setPen(QPen(QColor(t["accent"]), 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(rect.adjusted(-1.5, -1.5, 1.5, 1.5), r_ + 1, r_ + 1)
        p.setPen(fg)
        full = self.o.get("full_name", True)
        lines = [c.sname if full else c.sshort]
        if extra:
            lines.append(extra)
        elif self.o["show_time"] and isinstance(c, Card):
            lines.append(hm_range(c.start, c.end))
        view = self.page.view
        if view == "sections":
            if self.o["show_teacher"] and getattr(c, "tname", ""):
                lines.append(self.page.grid.tshort.get(getattr(c, "teacher", None)) or c.tname)
        else:
            secs = getattr(c, "sections", None) or ([c.section] if getattr(c, "section", None) else [])
            if secs:
                lines.append("، ".join(self.page.grid.sec_by_id[s].short for s in secs
                                       if s in self.page.grid.sec_by_id)[:40])
        if self.o["show_room"] and getattr(c, "rname", ""):
            lines.append(c.rname)
        max_lines = max(1, int(rect.height() // (fm.height() + 1)))
        width = int(rect.width() - 8)
        # الاسم الكامل يلتف على عدة أسطر، وما تبقى من الأسطر للأستاذ والوقت
        name_lines = wrap_text(lines[0], fm, width, max(1, max_lines - min(len(lines) - 1, max_lines // 2)))
        rest = [fm.elidedText(x, Qt.ElideRight, width) for x in lines[1:]]
        text = "\n".join((name_lines + rest)[:max_lines])
        p.drawText(rect.adjusted(3, 1, -5, -1), Qt.AlignCenter, text)
        if self.o["show_done_mark"] and getattr(c, "status", "") == "done" and rect.height() > 14:
            rr = 3.6
            cx, cy = rect.x() + 3 + rr, rect.bottom() - 3 - rr
            op = p.opacity()
            p.setOpacity(0.75 * op)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#15803D"))
            p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))
            p.setPen(QPen(QColor("white"), 1.4))
            p.drawPolyline([QPoint(int(cx - 1.8), int(cy)), QPoint(int(cx - 0.4), int(cy + 1.5)),
                            QPoint(int(cx + 2), int(cy - 1.5))])
            p.setOpacity(op)
        if getattr(c, "status", "") in ("postponed", "cancelled"):
            p.setPen(QPen(fg, 1))
            p.drawLine(rect.topLeft(), rect.bottomRight())

    def _row_of_section(self, sec: int | None) -> int | None:
        if sec is None:
            return None
        for ri, (key, *_r) in enumerate(self.rows):
            if key == ("s", sec):
                return ri
        return None

    # ------------------------------------------------------------------ تفاعل
    def allowed_row(self, ri: int) -> bool:
        it = self.picked
        if it is None:
            return False
        key = self.rows[ri][0]
        if isinstance(it, TrayItem) and it.free:
            return key[0] == "s"               # المادة الحرة تُوضع في أي قسم
        if key[0] == "s":
            secs = it.sections if isinstance(it, Card) else [it.section]
            return key[1] in secs
        if key[0] == "t":
            return key[1] == it.teacher
        if key[0] == "r":
            return isinstance(it, Card) and key[1] == it.room
        return False

    def proposal(self, ri: int, di: int, k: int):
        it = self.picked
        sec = self.row_section(ri, it)
        if sec is None or k >= self.nu:
            return None
        g = self.page.grid
        if self.time_mode():
            return g.proposal_at(it.minutes, sec, di, self.units[k].start)
        return g.proposal(it.minutes, sec, di, self.units[k].idx)

    def compute_validity(self, ri: int):
        self.valid_row = ri
        self.validity = {}
        it = self.picked
        if it is None or not self.allowed_row(ri):
            return
        g = self.page.grid
        sec = self.row_section(ri, it)
        if sec is None:
            return
        chk = g.checker_for(it, sec)
        for di in self.days:
            for k in range(self.nu):
                prop = self.proposal(ri, di, k)
                if prop is None:
                    self.validity[(di, k)] = (False, ["خارج أوقات اليوم"])
                else:
                    msgs = chk(*prop)
                    self.validity[(di, k)] = (not msgs, msgs)

    def pick(self, item):
        self.picked = item
        self.valid_row = None
        self.validity = {}
        if item is not None:
            target = self.hover[0] if self.hover and self.allowed_row(self.hover[0]) else None
            if target is None:
                target = next((ri for ri in range(len(self.rows)) if self.allowed_row(ri)
                               and (not isinstance(item, TrayItem) or not item.free
                                    or self.rows[ri][0] == ("s", self.selected_section))), None)
            if target is not None:
                self.compute_validity(target)
            self.setFocus()
        self.picked_changed.emit(item)
        self.viewport().update()

    def cancel_pick(self):
        if self.picked is not None:
            self.pick(None)
        if self.resizing:
            self.resizing = None
            self.viewport().update()

    # ------------------------------------------------------------------ تغيير الأحجام بالسحب (الرأس وعمود التسميات)
    def size_handle(self, p: QPoint):
        """مقبض تغيير حجم تحت المؤشر: ('label',) أو ('row', ri) أو ('unit', col) أو ('day', di_i)."""
        vw = self.viewport().width()
        lx = vw - self.LW()
        if abs(p.x() - lx) <= 4:
            return ("label",)
        if p.x() > lx and p.y() >= self.HEADER_H:
            off = (p.y() - self.HEADER_H + self.verticalScrollBar().value()) % self.RH()
            ri = (p.y() - self.HEADER_H + self.verticalScrollBar().value()) // self.RH()
            if (off >= self.RH() - 4 or off <= 3) and 0 <= ri < len(self.rows):
                return ("row", ri)
            return None
        if p.y() >= self.HEADER_H or not self.nu:
            return None
        fr = vw - p.x() - self.LW() + self.horizontalScrollBar().value()
        col = self.col_at(fr)
        if col is None:
            return None
        rc = self.col_rect(col)
        if abs(p.x() - rc.x()) > 4:
            return None
        di_i, k = divmod(col, self.nu)
        if p.y() < 24:
            return ("day", di_i) if k == self.nu - 1 else None
        return ("unit", col)

    def _start_size_drag(self, h, p: QPoint):
        if h[0] == "label":
            self.size_drag = {"h": h, "x0": p.x(), "w0": self.LW()}
        elif h[0] == "row":
            self.size_drag = {"h": h, "y0": p.y(), "h0": self.RH()}
        elif h[0] == "unit":
            self.size_drag = {"h": h, "x0": p.x(), "w0": self.col_w[h[1]]}
        else:
            di_i = h[1]
            band = sum(self.col_w[di_i * self.nu + k] for k in range(self.nu))
            self.size_drag = {"h": h, "x0": p.x(), "w0": band}

    def _do_size_drag(self, p: QPoint):
        sd = self.size_drag
        h = sd["h"]
        o = self.o
        if h[0] == "label":
            o["label_w"] = int(max(60, min(520, sd["w0"] + (sd["x0"] - p.x()))))
        elif h[0] == "row":
            o["row_h"] = int(max(18, min(220, sd["h0"] + (p.y() - sd["y0"]))))
        elif h[0] == "unit":
            col = h[1]
            di_i, k = divmod(col, self.nu)
            new = max(12, sd["w0"] + (sd["x0"] - p.x()))
            fu = new / max(1.0, self.UW() * self.day_f(self.days[di_i]))
            o.setdefault("unit_w", {})[f"{o['layout']}:{self.units[k].idx}"] = round(max(0.2, min(8.0, fu)), 3)
        else:
            di_i = h[1]
            new = max(40, sd["w0"] + (sd["x0"] - p.x()))
            fsum = sum(self.unit_f(k) for k in range(self.nu)) or 1
            o.setdefault("day_w", {})[str(self.days[di_i])] = round(max(0.2, min(8.0, new / (self.UW() * fsum))), 3)
        self._layout_cols()
        self._update_scroll()
        self.viewport().update()

    def reset_size(self, h):
        o = self.o
        if h[0] == "label":
            o["label_w"] = DEFAULT_OPTIONS["label_w"]
        elif h[0] == "row":
            o["row_h"] = DEFAULT_OPTIONS["row_h"]
        elif h[0] == "unit":
            k = h[1] % self.nu
            (o.get("unit_w") or {}).pop(f"{o['layout']}:{self.units[k].idx}", None)
        else:
            (o.get("day_w") or {}).pop(str(self.days[h[1]]), None)
        self.page._save()
        self._layout_cols()
        self._update_scroll()
        self.viewport().update()

    def mouseDoubleClickEvent(self, e):
        h = self.size_handle(e.position().toPoint())
        if h:
            self.reset_size(h)
            return
        super().mouseDoubleClickEvent(e)

    def _header_menu(self, p: QPoint, gpos):
        """قائمة رأس الجدول: إخفاء حصة أو يوم، وإرجاع الأحجام."""
        vw = self.viewport().width()
        fr = vw - p.x() - self.LW() + self.horizontalScrollBar().value()
        col = self.col_at(fr)
        o = self.o
        m = QMenu(self)
        if col is not None:
            di_i, k = divmod(col, self.nu)
            di, u = self.days[di_i], self.units[k]
            lab = f"الحصة {u.label}" if o["layout"] == "periods" else hm_range(u.start, u.end)
            m.addAction(f"إخفاء {lab} (من كل الأيام)", lambda: self.page.hide_unit(u.idx))
            m.addAction(f"إخفاء يوم {DAY_NAMES[di]}", lambda: self.page.hide_day(di))
            m.addAction("إرجاع عرض هذه الخانة", lambda: self.reset_size(("unit", col)))
            m.addAction(f"إرجاع عرض يوم {DAY_NAMES[di]}", lambda: self.reset_size(("day", di_i)))
            m.addSeparator()
        m.addAction("إظهار كل الحصص والأيام", self.page.show_all_units)
        m.addAction("إرجاع كل الأحجام", self.page.reset_all_sizes)
        lm = m.addMenu("شكل الجدول")
        for k2, lab2 in LAYOUTS:
            a = lm.addAction(lab2, lambda k2=k2: self.page.set_layout(k2))
            a.setCheckable(True)
            a.setChecked(o["layout"] == k2)
        m.exec(gpos)

    def mousePressEvent(self, e):
        pos = e.position().toPoint()
        self._press_pos = pos
        if e.button() == Qt.LeftButton and self.picked is None:
            h = self.size_handle(pos)
            if h:
                self._start_size_drag(h, pos)
                return
        if e.button() == Qt.RightButton and pos.y() < self.HEADER_H and self.picked is None:
            self._header_menu(pos, e.globalPosition().toPoint())
            return
        if e.button() == Qt.RightButton:
            if self.picked is not None or self.resizing:
                self.cancel_pick()
                return
            c, _h = self.card_at(pos)
            if c:
                self.selected = c
                self.card_selected.emit(c)
                self.context_card.emit(c, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        if self.picked is not None:
            self._drop(pos)
            return
        h = self.hit(pos)
        if h and h[1] == -1:                     # نقر على اسم القسم: تحديده للشريط السفلي
            key = self.rows[h[0]][0]
            if key[0] == "s":
                self.selected_section = key[1]
                self.section_clicked.emit(key[1])
                self.viewport().update()
            elif key[0] == "t":
                self.teacher_clicked.emit(key[1])
            return
        edge = self.edge_at(pos)
        if edge:
            c, ri, side = edge
            self.selected = c
            self.card_selected.emit(c)
            self.resizing = {"card": c, "row": ri, "side": side, "start": c.start, "end": c.end, "msgs": []}
            self.viewport().update()
            return
        c, h = self.card_at(pos)
        if c:
            self.selected = c
            if h and self.rows[h[0]][0][0] == "s":
                self.selected_section = self.rows[h[0]][0][1]
            self.card_selected.emit(c)
            self.pick(c)
        else:
            self.selected = None
            self.card_selected.emit(None)
        self.viewport().update()

    def mouseReleaseEvent(self, e):
        pos = e.position().toPoint()
        if getattr(self, "size_drag", None):
            self.size_drag = None
            self.page._save()
            self.page.rebuild()
            return
        if self.resizing and e.button() == Qt.LeftButton:
            rz, self.resizing = self.resizing, None
            if (rz["start"], rz["end"]) != (rz["card"].start, rz["card"].end):
                self.request_resize.emit(rz["card"], rz["start"], rz["end"])
            self.viewport().update()
            self._press_pos = None
            return
        if self.picked is not None and self._press_pos is not None and e.button() == Qt.LeftButton \
                and (pos - self._press_pos).manhattanLength() > 10:
            self._drop(pos)    # سحب وإفلات
        self._press_pos = None

    def _drop(self, pos: QPoint):
        h = self.hit(pos)
        if not h or h[1] < 0:
            return
        ri, col = h
        if not self.allowed_row(ri):
            self.page.sound("conflict")
            self.page.flash("لا يمكن وضع هذه البطاقة في هذا الصف.")
            return
        di = self.days[col // self.nu]
        self.last_drop_x = pos.x()           # لموضع البطاقة القصيرة داخل خانتها (نصف الساعة الأولى أو الثانية…)
        self.request_drop.emit(self.picked, ri, di, col % self.nu)

    def _update_resize(self, pos: QPoint):
        rz = self.resizing
        c = rz["card"]
        hm_ = self.x_minute(rz["row"], pos.x(), c)
        if hm_ is None:
            return
        di_i, m = hm_
        if self.days[di_i] != c.wd:
            return
        g = self.page.grid
        sec = self.row_section(rz["row"], c)
        lo, hi = g.day_start(sec), g.day_limit(sec, c.start)
        if rz["side"] == "end":
            rz["end"] = max(rz["start"] + 60, min(hi, m))
        else:
            rz["start"] = min(rz["end"] - 60, max(lo, m))
        rz["msgs"] = g.check_card(c, c.day, rz["start"], rz["end"])
        msg = f"{c.sname}: {hm_range(rz['start'], rz['end'])} ({(rz['end'] - rz['start']) / 60:g} سا)"
        if rz["msgs"]:
            msg += "  — غير متاح: " + " · ".join(rz["msgs"][:2])
        self.hover_cell.emit(msg)

    def mouseMoveEvent(self, e):
        self.mouse = e.position().toPoint()
        if getattr(self, "size_drag", None):
            self._do_size_drag(self.mouse)
            return
        if self.picked is None and not self.resizing:
            h = self.size_handle(self.mouse)
            if h:
                self.viewport().setCursor(Qt.SizeVerCursor if h[0] == "row" else Qt.SizeHorCursor)
                self.hover_cell.emit({"label": "اسحب لتغيير عرض عمود الأقسام", "row": "اسحب لتغيير ارتفاع الأسطر",
                                      "unit": "اسحب لتغيير عرض هذه الخانة · نقر مزدوج للإرجاع",
                                      "day": "اسحب لتغيير عرض اليوم · نقر مزدوج للإرجاع"}[h[0]])
                return
        if self.resizing:
            self._update_resize(self.mouse)
            self.viewport().update()
            return
        if self.picked is not None:
            self.viewport().setCursor(Qt.ClosedHandCursor)
        elif self.edge_at(self.mouse):
            self.viewport().setCursor(Qt.SizeHorCursor)
        else:
            c, _h = self.card_at(self.mouse)
            self.viewport().setCursor(Qt.PointingHandCursor if c else Qt.ArrowCursor)
        h = self.hit(self.mouse)
        if h != self.hover:
            self.hover = h
            if h and self.picked is not None and h[0] != self.valid_row and self.allowed_row(h[0]):
                self.compute_validity(h[0])
            self.hover_cell.emit(self._hover_text(h))
        self.viewport().update()

    def drag_hover(self, pos: QPoint):
        """سحب من الشريط فوق الجدول: نفس إظهار الخانات المتاحة كتحريك المؤشر."""
        self.mouse = pos
        h = self.hit(pos)
        if h != self.hover:
            self.hover = h
            if h and self.picked is not None and h[0] != self.valid_row and self.allowed_row(h[0]):
                self.compute_validity(h[0])
            self.hover_cell.emit(self._hover_text(h))
        self.viewport().update()

    def drop_at(self, pos: QPoint):
        if self.picked is not None:
            self._drop(pos)

    def _hover_text(self, h) -> str:
        if not h:
            return ""
        if h[1] < 0:
            return f"{self.rows[h[0]][1]} — انقر لتحديد القسم (يُصفّى الشريط السفلي عليه)"
        di = self.days[h[1] // self.nu]
        u = self.row_units(h[0], self.picked)[h[1] % self.nu]
        where = f"{self.rows[h[0]][1]} — {DAY_NAMES[di]} {hm_range(u.start, u.end)}"
        if self.picked is not None and h[0] == self.valid_row:
            ok, msgs = self.validity.get((di, h[1] % self.nu), (False, []))
            return where + ("  — متاح للوضع" if ok else "  — غير متاح: " + " · ".join(msgs[:2]))
        c, _ = self.card_at(self.mouse)
        if c:
            d = self.page.grid.describe(c)
            return f"{d['subject']} — {d['sections_short']} — {d['teacher']} — {d['time']}"
        return where

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.page.zoom(1 if e.angleDelta().y() > 0 else -1)
            return
        if e.modifiers() & Qt.ShiftModifier:
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - e.angleDelta().y())
            return
        super().wheelEvent(e)

    def leaveEvent(self, e):
        self.hover = None
        self.viewport().update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancel_pick()
            return
        if e.key() == Qt.Key_Delete and self.selected is not None:
            self.page.to_tray(self.selected)
            return
        super().keyPressEvent(e)

    def event(self, e):
        if e.type() == e.Type.ToolTip and self.picked is None and not self.resizing:
            c, _h = self.card_at(e.pos())
            if c:
                d = self.page.grid.describe(c)
                g = self.page.grid
                html = (f"<b>{d['subject']}</b> <span style='color:gray'>{CATEGORY_LABELS.get(c.category, '')}"
                        f"{' · مشتركة' if c.shareable else ''}{' · مستوردة' if c.imported else ''}</span><br>"
                        f"{d['sections'] if len(c.sections) <= 2 else d['sections_short']}<br>"
                        f"الأستاذ: {d['teacher']}<br>{d['time']}<br>الحالة: {STATUS_LABELS.get(c.status, c.status)}")
                if c.note:
                    html += f"<br><i>{c.note}</i>"
                for x in g.conflict_by_sid.get(c.sid, [])[:4]:
                    html += f"<br><span style='color:{theme.CURRENT['bad']}'>تعارض: {x.message}</span>"
                if g.ignored_by_sid.get(c.sid):
                    html += "<br><span style='color:gray'>تعارض متجاهَل</span>"
                html += "<br><span style='color:gray'>اسحب طرف البطاقة لتمديدها · الزر الأيمن للخيارات</span>"
                QToolTip.showText(e.globalPos(), html, self)
                return True
        return super().event(e)


# ====================================================================== الشريط السفلي
INFO_ROLE = Qt.UserRole + 1
TRAY_SORTS = [("default", "الترتيب العادي"), ("pct", "الأقل استكمالاً أولاً"), ("remaining", "الأكثر باقياً أولاً"),
              ("alpha", "أبجدي")]


class TrayDelegate(QStyledItemDelegate):
    """رسم بطاقة الشريط: اسم المادة، وتحته سطر أصغر «باقي 24 سا · 40%» للقسم المحدد."""

    def paint(self, p: QPainter, opt, index):
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(opt.rect).adjusted(2, 2, -2, -2)
        bg = index.data(Qt.BackgroundRole)
        fg = index.data(Qt.ForegroundRole)
        bgc = bg.color() if isinstance(bg, QBrush) else QColor("#DDD")
        fgc = fg.color() if isinstance(fg, QBrush) else QColor("#111")
        sel = bool(opt.state & QStyle.State_Selected)
        p.setPen(QPen(QColor(theme.CURRENT["accent"]), 2.4) if sel else QPen(bgc.darker(118), 1))
        p.setBrush(bgc)
        p.drawRoundedRect(r, 6, 6)
        f = index.data(Qt.FontRole) or opt.font
        info_ = index.data(INFO_ROLE)
        p.setPen(fgc)
        tr = r.adjusted(5, 3, -5, -3)
        if info_:
            fi = QFont(f)
            fi.setBold(False)
            fi.setPointSizeF(max(6.5, f.pointSizeF() * 0.82))
            ih = QFontMetrics(fi).height()
            p.setFont(f)
            p.drawText(tr.adjusted(0, 0, 0, -ih), Qt.AlignCenter, index.data(Qt.DisplayRole) or "")
            p.setFont(fi)
            c2 = QColor(fgc)
            c2.setAlphaF(0.85)
            p.setPen(c2)
            p.drawText(QRectF(tr.x(), tr.bottom() - ih, tr.width(), ih), Qt.AlignCenter,
                       QFontMetrics(fi).elidedText(info_, Qt.ElideRight, int(tr.width())))
        else:
            p.setFont(f)
            p.drawText(tr, Qt.AlignCenter, index.data(Qt.DisplayRole) or "")
        p.restore()

    def sizeHint(self, opt, index):
        sh = index.data(Qt.SizeHintRole)
        return sh if isinstance(sh, QSize) else super().sizeHint(opt, index)


def tray_info_text(inf: dict | None) -> str:
    """«باقي 24 سا · 40%» من سطر simple_progress. None = لا قسم محدد؛ {} = مادة بلا مقرر للقسم."""
    if inf is None:
        return ""
    if not inf.get("hours"):
        return "بلا مقرر"
    rem, pct = inf.get("remaining") or 0, inf.get("pct") or 0
    if inf.get("over"):
        return f"تجاوز {inf['done'] - inf['hours']:g} سا · {pct:g}%"
    return f"باقي {rem:g} سا · {pct:g}%"


class TrayList(QListWidget):
    picked = Signal(object)

    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setViewMode(QListWidget.IconMode)
        self.setFlow(QListWidget.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSpacing(4)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setTextElideMode(Qt.ElideRight)
        self.customContextMenuRequested.connect(self._menu)
        self.items: list[TrayItem] = []
        self.info: dict[int, dict] = {}            # مادة → سطر التقدم للقسم المحدد
        self.setItemDelegate(TrayDelegate(self))
        self.viewport().setCursor(Qt.PointingHandCursor)

    def set_items(self, items: list[TrayItem]):
        self.setUpdatesEnabled(False)
        self.clear()
        self.items = items
        w, h = TRAY_SIZES.get(self.page.options["tray_size"], TRAY_SIZES["m"])
        sc = float(self.page.options.get("tray_scale") or 1.0)
        w, h = int(w * sc), int(h * sc)
        self.setGridSize(QSize(w + 6, h + 6))
        g = self.page.grid
        outline = self.page.options["card_style"] == "outline"
        base = QFont(self.font())
        base.setPointSizeF(max(8.0, 9.0 * min(1.4, sc)))
        fi = QFont(base)
        fi.setPointSizeF(max(6.5, base.pointSizeF() * 0.82))
        info_h = QFontMetrics(fi).height()
        for it in items:
            sec = g.sec_by_id.get(it.section) if it.section else None
            cur_sec = self.page.view_grid.selected_section
            inf = (self.info.get(it.subject, {}) if cur_sec and self.info is not None
                   and not (it.full_day or it.key.startswith("q")) and (not it.section or it.section == cur_sec)
                   else None)
            itext = tray_info_text(inf)
            # البطاقة: اسم المادة كاملاً (بلا ساعات ولا أستاذ)؛ يصغر الخط بدل الاختصار، وتحته سطر التقدم
            f, lines = fit_lines(it.sname, base, w - 14, h - 8 - (info_h if itext else 0))
            if it.sid or getattr(it, "pinned", False):
                f.setBold(True)
            li = QListWidgetItem("\n".join(lines))
            li.setFont(f)
            if itext:
                li.setData(INFO_ROLE, itext)
            col = QColor(self.page.view_grid.card_color(it))
            if outline:
                li.setBackground(QBrush(QColor(theme.CURRENT["surface2"])))
                li.setForeground(QBrush(col.lighter(135) if theme.is_dark() else col.darker(185)))
            else:
                li.setBackground(QBrush(col))
                li.setForeground(QBrush(_text_color(col)))
            li.setSizeHint(QSize(w, h))
            li.setTextAlignment(Qt.AlignCenter)
            kind = ("حصة مُزالة من الجدول" if it.sid else
                    "مادة حرة: ارفعها وضعها في أي قسم ثم اختر الأستاذ" if it.free else
                    "من الحجم الساعي المتبقي لهذا الأسبوع")
            tip = (f"{it.sname}\n{sec.name if sec else ''}\n{it.tname or ''}\nالمدة: {it.minutes / 60:g} سا"
                   + (f" · باقي {it.left_hours:g} سا" if it.left_hours is not None else "")
                   + ("\nمثبتة" if getattr(it, "pinned", False) else "") + f"\n{kind}")
            if it.free and it.history:
                tip += f"\nدُرِّست لهذا القسم {it.history} مرة في الأسابيع السابقة"
            if inf and inf.get("hours"):
                tip += (f"\nالمقرر {inf['hours']:g} سا · المنجز والمبرمج حتى نهاية هذا الأسبوع {inf['done']:g} سا"
                        f" ({inf['pct']:g}%) · الباقي {inf['remaining']:g} سا")
            li.setToolTip("\n".join(x for x in tip.split("\n") if x))
            li.setData(Qt.UserRole, it)
            self.addItem(li)
        self.setUpdatesEnabled(True)

    # النقرة: تحمل البطاقة (ثم انقر خانة في الجدول لوضعها). الضغط المتواصل والسحب: إفلات مباشر على الجدول.
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            li = self.itemAt(e.position().toPoint())
            self._press = (e.position().toPoint(), li) if li else None
            if li:
                self.setCurrentItem(li)
                self.picked.emit(li.data(Qt.UserRole))
                return
        super().mousePressEvent(e)

    def _grid_pos(self, gpos):
        gv = self.page.view_grid
        vp = gv.viewport()
        p = vp.mapFromGlobal(gpos)
        return p if vp.rect().contains(p) else None

    def mouseMoveEvent(self, e):
        pr = getattr(self, "_press", None)
        if pr and e.buttons() & Qt.LeftButton:
            gp = self._grid_pos(e.globalPosition().toPoint())
            self.setCursor(Qt.ClosedHandCursor)
            if gp is not None:
                self.page.view_grid.drag_hover(gp)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        pr, self._press = getattr(self, "_press", None), None
        self.unsetCursor()
        if pr and e.button() == Qt.LeftButton:
            gp = self._grid_pos(e.globalPosition().toPoint())
            if gp is not None and (e.position().toPoint() - pr[0]).manhattanLength() > 10:
                self.page.view_grid.drop_at(gp)
            return
        super().mouseReleaseEvent(e)

    def _clicked(self, li):
        self.picked.emit(li.data(Qt.UserRole))

    def _menu(self, pos):
        li = self.itemAt(pos)
        if not li:
            return
        it: TrayItem = li.data(Qt.UserRole)
        m = QMenu(self)
        m.addAction(icon("mdi6.cursor-move"), "رفع ووضع في الجدول", lambda: self.picked.emit(it))
        dm = m.addMenu(icon("mdi6.timer-outline"), "المدة ثم الرفع")
        for mins in DURATIONS:
            a = dm.addAction(duration_label(mins), lambda mins=mins: self._set_minutes(it, mins))
            a.setCheckable(True)
            a.setChecked(it.minutes == mins and not it.full_day and bool(it.sid))
        if it.free:
            dm.addSeparator()
            a = dm.addAction("اليوم كاملاً", lambda: self._set_full(it))
            a.setCheckable(True)
            a.setChecked(it.full_day)
        sec = it.section or it.home or self.page.view_grid.selected_section
        if it.pinned:
            m.addAction(icon("mdi6.pin-off-outline"), "إلغاء التثبيت", lambda: (self.page.unpin(it), self.page._fill_tray()))
        if sec:
            self.page.add_slot_actions(m, it, sec, self.page.grid.suggest_slots(it, sec))
        if it.sid:
            m.addAction(icon("mdi6.delete-outline"), "حذف نهائي", lambda: self.page.delete_session(it.sid))
        m.exec(self.mapToGlobal(pos))


    def _set_minutes(self, it, minutes: int):
        """مدة البطاقة قبل وضعها (ثم تُرفع مباشرة لوضعها، ولا يُسأل عن المدة عند الإفلات)."""
        it.minutes = minutes
        it.full_day = False
        it.dur_chosen = True
        self.picked.emit(it)

    def _set_full(self, it):
        it.full_day = True
        it.minutes = 480
        it.dur_chosen = True
        self.picked.emit(it)


# ====================================================================== اختيار الأستاذ
class TeacherPicker(QDialog):
    """بعد وضع مادة حرة: من درّسها لهذا القسم أولاً، ثم المؤهلون، ثم الجميع، أو «بدون أستاذ»."""

    GROUPS = {"history": "درّسها لهذا القسم سابقاً", "qualified_spec": "مؤهل — نفس الاختصاص",
              "qualified": "مؤهل للمادة", "other": "أساتذة آخرون"}

    def __init__(self, parent, title: str, candidates: list[dict], current: int | None = None, create=None):
        super().__init__(parent)
        self.create = create
        self.setWindowTitle("اختيار الأستاذ")
        self.resize(520, 520)
        self.result_id: int | None = None
        self.chosen = False
        v = QVBoxLayout(self)
        lab = QLabel(title)
        lab.setWordWrap(True)
        lab.setObjectName("SectionTitle")
        v.addWidget(lab)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن أستاذ…")
        v.addWidget(self.search)
        self.only_q = QCheckBox("إظهار المؤهلين ومن درّسها فقط")
        self.only_q.setChecked(any(c["group"] != "other" for c in candidates))
        v.addWidget(self.only_q)
        self.lst = QListWidget()
        v.addWidget(self.lst, 1)
        self.cands = candidates
        self.current = current
        self.search.textChanged.connect(self._fill)
        self.only_q.toggled.connect(self._fill)
        self.lst.itemDoubleClicked.connect(lambda _: self._ok())
        bb = QDialogButtonBox()
        ok = bb.addButton("اختيار", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        self.new_btn = bb.addButton("إضافة أستاذ جديد بهذا الاسم", QDialogButtonBox.ActionRole)
        self.new_btn.setToolTip("يُضاف إلى قائمة الأساتذة ويُعيَّن لهذه المادة ولاختصاص القسم")
        self.new_btn.clicked.connect(self._new)
        self.new_btn.setVisible(False)
        none = bb.addButton("بدون أستاذ (أحدده لاحقاً)", QDialogButtonBox.ActionRole)
        bb.addButton("إلغاء", QDialogButtonBox.RejectRole)
        ok.clicked.connect(self._ok)
        none.clicked.connect(self._none)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self._fill()
        self.search.setFocus()

    def _fill(self):
        self.lst.clear()
        q = self.search.text().strip()
        last = None
        t = theme.CURRENT
        for c in self.cands:
            if q and q not in c["name"]:
                continue
            if self.only_q.isChecked() and not q and c["group"] == "other":
                continue
            if c["group"] != last:
                hdr = QListWidgetItem(self.GROUPS[c["group"]])
                hdr.setFlags(Qt.NoItemFlags)
                f = hdr.font()
                f.setBold(True)
                hdr.setFont(f)
                hdr.setForeground(QBrush(QColor(t["muted"])))
                self.lst.addItem(hdr)
                last = c["group"]
            txt = c["name"]
            if c["uses"]:
                txt += f"   (×{c['uses']})"
            if c["busy"]:
                txt += f"\n      تعارض: {c['busy'][0]} — يمكنك اختياره، وسيُعرض عليك التعارض"
            it = QListWidgetItem(icon("mdi6.account-alert-outline" if c["busy"] else "mdi6.account-check-outline",
                                      t["bad"] if c["busy"] else t["ok"]), txt)
            it.setData(Qt.UserRole, c["id"])
            if c["busy"]:
                it.setToolTip("\n".join(c["busy"][:3]))
            self.lst.addItem(it)
            if c["id"] == self.current:
                self.lst.setCurrentItem(it)
        if self.create:
            self.new_btn.setVisible(bool(q) and not any(q == c["name"] or q == c["name"].split(" ", 1)[-1]
                                                        for c in self.cands))
            self.new_btn.setText(f"إضافة «{q}» أستاذاً جديداً" if q else "إضافة أستاذ جديد")
        if self.lst.currentItem() is None:
            for i in range(self.lst.count()):
                if self.lst.item(i).flags() & Qt.ItemIsSelectable:
                    self.lst.setCurrentRow(i)
                    break

    def _ok(self):
        it = self.lst.currentItem()
        if it and it.data(Qt.UserRole):
            self.result_id = it.data(Qt.UserRole)
            self.chosen = True
            self.accept()

    def _new(self):
        name = " ".join(self.search.text().split())
        if not name or not self.create:
            return
        self.result_id = self.create(name)
        self.chosen = bool(self.result_id)
        if self.chosen:
            self.accept()

    def _none(self):
        self.result_id = None
        self.chosen = True
        self.accept()


# ====================================================================== بطاقة جديدة
class NewCardDialog(QDialog):
    """بطاقة مادة جديدة للشريط: القسم، المادة (موجودة أو جديدة)، المدة، والتثبيت."""

    def __init__(self, page, section_id=None):
        super().__init__(page)
        self.page = page
        self.db = page.ctx.db
        self.setWindowTitle("بطاقة جديدة")
        self.resize(460, 0)
        form = QFormLayout(self)
        self.sec = QComboBox()
        self.sec.addItem("— أي قسم —", None)
        for s in page.grid.sections:
            self.sec.addItem(f"{s.short}", s.id)
        self.sec.setCurrentIndex(max(0, self.sec.findData(section_id)))
        form.addRow("القسم", self.sec)
        self.sub = QComboBox()
        self.sub.setEditable(True)
        self.sub.setInsertPolicy(QComboBox.NoInsert)
        self.sub.lineEdit().setPlaceholderText("اكتب للبحث، أو اكتب اسم مادة جديدة")
        for r in self.db.q("SELECT id, name FROM subjects WHERE COALESCE(kind,'teach')<>'nonteach' ORDER BY name"):
            self.sub.addItem(r["name"], r["id"])
        self.sub.setCurrentIndex(-1)
        from PySide6.QtWidgets import QCompleter
        comp = QCompleter([self.sub.itemText(i) for i in range(self.sub.count())], self)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.sub.setCompleter(comp)
        form.addRow("المادة", self.sub)
        self.cat = QComboBox()
        for k, lab in (("specialty", "اختصاص"), ("military", "عسكرية"), ("general", "عامة")):
            self.cat.addItem(lab, k)
        self.cat_lbl = QLabel("نوع المادة الجديدة")
        form.addRow(self.cat_lbl, self.cat)
        from PySide6.QtWidgets import QDoubleSpinBox
        self.dur = QDoubleSpinBox()
        self.dur.setRange(0.5, 8)
        self.dur.setSingleStep(0.5)
        self.dur.setDecimals(1)
        self.dur.setSuffix(" سا")
        try:
            self.dur.setValue(int(self.db.get_setting("default_minutes", "120") or 120) / 60)
        except ValueError:
            self.dur.setValue(2)
        form.addRow("المدة", self.dur)
        self.full = QCheckBox("يوم كامل (مثل الاختبار والخفارة): بطاقة دائمة في أول الشريط تملأ اليوم")
        self.full.toggled.connect(lambda on: (self.dur.setEnabled(not on), self.pin.setEnabled(not on)))
        form.addRow("", self.full)
        self.pin = QCheckBox("تثبيت في أول الشريط (تبقى حتى توضع في الجدول)")
        self.pin.setChecked(True)
        form.addRow("", self.pin)
        self.sub.currentTextChanged.connect(self._kind)
        bb = QDialogButtonBox()
        ok = bb.addButton("إنشاء البطاقة", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton("إلغاء", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self._kind()

    def _existing(self) -> int | None:
        t = " ".join(self.sub.currentText().split())
        i = self.sub.findText(t)
        return self.sub.itemData(i) if i >= 0 else None

    def _kind(self, *_):
        new = bool(self.sub.currentText().strip()) and self._existing() is None
        self.cat.setVisible(new)
        self.cat_lbl.setVisible(new)

    def _ok(self):
        name = " ".join(self.sub.currentText().split())
        if not name:
            error(self, "اختر المادة أو اكتب اسمها.")
            return
        self.sub_id = self._existing()
        if self.sub_id is None:
            from ...services.structure import CATEGORY_COLORS, is_shared_subject
            from ...utils import make_abbrev
            cat = self.cat.currentData()
            short = make_abbrev(name)
            n = 1
            while self.db.scalar("SELECT 1 FROM subjects WHERE short=?", (short,)):
                n += 1
                short = f"{make_abbrev(name)} {n}"
            with self.db.tx():
                self.sub_id = self.db.execute(
                    "INSERT INTO subjects(name, short, color, shareable, kind, category) VALUES (?,?,?,?,?,?)",
                    (name, short, CATEGORY_COLORS.get(cat, "#CCCCCC"), int(is_shared_subject(name)), "teach", cat))
                self.db.log("إضافة مادة من الجدول العام", "subjects", self.sub_id, {"name": name})
        self.accept()

    def values(self):
        return self.sec.currentData(), getattr(self, "sub_id", None), int(round(self.dur.value() * 60)), \
            self.pin.isChecked() and not self.full.isChecked()


# ====================================================================== خيارات العرض
class DisplayOptions(QDialog):
    def __init__(self, page):
        super().__init__(page)
        self.page = page
        self.setWindowTitle("خيارات العرض")
        o = page.options
        lay = QVBoxLayout(self)
        grid = QGridLayout()
        self.checks = {}
        items = [("show_teacher", "اسم الأستاذ على البطاقة"), ("show_time", "الوقت على البطاقة"),
                 ("show_room", "القاعة على البطاقة"),
                 ("show_nonteach", "الحصص غير الدراسية (الغداء، العطلة، الخفارة…)"),
                 ("show_night", "الفترة الليلية (17:00–00:00)"),
                 ("show_conflicts", "علامة التعارض"), ("show_done_mark", "علامة «منجزة»"),
                 ("level_stripe", "شريط لون الطور على البطاقة"), ("show_tray", "شريط البطاقات"),
                 ("tray_side", "شريط البطاقات على الجانب (بدل الأسفل)"),
                 ("tray_all", "الشريط السفلي: كل الأقسام (وليس القسم المحدد فقط)")]
        for i, (k, lab) in enumerate(items):
            cb = QCheckBox(lab)
            cb.setChecked(bool(o[k]))
            self.checks[k] = cb
            grid.addWidget(cb, i // 2, i % 2)
        lay.addLayout(grid)
        form = QFormLayout()
        self.combos = {}
        for k, lab, opts in (("layout", "شكل الجدول", LAYOUTS),
                             ("card_style", "شكل البطاقة", [("filled", "مملوءة باللون"),
                                                            ("outline", "إطار ملوّن")])):
            cb = QComboBox()
            for v, t in opts:
                cb.addItem(t, v)
            cb.setCurrentIndex(max(0, cb.findData(o[k])))
            self.combos[k] = cb
            form.addRow(lab, cb)
        self.spins = {}
        for k, lab, lo, hi in (("row_h", "ارتفاع الصف", 18, 220), ("col_w", "عرض الحصة (الأساسي)", 30, 300),
                               ("label_w", "عرض عمود الأقسام", 60, 520), ("font_pt", "حجم خط البطاقات", 6, 16),
                               ("grid_line_w", "سمك خطوط الشبكة", 1, 4), ("day_sep_w", "سمك الفاصل بين الأيام", 1, 6)):
            sp = QSpinBox()
            sp.setRange(lo, hi)
            sp.setValue(int(round(float(o[k]))))
            self.spins[k] = sp
            form.addRow(lab, sp)
        lay.addLayout(form)
        tip = QLabel("لتغيير عرض يوم أو حصة بعينها: اسحب حدها في رأس الجدول (نقر مزدوج للإرجاع). "
                     "الزر الأيمن على الرأس لإخفاء حصة أو يوم. اسحب حد عمود الأقسام أو حد سطر لتغيير العرض والارتفاع.")
        tip.setWordWrap(True)
        tip.setObjectName("Muted")
        lay.addWidget(tip)
        lay.addWidget(QLabel("الأيام الظاهرة:"))
        dv = QHBoxLayout()
        self.day_checks = {}
        hd = set(o.get("hidden_days") or [])
        for di in range(7):
            cb = QCheckBox(DAY_NAMES[di])
            cb.setChecked(di not in hd and (di != 5 or o["show_fri"]) and (di != 6 or o["show_sat"]))
            self.day_checks[di] = cb
            dv.addWidget(cb)
        dv.addStretch()
        lay.addLayout(dv)
        rs = QPushButton("إرجاع كل الأحجام (الأيام والحصص والأعمدة)")
        rs.clicked.connect(lambda: (self.page.reset_all_sizes(), self.reject()))
        lay.addWidget(rs)
        lay.addWidget(QLabel("الأطوار الظاهرة:"))
        lv = QHBoxLayout()
        self.levels = {}
        for r in page.ctx.db.q("SELECT id, code, name FROM levels ORDER BY sort, id"):
            cb = QCheckBox(r["code"] or r["name"])
            cb.setToolTip(r["name"])
            cb.setChecked(r["id"] not in o["hidden_levels"])
            self.levels[r["id"]] = cb
            lv.addWidget(cb)
        lv.addStretch()
        lay.addLayout(lv)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        bb.button(QDialogButtonBox.RestoreDefaults).setText("الوضع الافتراضي")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.RestoreDefaults).clicked.connect(self._defaults)
        lay.addWidget(bb)

    def _defaults(self):
        for k, cb in self.checks.items():
            cb.setChecked(bool(DEFAULT_OPTIONS[k]))
        for k, cb in self.combos.items():
            cb.setCurrentIndex(max(0, cb.findData(DEFAULT_OPTIONS[k])))
        for k, sp in self.spins.items():
            sp.setValue(int(round(float(DEFAULT_OPTIONS[k]))))
        for cb in self.levels.values():
            cb.setChecked(True)
        for cb in self.day_checks.values():
            cb.setChecked(True)

    def values(self) -> dict:
        o = dict(self.page.options)
        o.update({k: cb.isChecked() for k, cb in self.checks.items()})
        o.update({k: cb.currentData() for k, cb in self.combos.items()})
        o.update({k: sp.value() for k, sp in self.spins.items()})
        o["hidden_levels"] = [lid for lid, cb in self.levels.items() if not cb.isChecked()]
        o["hidden_days"] = [di for di, cb in self.day_checks.items() if not cb.isChecked()]
        o["show_fri"], o["show_sat"] = True, True
        return o


# ====================================================================== الصفحة
class MasterPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.options = load_options(ctx.db)
        self.view = "sections"
        self._tb_icons: list[tuple] = []
        ws = date.today()
        self.grid = WeekGrid(ctx.db, ws)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        lay.addWidget(self._toolbar())
        lay.addWidget(self._day_bar())
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(7)
        self.view_grid = GridView(self)
        self.split.addWidget(self.view_grid)
        self.split.addWidget(self._tray_panel())
        self.split.setStretchFactor(0, 6)
        self.split.setStretchFactor(1, 1)
        self.split.splitterMoved.connect(self._save_tray_h)
        lay.addWidget(self.split, 1)
        self.hover_lbl = QLabel()
        self.hover_lbl.setObjectName("Muted")
        lay.addWidget(self.hover_lbl)
        self.view_grid.card_selected.connect(self._selected)
        self.view_grid.hover_cell.connect(self.hover_lbl.setText)
        self.view_grid.request_drop.connect(self._drop)
        self.view_grid.request_resize.connect(self._resize)
        self.view_grid.context_card.connect(self._card_menu)
        self.view_grid.section_clicked.connect(lambda s: self._fill_tray())
        self.view_grid.teacher_clicked.connect(self.open_teacher)
        self.tray.picked.connect(self._tray_pick)
        for seq, fn in (("Ctrl+Z", self.undo), ("Ctrl+Y", self.redo), ("Ctrl+Shift+Z", self.redo),
                        ("Esc", self.view_grid.cancel_pick), ("Ctrl+Shift+F", lambda: self.tray_search.setFocus())):
            QShortcut(QKeySequence(seq), self, activated=fn, context=Qt.WidgetWithChildrenShortcut)
        ctx.data_changed.connect(self._data_changed)
        self.set_week(ws)
        self._restore_tray_h()
        from PySide6.QtWidgets import QApplication
        self.apply_ui_style(QApplication.instance().property("ui_style") or "ops")

    # ------------------------------------------------------------------ شريط الأدوات
    def _toolbar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("GridToolbar")
        flow = FlowLayout(bar, spacing=4)
        flow.setContentsMargins(8, 4, 8, 4)

        class _Groups:
            """مجموعات أزرار تنساب على سطرين إذا ضاقت الشاشة (بدل فرض عرض أكبر من الشاشة)."""

            def __init__(self):
                self.new()

            def new(self):
                g = QWidget()
                g.setLayoutDirection(Qt.RightToLeft)
                self.lay = QHBoxLayout(g)
                self.lay.setContentsMargins(0, 0, 0, 0)
                self.lay.setSpacing(4)
                flow.addWidget(g)

            def addWidget(self, w, *a):
                self.lay.addWidget(w, *a)

            def addSpacing(self, n):
                self.lay.addSpacing(n)

            def addStretch(self, *a):
                self.new()

        h = _Groups()

        def sep():
            h.new()
            f = QFrame()
            f.setObjectName("VSep")
            f.setFixedWidth(1)
            f.setMinimumHeight(22)
            h.addWidget(f)
            h.addSpacing(4)

        def tb(ic, tip, fn, text=None):
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setToolTip(tip)
            b.setCursor(Qt.PointingHandCursor)
            if text:
                b.setText(text)
                b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.clicked.connect(fn)
            h.addWidget(b)
            self._tb_icons.append((b, ic))
            return b
        tb("mdi6.chevron-right", "الأسبوع السابق (Ctrl+PgUp)", lambda: self.set_week(self.grid.ws - timedelta(days=7)))
        self.week_cb = QComboBox()
        self.week_cb.setMinimumWidth(230)
        for n in range(1, 56):
            ws = week_of_number(self.ctx.db, n)
            self.week_cb.addItem(f"الأسبوع {n}  ·  {ws.strftime('%d/%m')} – {(ws + timedelta(days=6)).strftime('%d/%m/%Y')}",
                                 iso(ws))
        self.week_cb.activated.connect(lambda _: self.set_week(date.fromisoformat(self.week_cb.currentData())))
        h.addWidget(self.week_cb)
        tb("mdi6.chevron-left", "الأسبوع التالي (Ctrl+PgDown)", lambda: self.set_week(self.grid.ws + timedelta(days=7)))
        tb("mdi6.calendar-today", "الأسبوع الحالي", lambda: self.set_week(date.today()), "اليوم")
        sep()
        self.view_btns = QButtonGroup(self)
        self.view_btn_of = {}
        for k, lab, ic in VIEWS:
            b = QToolButton()
            b.setText(lab)
            b.setIcon(icon(ic))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setCheckable(True)
            b.setObjectName("Pill")
            b.setCursor(Qt.PointingHandCursor)
            b.setChecked(k == self.view)
            b.clicked.connect(lambda _=False, k=k: self.set_view(k))
            self.view_btns.addButton(b)
            self.view_btn_of[k] = b
            self._tb_icons.append((b, ic))
            h.addWidget(b)
        sep()
        lab = QLabel("التلوين")
        lab.setObjectName("Muted")
        h.addWidget(lab)
        self.color_cb = QComboBox()
        for k, lab_ in COLOR_MODES:
            self.color_cb.addItem(lab_, k)
        self.color_cb.activated.connect(self._color_changed)
        h.addWidget(self.color_cb)
        self.layout_btn = tb("mdi6.timeline-clock-outline", "شكل الجدول", self.toggle_layout)
        lm = QMenu(self.layout_btn)
        for k_, lab_ in LAYOUTS:
            lm.addAction(lab_, lambda k_=k_: self.set_layout(k_))
        self.layout_btn.setMenu(lm)
        self.layout_btn.setPopupMode(QToolButton.MenuButtonPopup)
        h.addStretch()
        self.b_conf = tb("mdi6.alert-outline", "قائمة التعارضات النشطة", self.show_conflicts, "التعارضات")
        self.b_conf.setObjectName("ConfBadge")
        sep()
        # التراجع والإعادة: الزر يكتب اسم العملية، والسهم يفتح آخر 20 عملية (اختيار عملية يتراجع حتى هي)
        self.b_undo = tb("mdi6.undo", "تراجع (Ctrl+Z)", self.undo, "تراجع")
        self.b_redo = tb("mdi6.redo", "إعادة (Ctrl+Y)", self.redo, "إعادة")
        for b, which in ((self.b_undo, "undo"), (self.b_redo, "redo")):
            mn = QMenu(b)
            mn.aboutToShow.connect(lambda mn=mn, which=which: self._fill_history(mn, which))
            b.setMenu(mn)
            b.setPopupMode(QToolButton.MenuButtonPopup)
            b.setMaximumWidth(260)
        tb("mdi6.backup-restore", "الرجوع إلى الأصل المستورد لهذا الأسبوع", self.revert_imported)
        sep()
        self.size_btns = {}
        for txt, tip, st in (("−", "تصغير الجدول (Ctrl+-)", -1), ("+", "تكبير الجدول (Ctrl++)", 1)):
            b = QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            b.setMinimumSize(30, 26)
            f = b.font()
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() + 2)
            b.setFont(f)
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _=False, st=st: self.zoom(st))
            h.addWidget(b)
        tb("mdi6.tune-variant", "خيارات العرض", self.display_options, "خيارات العرض")
        tb("mdi6.printer-eye", "طباعة البرنامج بالقالب الرسمي مع المعاينة (Ctrl+P)", self.print_program, "طباعة")
        tb("mdi6.folder-zip-outline", "تصدير الأسبوع كاملاً للحفظ: مجلد فيه Word وPDF لكل قسم وملف يجمع الأقسام",
           self.export_week, "تصدير الأسبوع")
        sep()
        self.gen_btn = QPushButton(icon("mdi6.auto-fix", "white"), "برمجة آلية")
        self.gen_btn.setObjectName("Cta")
        self.gen_btn.setToolTip("برمجة الأسبوع آلياً (Ctrl+G)")
        self.gen_btn.setCursor(Qt.PointingHandCursor)
        self.gen_btn.clicked.connect(lambda: self.ctx.navigate.emit("generate", None))
        h.addWidget(self.gen_btn)
        return bar

    def _day_bar(self) -> QWidget:
        """تبويبات الأيام (الواجهة ج): عرض يوم واحد بخانات واسعة، أو كل الأيام."""
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 0, 4, 0)
        h.setSpacing(4)
        self.day_btns = []
        grp = QButtonGroup(w)
        grp.setExclusive(True)
        for di, lab in [(-1, "الأسبوع كاملاً")] + [(i, DAY_NAMES[i]) for i in range(7)]:
            b = QToolButton()
            b.setObjectName("DayTab")
            b.setText(lab)
            b.setCheckable(True)
            b.setMinimumHeight(34)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, di=di: self.focus_day(di))
            grp.addButton(b)
            h.addWidget(b)
            self.day_btns.append((di, b))
        h.addStretch()
        self.day_bar = w
        return w

    def focus_day(self, di: int):
        self.options["day_focus"] = di
        self._save()
        for d, b in self.day_btns:
            b.setChecked(d == di)
        self.rebuild()

    def apply_ui_style(self, style: str):
        """ترتيب الصفحة حسب الواجهة: ب = الشريط لوحة جانبية، ج = تبويبات الأيام، أ = الشريط في الأسفل."""
        self.ui_style = style
        self.place_tray()
        self.day_bar.setVisible(style == "daily")
        di = int(self.options.get("day_focus", -1) if style == "daily" else -1)
        for d, b in self.day_btns:
            b.setChecked(d == di)
        self.rebuild()

    def place_tray(self):
        """الشريط في الأسفل (قابل للتكبير والتصغير بسحب الحاجز)، أو على الجانب حسب «خيارات العرض»."""
        side = bool(self.options.get("tray_side"))
        self.split.setOrientation(Qt.Horizontal if side else Qt.Vertical)
        self.tray_panel.setVisible(bool(self.options.get("show_tray", True)))
        if side:
            tw = int(self.options.get("tray_w", 340))
            self.split.setSizes([max(400, (self.width() or 1200) - tw), tw])
        else:
            self._restore_tray_h()

    def _tray_panel(self) -> QWidget:
        self.tray_panel = QFrame()
        self.tray_panel.setObjectName("TrayPanel")
        tv = QVBoxLayout(self.tray_panel)
        tv.setContentsMargins(10, 6, 10, 6)
        tv.setSpacing(4)
        top = QHBoxLayout()
        self.tray_title = QLabel()
        self.tray_title.setObjectName("PanelTitle")
        top.addWidget(self.tray_title)
        top.addStretch()
        row2 = QHBoxLayout()
        self.tray_search = QLineEdit()
        self.tray_search.setPlaceholderText("بحث عن مادة…  (Ctrl+Shift+F)")
        self.tray_search.setClearButtonEnabled(True)
        self.tray_search.setMinimumWidth(220)
        self.tray_search.textChanged.connect(lambda _: self._fill_tray())
        row2.addWidget(self.tray_search, 1)
        self.new_card_btn = QPushButton("بطاقة جديدة")
        self.new_card_btn.setIcon(icon("mdi6.card-plus-outline"))
        self.new_card_btn.setToolTip("إنشاء بطاقة مادة (مادة موجودة أو جديدة) وتثبيتها في أول الشريط")
        self.new_card_btn.clicked.connect(lambda: self.new_card())
        top.addWidget(self.new_card_btn)
        self.tray_mode = QComboBox()
        self.tray_mode.setMinimumWidth(0)
        self.tray_mode.addItem("مواد حرة (أي قسم ثم الأستاذ)", "free")
        self.tray_mode.addItem("حسب الحجم الساعي (مرتبطة بالقسم والأستاذ)", "requirements")
        self.tray_mode.setCurrentIndex(max(0, self.tray_mode.findData(self.options["tray_mode"])))
        self.tray_mode.currentIndexChanged.connect(self._tray_opts_changed)
        row2.addWidget(self.tray_mode)
        self.chk_only = QCheckBox("مواد القسم فقط")
        self.chk_only.setToolTip("المواد التي قرأها القسم المحدد أو المقررة له؛ ابحث لإضافة غيرها")
        self.chk_only.setChecked(bool(self.options["tray_only_section"]))
        self.chk_only.toggled.connect(self._tray_opts_changed)
        row2.addWidget(self.chk_only)
        self.chk_hist = QCheckBox("السابقة أولاً")
        self.chk_hist.setToolTip("المواد التي درسها القسم في الأسابيع السابقة تظهر في الأول")
        self.chk_hist.setChecked(bool(self.options["tray_history_first"]))
        self.chk_hist.toggled.connect(self._tray_opts_changed)
        row2.addWidget(self.chk_hist)
        self.tray_sort = QComboBox()
        self.tray_sort.setToolTip("ترتيب البطاقات (المثبّتة والجاهزة تبقى في الأول).\n"
                                  "الاستكمال والباقي للقسم المحدد حتى نهاية الأسبوع المعروض")
        for k_, lab_ in TRAY_SORTS:
            self.tray_sort.addItem(icon("mdi6.sort"), lab_, k_)
        self.tray_sort.setCurrentIndex(max(0, self.tray_sort.findData(self.options.get("tray_sort", "default"))))
        self.tray_sort.currentIndexChanged.connect(self._tray_sort_changed)
        row2.addWidget(self.tray_sort)
        self.tray_size_btns = {}
        for txt, tip, st in (("−", "تصغير بطاقات الشريط", -1), ("+", "تكبير بطاقات الشريط", 1)):
            b = QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            b.setMinimumSize(30, 26)
            f = b.font()
            f.setBold(True)
            f.setPointSizeF(f.pointSizeF() + 2)
            b.setFont(f)
            b.setCursor(Qt.PointingHandCursor)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _=False, st=st: self._tray_zoom(st))
            top.addWidget(b)
        tv.addLayout(top)
        tv.addLayout(row2)
        self.tray = TrayList(self)
        self.tray.setMinimumHeight(48)
        tv.addWidget(self.tray, 1)
        return self.tray_panel

    def _recolor_toolbar(self):
        for b, ic in self._tb_icons:
            b.setIcon(icon(ic))
        self.gen_btn.setIcon(icon("mdi6.auto-fix", "white"))

    # ------------------------------------------------------------------ حالة
    def color_mode(self) -> str:
        return self.options.get(f"color_{self.view}", "subject")

    def _save(self):
        save_options(self.ctx.db, self.options)

    def _color_changed(self):
        self.options[f"color_{self.view}"] = self.color_cb.currentData()
        self._save()
        self.rebuild()

    def set_view(self, view: str):
        self.view = view
        if view in self.view_btn_of:
            self.view_btn_of[view].setChecked(True)
        self.view_grid.cancel_pick()
        self.color_cb.setCurrentIndex(max(0, self.color_cb.findData(self.color_mode())))
        self.rebuild()

    def set_week(self, d):
        self.view_grid.cancel_pick()
        self.grid.set_week(d)
        i = self.week_cb.findData(iso(self.grid.ws))
        if i >= 0:
            self.week_cb.setCurrentIndex(i)
        self.color_cb.setCurrentIndex(max(0, self.color_cb.findData(self.color_mode())))
        self.rebuild()

    def set_size(self, k: str):
        rh, cw, fp = SIZES[k]
        self.options.update({"size": k, "row_h": rh, "col_w": cw, "font_pt": fp})
        self._save()
        self.rebuild()

    def toggle_layout(self):
        keys = [k for k, _ in LAYOUTS]
        cur = self.options["layout"] if self.options["layout"] in keys else "periods"
        self.set_layout(keys[(keys.index(cur) + 1) % len(keys)])

    def hide_unit(self, idx: int):
        hu = self.options.setdefault("hidden_units", {})
        lst = hu.setdefault(self.options["layout"], [])
        if idx not in lst:
            lst.append(idx)
        self._save()
        self.rebuild()

    def hide_day(self, di: int):
        hd = self.options.setdefault("hidden_days", [])
        if di not in hd:
            hd.append(di)
        self._save()
        self.rebuild()

    def show_all_units(self):
        self.options["hidden_units"] = {}
        self.options["hidden_days"] = []
        self.options["show_fri"] = self.options["show_sat"] = True
        self._save()
        self.rebuild()

    def reset_all_sizes(self):
        for k in ("day_w", "unit_w"):
            self.options[k] = {}
        for k in ("label_w", "row_h", "col_w", "font_pt"):
            self.options[k] = DEFAULT_OPTIONS[k]
        self._save()
        self.rebuild()

    def set_layout(self, k: str):
        self.options["layout"] = k
        self._save()
        self.view_grid.cancel_pick()
        self.rebuild()
        self.flash("شكل الجدول: " + dict(LAYOUTS)[k])

    def _tray_opts_changed(self, *_):
        self.options["tray_mode"] = self.tray_mode.currentData()
        self.options["tray_only_section"] = self.chk_only.isChecked()
        self.options["tray_history_first"] = self.chk_hist.isChecked()
        self._save()
        self._fill_tray()

    def _tray_size(self, k):
        self.options["tray_size"] = k
        self.options["tray_scale"] = 1.0
        self._save()
        self._fill_tray()

    def _tray_zoom(self, step: int):
        sc = float(self.options.get("tray_scale") or 1.0)
        self.options["tray_scale"] = round(max(0.6, min(2.2, sc * (1.12 if step > 0 else 1 / 1.12))), 3)
        self._save()
        self._fill_tray()

    def _save_tray_h(self, *_):
        sizes = self.split.sizes()
        if len(sizes) == 2 and sizes[1] > 0:
            self.options["tray_h" if self.split.orientation() == Qt.Vertical else "tray_w"] = sizes[1]
            self._save()

    def _restore_tray_h(self):
        th = max(70, int(self.options.get("tray_h", 190)))
        total = self.split.height() if self.split.height() > 300 else 900
        th = min(th, total - 150)
        self.split.setSizes([max(150, total - th), th])

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_tray_placed", False):      # الأحجام الصحيحة تُعرف بعد ظهور الصفحة
            self._tray_placed = True
            QTimer.singleShot(0, self.place_tray)

    def refresh(self, keep_selection=False):
        sel = self.view_grid.selected.sid if (keep_selection and self.view_grid.selected) else None
        self.grid.reload()
        self.rebuild()
        if sel and sel in self.grid.cards:
            self.view_grid.selected = self.grid.cards[sel]

    def flash(self, msg: str):
        self.ctx.status.emit(msg)
        self.hover_lbl.setText(msg)

    def _units(self) -> list:
        o = self.options
        g = self.grid
        hidden = set((o.get("hidden_units") or {}).get(o["layout"], []))
        if o["layout"] in ("time", "hours"):
            st = 60 if o["layout"] == "hours" else SLOT
            day_ps = [p for prof in g.pm.profiles.values() for p in prof if p.kind == "day"]
            t0 = min((p.start for p in day_ps), default=480)
            t1 = max((p.end for p in day_ps), default=960)
            t0 -= t0 % st
            units = [Unit(k, m, m + st, hm(m)) for k, m in enumerate(range(t0, t1, st))]
            if o["show_night"]:
                night = [p for prof in g.pm.profiles.values() for p in prof if p.kind == "night"]
                if night:
                    n0, n1 = min(p.start for p in night), max(p.end for p in night)
                    n0 -= n0 % st
                    units += [Unit(len(units) + k, m, m + st, hm(m), True)
                              for k, m in enumerate(range(n0, n1, st))]
            return [u for u in units if u.idx not in hidden] or units
        std = g.pm.periods(profile="basic_night" if o["show_night"] else "standard")
        units = [Unit(p.idx, p.start, p.end, "ليل" if p.kind == "night" else str(p.idx), p.kind == "night")
                 for p in std if o["show_night"] or p.kind == "day"]
        return [u for u in units if u.idx not in hidden] or units

    def rebuild(self):
        g, o = self.grid, self.options
        hd = set(o.get("hidden_days") or [])
        days = [d for d in range(7) if d not in hd and (d != 5 or o["show_fri"]) and (d != 6 or o["show_sat"])] \
            or [0, 1, 2, 3, 4]
        if getattr(self, "ui_style", "") == "daily" and int(o.get("day_focus", -1)) >= 0:
            days = [int(o["day_focus"])]
        hidden = set(o["hidden_levels"])

        def keep(c: Card) -> bool:
            return o["show_nonteach"] or c.kind != "nonteach"
        rows, cards = [], []
        if self.view == "sections":
            for s in g.sections:
                if s.level_id in hidden:
                    continue
                rows.append((("s", s.id), s.short, s.level_color, s.level_code))
                cards.append([c for c in g.by_section.get(s.id, []) if keep(c)])
        elif self.view == "teachers":
            for tid, name in g.teachers_rows():
                rows.append((("t", tid), name, "#7F8C8D", ""))
                cards.append([c for c in g.by_teacher.get(tid, []) if keep(c)])
        else:
            for rid, name in g.rooms_rows():
                rows.append((("r", rid), name, "#7F8C8D", ""))
                cards.append([c for c in g.by_room.get(rid, []) if keep(c)])
        self.view_grid.set_data(rows, cards, days, self._units())
        if self.view_grid.selected and self.view_grid.selected.sid not in g.cards:
            self.view_grid.selected = None
        n = len([x for x in g.conflicts if not x.ignored])
        self.b_conf.setText(f"التعارضات ({n})")
        self.b_conf.setProperty("active", "1" if n else "0")
        self.b_conf.style().unpolish(self.b_conf)
        self.b_conf.style().polish(self.b_conf)
        self._recolor_toolbar()
        self.b_conf.setIcon(icon("mdi6.alert-outline", "white" if n else None))
        self.layout_btn.setToolTip("شكل الجدول الحالي: " + dict(LAYOUTS).get(o["layout"], "") + " — انقر للتبديل")
        self.tray_panel.setVisible(o["show_tray"])
        self._update_undo_btns()
        self._fill_tray()

    def _fill_tray(self):
        if not self.options["show_tray"]:
            return
        g = self.grid
        sec = self.view_grid.selected_section
        mode = self.options["tray_mode"]
        secs = None if (self.options["tray_all"] or not sec) else [sec]
        q = self.tray_search.text().strip()
        removed = [it for it in g.tray_items(secs, include_requirements=False) if not q or q in it.sname]
        # الباقي والنسبة للقسم المحدد: المنجز + المبرمج حتى نهاية الأسبوع المعروض (ينقص الباقي كلما وُضعت بطاقة)
        self.tray.info = {}
        if sec and sec in g.sec_by_id:
            from ...services.progress import simple_progress
            try:
                self.tray.info = {r["subject_id"]: r for r in simple_progress(
                    self.ctx.db, [g.sec_by_id[sec].formation_id], g.we, sec, include_planned=True)}
            except Exception:
                self.tray.info = {}
        if mode == "free":
            left = None
            if sec:
                from ...services.progress import section_progress
                fid = g.sec_by_id[sec].formation_id if sec in g.sec_by_id else None
                left = {r["subject_id"]: r["remaining"] for r in section_progress(self.ctx.db, [fid], date.today(), sec)
                        if r["remaining"] is not None} if fid else None
            items = removed + g.subject_items(sec, self.options["tray_only_section"] and bool(sec),
                                              self.options["tray_history_first"], q, left=left)
            self.chk_only.setEnabled(bool(sec))
            self.chk_hist.setEnabled(bool(sec))
        else:
            items = removed + [it for it in g.tray_items(secs) if not it.sid and (not q or q in it.sname)]
            self.chk_only.setEnabled(False)
            self.chk_hist.setEnabled(False)
        pinned = self._pinned_items(sec, q) + self._quick_items(q)
        keys = {(p.subject, p.minutes) for p in pinned}
        quick_subs = {p.subject for p in pinned if p.full_day or p.key.startswith("q")}
        rest = [it for it in items if not (it.free and ((it.subject, it.minutes) in keys or it.subject in quick_subs))]
        items = pinned + self._sorted_tray(rest)
        title = "الشريط السفلي"
        if sec and sec in g.sec_by_id:
            title += f" — {g.sec_by_id[sec].short}"
        else:
            title += " — انقر اسم قسم لتصفية البطاقات عليه"
        self.tray_title.setText(f"{title} · {len(items)} بطاقة")
        self.tray.set_items(items[:800])

    def _sorted_tray(self, items: list) -> list:
        """ترتيب بطاقات الشريط (بعد المثبّتة والجاهزة): العادي، الأقل استكمالاً، الأكثر باقياً، أبجدي.
        المواد بلا مقرر للقسم المحدد تأتي في الآخر عند الترتيب بالنسبة أو الباقي."""
        mode = self.options.get("tray_sort", "default")
        inf = self.tray.info
        if mode == "alpha":
            return sorted(items, key=lambda it: it.sname)
        if mode == "pct":
            return sorted(items, key=lambda it: (not (inf.get(it.subject) or {}).get("hours"),
                                                 (inf.get(it.subject) or {}).get("pct") or 0, it.sname))
        if mode == "remaining":
            return sorted(items, key=lambda it: (not (inf.get(it.subject) or {}).get("hours"),
                                                 -((inf.get(it.subject) or {}).get("remaining") or 0), it.sname))
        return items

    def _tray_sort_changed(self, *_):
        self.options["tray_sort"] = self.tray_sort.currentData()
        self._save()
        self._fill_tray()

    def _quick_items(self, q: str) -> list:
        """بطاقات جاهزة دائمة في أول الشريط: الغداء (ساعة)، وبطاقات «اليوم كاملاً»."""
        from ...services import fullday as FD
        db = self.ctx.db
        out = []
        ids = [("lunch", FD.lunch_subject(db))] + [("full", i) for i in FD.subjects(db)]
        self.fullday_ids = {i for k, i in ids if k == "full"}
        for kind_, sid in ids:
            r = db.one("""SELECT id, name, short, color, COALESCE(category,'specialty') cat, COALESCE(kind,'teach') kind,
                          shareable FROM subjects WHERE id=?""", (sid,))
            if not r or (q and q not in r["name"]):
                continue
            full = kind_ == "full"
            out.append(TrayItem(f"q{kind_}{sid}", None, sid, r["name"], r["short"] or r["name"], r["color"] or "#CCC",
                                r["cat"], None, "", 480 if full else 60, set(), shareable=True, kind=r["kind"],
                                free=True, pinned=True, full_day=full))
        return out

    def _pinned_items(self, sec, q: str) -> list:
        g = self.grid
        out = []
        subs = {r["id"]: r for r in self.ctx.db.q("""SELECT id, name, short, color, COALESCE(category,'specialty') cat,
                                                     COALESCE(kind,'teach') kind, shareable FROM subjects""")}
        for home, sub, minutes in self.pins():
            r = subs.get(sub)
            if not r or (q and q not in r["name"]):
                continue
            if home and not self.options["tray_all"] and sec and home != sec:
                continue
            out.append(TrayItem(f"p{home}-{sub}-{minutes}", None, sub, r["name"], r["short"] or r["name"],
                                r["color"] or "#CCC", r["cat"], None, "", int(minutes), set(),
                                shareable=bool(r["shareable"]), kind=r["kind"], free=True, pinned=True,
                                home=home or None))
        return out

    def new_card(self):
        dlg = NewCardDialog(self, self.view_grid.selected_section)
        if dlg.exec() != QDialog.Accepted:
            return
        sec, sub, minutes, pin = dlg.values()
        if not sub:
            return
        if dlg.full.isChecked():
            from ...services import fullday as FD
            FD.add(self.ctx.db, sub)
            self._fill_tray()
            self.flash("أُضيفت بطاقة «يوم كامل» دائمة في أول الشريط.")
            return
        if pin:
            pins = self.pins()
            key = [sec or 0, sub, minutes]
            if key not in pins:
                pins.insert(0, key)
                self.ctx.db.set_setting("tray_pins", json.dumps(pins))
        if sec:
            self.view_grid.selected_section = sec
        self._fill_tray()
        if not pin:
            r = self.ctx.db.one("SELECT id, name, short, color, COALESCE(category,'specialty') cat, "
                                "COALESCE(kind,'teach') kind, shareable FROM subjects WHERE id=?", (sub,))
            it = TrayItem(f"n{sub}", None, sub, r["name"], r["short"] or r["name"], r["color"] or "#CCC", r["cat"],
                          None, "", minutes, set(), shareable=bool(r["shareable"]), kind=r["kind"], free=True,
                          home=sec)
            self._tray_pick(it)
        self.flash("أُنشئت البطاقة" + (" وثُبّتت في أول الشريط." if pin else " — انقر خانة لوضعها."))

    def _selected(self, c):
        if not self.options["tray_all"] and self.view == "sections":
            self._fill_tray()

    def _data_changed(self, w):
        if w == "grid_options":
            self.options = load_options(self.ctx.db)
            self.rebuild()
        elif w in ("*", "sessions", "sections", "subjects", "curriculum", "absences"):
            self.refresh()

    def open_teacher(self, tid: int):
        from ..teacher_profile import open_profile
        open_profile(self.ctx, tid, self, self.grid.ws)

    def _leave_for(self, tid: int):
        from ..teacher_profile import add_leave
        if add_leave(self.ctx, self, tid):
            self.refresh()

    def print_target(self):
        gv = self.view_grid
        if self.view == "teachers" and gv.selected is not None and gv.selected.teacher:
            return "teacher", gv.selected.teacher
        if self.view == "rooms" and gv.selected is not None and gv.selected.room:
            return "room", gv.selected.room
        if gv.selected_section:
            return "section", gv.selected_section
        return "all_sections", None

    def export_week(self):
        from ..word_ui import export_week_dialog
        export_week_dialog(self, self.ctx, self.grid.ws)

    def print_program(self):
        from ..sheet_view import open_print
        k, t = self.print_target()
        open_print(self.ctx, self.grid.ws, self, k, t)

    def focus_section(self, sec_id: int):
        if self.view != "sections":
            self.set_view("sections")
        gv = self.view_grid
        gv.selected_section = sec_id
        ri = gv._row_of_section(sec_id)
        if ri is not None:
            gv.verticalScrollBar().setValue(max(0, ri * gv.RH() - gv.viewport().height() // 3))
        gv.viewport().update()
        self._fill_tray()

    def zoom(self, step: int):
        """تكبير/تصغير الجدول كاملاً: البطاقات والخط وعرض الأعمدة معاً."""
        o = self.options
        f = 1.1 if step > 0 else 1 / 1.1
        cw = max(30, min(260, round(float(o["col_w"]) * f)))
        if cw == int(o["col_w"]):
            return
        o["col_w"] = cw
        o["row_h"] = max(22, min(150, round(float(o["row_h"]) * f)))
        o["font_pt"] = round(max(6.0, min(15.0, float(o["font_pt"]) * f)), 2)
        o["label_w"] = max(90, min(420, round(float(o.get("label_w", 184)) * (f ** 0.5))))
        o["size"] = ""
        self._save()
        self.rebuild()

    def display_options(self):
        d = DisplayOptions(self)
        if d.exec() == QDialog.Accepted:
            self.options = d.values()
            self.options["size"] = next((k for k, (rh, cw, _f) in SIZES.items()
                                         if rh == self.options["row_h"] and cw == self.options["col_w"]), "")
            self._save()
            self.rebuild()
            self.place_tray()

    # ------------------------------------------------------------------ عمليات
    def _tray_pick(self, item: TrayItem):
        self.view_grid.selected = None
        self.view_grid.pick(item)
        self.flash(f"«{item.sname}» مرفوعة — انقر خانة لوضعها" + (" في أي قسم" if item.free else "") + " · Esc للإلغاء")

    def sound(self, kind: str):
        from .. import sounds
        sounds.play(kind, self.ctx.db)

    def _confirm_conflicts(self, msgs: list[str]) -> tuple[bool, bool]:
        """(نتابع؟، نتجاهل التعارض؟)"""
        if not msgs:
            return True, False
        self.sound("conflict")
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("تعارض")
        box.setText("يوجد تعارض في هذا الوقت:\n\n• " + "\n• ".join(msgs[:6]))
        b_ign = box.addButton("وضع وتجاهل التعارض", QMessageBox.AcceptRole)
        b_keep = box.addButton("وضع وإظهار التعارض", QMessageBox.ActionRole)
        box.addButton("إلغاء", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() not in (b_ign, b_keep):
            return False, False
        return True, box.clickedButton() is b_ign

    def _after_place(self, sid: int, ignore: bool, d, s, e):
        self.sound("ok")
        if ignore:
            CF.ignore(self.ctx.db, [x.key for x in self.grid.conflict_by_sid.get(sid, [])], "تجاهل عند الوضع")
            self.grid.refresh_conflicts()
        self.view_grid.picked = None
        self.view_grid.validity = {}
        self.rebuild()
        if sid in self.grid.cards:
            self.view_grid.selected = self.grid.cards[sid]
        self.flash(f"تم: {DAY_NAMES[(d.weekday() + 1) % 7]} {d.strftime('%d/%m')} {hm_range(s, e)}")
        self.ctx.changed("sessions_grid")

    def add_slot_actions(self, m: QMenu, item, sec, slots: list[dict]):
        """يضيف إلى القائمة أقرب الأوقات المتاحة؛ اختيار وقت يضع الحصة فيه مباشرة."""
        m.addSeparator()
        if not sec:
            a = m.addAction("انقر اسم قسم في الجدول لترى أقرب الأوقات المتاحة له")
            a.setEnabled(False)
            return
        name = self.grid.sec_by_id[sec].short if sec in self.grid.sec_by_id else ""
        hdr = m.addAction(f"أقرب الأوقات المتاحة — {name}")
        hdr.setEnabled(False)
        if not slots:
            a = m.addAction("لا يوجد وقت متاح هذا الأسبوع (القسم أو الأستاذ مشغول)")
            a.setEnabled(False)
            return
        for sl in slots:
            m.addAction(icon("mdi6.clock-check-outline", theme.CURRENT["ok"]), sl["label"],
                        lambda sl=sl: self.place_at(item, sec, sl["day"], sl["start"], sl["end"], sl["teacher"]))

    def place_at(self, item, sec, d, s, e, teacher=None):
        """وضع بطاقة أو نقل حصة إلى وقت محدد (من اقتراحات الوقت)."""
        g = self.grid
        try:
            if isinstance(item, Card):
                msgs = g.check_card(item, d, s, e)
                ok, ign = self._confirm_conflicts(msgs)
                if not ok:
                    return
                g.move(item, d, s, e)
                sid = item.sid
            elif item.free:
                sid, ign = self._place_free(item, sec, d, s, e, preselect=teacher)
                if sid is None:
                    return
            else:
                msgs = g.check_tray(item, d, s, e)
                ok, ign = self._confirm_conflicts(msgs)
                if not ok:
                    return
                sid = g.place(item, d, s, e)
        except GridError as ex:
            error(self, str(ex))
            return
        self._after_place(sid, ign, d, s, e)

    def _place_free(self, item, sec, d, s, e, preselect=None):
        """مادة حرة: فحص القسم ← نافذة اختيار الأستاذ ← فحص الأستاذ ← الوضع. يعيد (sid أو None، تجاهل؟)."""
        g = self.grid
        msgs = g.check_free(item, sec, d, s, e)
        ok, ign = self._confirm_conflicts(msgs)
        if not ok:
            return None, False
        secname = g.sec_by_id[sec].short
        cands = g.teacher_candidates(sec, item.subject, d, s, e)
        di = (d - g.ws).days
        tp = TeacherPicker(self, f"{item.sname} — {secname}\n{DAY_NAMES[di]} {hm_range(s, e)}", cands,
                           current=preselect,
                           create=lambda name, sub=item.subject, sec=sec: g.create_teacher(name, sub, sec))
        if tp.exec() != QDialog.Accepted or not tp.chosen:
            return None, False
        if tp.result_id:
            tmsgs = g.check(sections=[], groups=set(), teacher=tp.result_id, room=None, subject=item.subject,
                            shareable=item.shareable, kind=item.kind, day=d, start=s, end=e)
            if tmsgs:
                ok2, ign2 = self._confirm_conflicts(tmsgs)
                if not ok2:
                    return None, False
                ign = ign or ign2
        sid = g.place_free(item, sec, tp.result_id, d, s, e)
        self.unpin(item)
        self.view_grid.selected_section = sec
        return sid, ign

    def unpin(self, item):
        pins = self.pins()
        key = [item.home or 0, item.subject, item.minutes]
        if key in pins:
            pins.remove(key)
            self.ctx.db.set_setting("tray_pins", json.dumps(pins))

    def pins(self) -> list:
        try:
            return [list(x) for x in json.loads(self.ctx.db.get_setting("tray_pins", "[]") or "[]")]
        except Exception:
            return []

    def ask_duration(self, item) -> int | str | None:
        """قائمة المدة عند وضع بطاقة من الشريط: 30 دقيقة … 4 ساعات، أو اليوم كاملاً. None = إلغاء."""
        from PySide6.QtGui import QCursor
        mn = QMenu(self)
        hdr = mn.addAction(f"مدة «{item.sname}»")
        hdr.setEnabled(False)
        mn.addSeparator()
        acts = {}
        default = None
        for mins in DURATIONS:
            a = mn.addAction(icon("mdi6.timer-outline"), duration_label(mins))
            acts[a] = mins
            if mins == item.minutes:
                default = a
        if item.free:
            mn.addSeparator()
            acts[mn.addAction(icon("mdi6.calendar-today"), "اليوم كاملاً")] = "full"
        if default is not None:
            mn.setActiveAction(default)
        a = mn.exec(QCursor.pos(), default)
        return acts.get(a)

    def _refine_start(self, item, ri: int, prop):
        """بطاقة أقصر من خانتها: تبدأ حيث أُفلتت (بخطوة 30 د) وتُرسم بحجمها الحقيقي."""
        gv = self.view_grid
        d, s, e = prop
        x = getattr(gv, "last_drop_x", None)
        if x is None:
            return prop
        m = gv.x_minute_raw(ri, x, item)
        units = gv.row_units(ri, item)
        u = next((u for u in units if u.start <= s < u.end), None)
        if m is None or u is None or item.minutes >= u.end - u.start:
            return prop
        start = u.start + int(max(0, m - u.start) // 30) * 30
        start = max(u.start, min(start, u.end - item.minutes))
        return d, start, start + item.minutes

    def _drop(self, item, ri, di, k):
        gv = self.view_grid
        if isinstance(item, TrayItem) and not item.full_day and not item.key.startswith("qlunch") \
                and not getattr(item, "dur_chosen", False) and self.options.get("ask_duration", True):
            if not gv.allowed_row(ri):
                return
            ch = self.ask_duration(item)
            if ch is None:
                self.flash("أُلغي الوضع — البطاقة ما زالت مرفوعة (Esc للإلغاء).")
                return
            if ch == "full":
                item.full_day, item.minutes = True, 480
            else:
                item.minutes = int(ch)
            item.dur_chosen = True
            try:
                return self._drop(item, ri, di, k)
            finally:
                item.dur_chosen = False
        if isinstance(item, TrayItem) and item.full_day:
            sec = gv.row_section(ri)
            if sec is None:
                self.flash("ضع بطاقة «اليوم كاملاً» في صف قسم.")
                return
            self.place_full_day(item, sec, self.grid.ws + timedelta(days=di))
            return
        if isinstance(item, TrayItem) and item.key.startswith("qlunch"):
            prop = gv.proposal(ri, di, k)
            sec = gv.row_section(ri)
            if prop is None or sec is None:
                self.flash("لا تتسع الحصة في هذا الوقت.")
                return
            d, s, e = prop
            try:
                msgs = self.grid.check_free(item, sec, d, s, e)
                ok, ign = self._confirm_conflicts(msgs)
                if not ok:
                    return
                sid = self.grid.place_free(item, sec, None, d, s, e)
            except GridError as ex:
                error(self, str(ex))
                return
            self._after_place(sid, ign, d, s, e)
            return
        prop = gv.proposal(ri, di, k)
        if prop is None:
            self.flash("لا تتسع الحصة في هذا الوقت (تتجاوز نهاية اليوم).")
            return
        prop = self._refine_start(item, ri, prop)
        d, s, e = prop
        g = self.grid
        try:
            if isinstance(item, TrayItem) and item.free:
                sec = gv.row_section(ri)
                sid, ign = self._place_free(item, sec, d, s, e)
                if sid is None:
                    return
                self._after_place(sid, ign, d, s, e)
                return
            else:
                msgs = g.check_card(item, d, s, e) if isinstance(item, Card) else g.check_tray(item, d, s, e)
                ok, ign = self._confirm_conflicts(msgs)
                if not ok:
                    return
                if isinstance(item, Card):
                    g.move(item, d, s, e)
                    sid = item.sid
                else:
                    sid = g.place(item, d, s, e)
        except GridError as ex:
            error(self, str(ex))
            return
        self._after_place(sid, ign, d, s, e)

    def _resize(self, card: Card, start: int, end: int):
        msgs = self.grid.check_card(card, card.day, start, end)
        ok, ign = self._confirm_conflicts(msgs)
        if not ok:
            self.view_grid.viewport().update()
            return
        try:
            self.grid.resize(card, start, end)
        except GridError as ex:
            error(self, str(ex))
            return
        self._after_place(card.sid, ign, card.day, start, end)

    def _clear_day(self, sec: int, d, exclude_sid=None) -> bool | None:
        """يسأل قبل إرجاع حصص اليوم إلى الشريط. يعيد None عند الإلغاء."""
        g = self.grid
        busy = g.day_cards(sec, d, exclude_sid)
        if not busy:
            return True
        names = "\n• ".join(f"{c.sname} {hm_range(c.start, c.end)}" for c in busy[:10])
        if not confirm(self, f"في يوم {DAY_NAMES[(d.weekday() + 1) % 7]} {d.strftime('%d/%m')} للقسم "
                             f"{g.sec_by_id[sec].short} {len(busy)} حصة:\n\n• {names}\n\n"
                             "إرجاعها إلى الشريط ووضع «اليوم كاملاً»؟ (Ctrl+Z للتراجع)"):
            return None
        for c in busy:
            g.to_tray(c)
        return True

    def place_full_day(self, item, sec: int, d):
        """وضع بطاقة «اليوم كاملاً» (اختبار، خفارة، خدمة…) من بداية يوم القسم إلى نهايته، مع الغداء."""
        g = self.grid
        s, e = g.full_day_range(sec)
        ev = g.day_events.get((sec, d))
        if ev and not confirm(self, f"هذا اليوم فيه حدث: {ev[0][0]}. المتابعة؟"):
            return
        g.begin_group()
        try:
            if self._clear_day(sec, d) is None:
                g.end_group("اليوم كاملاً")
                return
            sid = g.place_free(item, sec, None, d, s, e)
        except GridError as ex:
            g.end_group("اليوم كاملاً")
            error(self, str(ex))
            return
        g.end_group(f"اليوم كاملاً: {item.sname}")
        self._after_place(sid, False, d, s, e)

    def set_full_day(self, c: Card):
        g = self.grid
        sec = c.sections[0] if c.sections else None
        if sec is None:
            return
        s, e = g.full_day_range(sec)
        g.begin_group()
        try:
            if self._clear_day(sec, c.day, c.sid) is None:
                g.end_group("اليوم كاملاً")
                return
            g.move(c, c.day, s, e, label="اليوم كاملاً")
        except GridError as ex:
            g.end_group("اليوم كاملاً")
            error(self, str(ex))
            return
        g.end_group(f"اليوم كاملاً: {c.sname}")
        self._after_place(c.sid, False, c.day, s, e)

    def set_duration(self, c: Card, minutes: int):
        """مدة الحصة من بدايتها: تمتد على الحصص التالية فقط إذا كانت فارغة، وإلا يُرفض مع ذكر السبب."""
        if c.end - c.start == minutes:
            return
        g = self.grid
        sec = c.sections[0] if c.sections else None
        end = c.start + minutes
        limit = g.day_limit(sec, c.start) if sec else 24 * 60
        if end > limit:
            error(self, f"لا يمكن جعل «{c.sname}» {duration_label(minutes)}: تتجاوز نهاية اليوم ({hm(limit)}).", "المدة")
            return
        msgs = g.check_card(c, c.day, c.start, end)
        if msgs:
            self.sound("conflict")
            error(self, f"لا يمكن جعل «{c.sname}» {duration_label(minutes)} ({hm_range(c.start, end)}):\n\n• "
                  + "\n• ".join(msgs[:6]), "المدة")
            return
        try:
            g.resize(c, c.start, end)
        except GridError as ex:
            error(self, str(ex))
            return
        self._after_place(c.sid, False, c.day, c.start, end)

    def change_teacher(self, c: Card):
        sec = c.sections[0] if c.sections else None
        if sec is None:
            return
        cands = self.grid.teacher_candidates(sec, c.subject, c.day, c.start, c.end)
        cands = [dict(x, busy=[m for m in x["busy"] if c.sname not in m]) if x["id"] == c.teacher else x
                 for x in cands]
        tp = TeacherPicker(self, f"{c.sname} — {self.grid.describe(c)['sections_short']}\n{self.grid.describe(c)['time']}",
                           cands, c.teacher,
                           create=lambda name, sub=c.subject, sec=sec: self.grid.create_teacher(name, sub, sec))
        if tp.exec() == QDialog.Accepted and tp.chosen:
            try:
                self.grid.set_teacher(c, tp.result_id)
            except GridError as ex:
                error(self, str(ex))
                return
            self.rebuild()
            self.ctx.changed("sessions_grid")

    def to_tray(self, c: Card):
        try:
            self.grid.to_tray(c)
        except GridError as ex:
            error(self, str(ex))
            return
        self.view_grid.selected = None
        self.view_grid.cancel_pick()
        self.rebuild()
        self.flash("أُعيدت البطاقة إلى الشريط السفلي (Ctrl+Z للتراجع).")

    def set_status(self, c: Card, status: str):
        self.grid.set_status(c, status)
        self.refresh(keep_selection=True)

    def delete_session(self, sid: int):
        if confirm(self, "حذف هذه الحصة نهائياً؟ (يمكن التراجع بـ Ctrl+Z)", danger=True):
            self.grid.delete(sid)
            self.rebuild()

    def undo(self):
        self.view_grid.cancel_pick()
        lab = self.grid.undo()
        self.rebuild()
        self.flash(f"تراجع: {lab}" if lab else "لا يوجد ما يُتراجع عنه.")
        if lab:
            self.ctx.changed("sessions_grid")

    def redo(self):
        lab = self.grid.redo()
        self.rebuild()
        self.flash(f"إعادة: {lab}" if lab else "لا يوجد ما يُعاد.")
        if lab:
            self.ctx.changed("sessions_grid")

    def _fill_history(self, mn: QMenu, which: str):
        mn.clear()
        ops = self.grid.history(which, 20)
        if not ops:
            a = mn.addAction("لا توجد عمليات" if which == "undo" else "لا يوجد ما يُعاد")
            a.setEnabled(False)
            return
        hdr = mn.addAction("اختر عملية: يُتراجع عنها وعن كل ما بعدها" if which == "undo"
                           else "اختر عملية: تُعاد هي وكل ما قبلها")
        hdr.setEnabled(False)
        mn.addSeparator()
        for i, t in enumerate(ops):
            mn.addAction(f"{i + 1}. {t}", lambda n=i + 1, w=which: self._history_jump(w, n))

    def _history_jump(self, which: str, n: int):
        self.view_grid.cancel_pick()
        k = self.grid.undo_many(n) if which == "undo" else self.grid.redo_many(n)
        self.rebuild()
        self.flash(f"{'تراجع عن' if which == 'undo' else 'إعادة'} {k} عملية")
        if k:
            self.ctx.changed("sessions_grid")

    def _update_undo_btns(self):
        if not hasattr(self, "b_undo"):
            return
        for b, which, base, key in ((self.b_undo, "undo", "تراجع", "Ctrl+Z"), (self.b_redo, "redo", "إعادة", "Ctrl+Y")):
            ops = self.grid.history(which, 1)
            txt = f"{base}: {ops[0]}" if ops else base
            fm = b.fontMetrics()
            b.setText(fm.elidedText(txt, Qt.ElideRight, 200))
            b.setToolTip(f"{txt} ({key})" if ops else f"لا يوجد ما {'يُتراجع عنه' if which == 'undo' else 'يُعاد'}")
            b.setEnabled(True)

    def revert_imported(self):
        if not self.grid.imported_snapshots():
            info(self, "هذا الأسبوع ليس مستورداً من aSc؛ لا يوجد أصل للرجوع إليه.")
            return
        if confirm(self, "الرجوع إلى النسخة المستوردة الأصلية لهذا الأسبوع؟\nتُحفظ نسخة من الوضع الحالي قبل الرجوع.",
                   danger=True):
            try:
                n = self.grid.revert_to_imported()
            except Exception as ex:
                error(self, str(ex))
                return
            self.rebuild()
            self.flash(f"تمت الاستعادة ({n} جدول).")

    def _ignore(self, c: Card):
        CF.ignore(self.ctx.db, [x.key for x in self.grid.conflict_by_sid.get(c.sid, [])], "تجاهل يدوي من الجدول العام")
        self.refresh(keep_selection=True)

    def _unignore(self, c: Card):
        CF.unignore(self.ctx.db, [x.key for x in self.grid.ignored_by_sid.get(c.sid, [])])
        self.refresh(keep_selection=True)

    def _details(self, c: Card):
        d = self.grid.describe(c)
        conf = self.grid.conflict_by_sid.get(c.sid, [])
        txt = (f"المادة: {d['subject']} ({CATEGORY_LABELS.get(c.category, '')})\nالقسم: {d['sections']}\n"
               f"الأستاذ: {d['teacher']}\nالقاعة: {d['room']}\nالوقت: {d['time']}\n"
               f"الحالة: {STATUS_LABELS.get(c.status, c.status)}" + (f"\nملاحظة: {c.note}" if c.note else ""))
        if conf:
            txt += "\n\nالتعارضات:\n• " + "\n• ".join(x.message for x in conf)
        info(self, txt, "تفاصيل الحصة")

    def _card_menu(self, c: Card, gpos):
        self.view_grid.viewport().update()
        m = QMenu(self)
        m.addAction(icon("mdi6.information-outline"), "تفاصيل الحصة", lambda: self._details(c))
        m.addAction(icon("mdi6.cursor-move"), "رفع ونقل", lambda: self.view_grid.pick(c))
        sec0 = c.sections[0] if c.sections else None
        if sec0:
            qm = m.addMenu(icon("mdi6.clock-fast"), "نقل سريع إلى وقت متاح")
            self.add_slot_actions(qm, c, sec0, self.grid.suggest_slots(c, sec0, limit=8))
        dm = m.addMenu(icon("mdi6.timer-outline"), f"المدة ({duration_label(c.end - c.start)})")
        for mins in DURATIONS:
            a = dm.addAction(duration_label(mins), lambda mins=mins: self.set_duration(c, mins))
            a.setCheckable(True)
            a.setChecked(c.end - c.start == mins)
        dm.addSeparator()
        sec_ = c.sections[0] if c.sections else None
        a = dm.addAction("اليوم كاملاً", lambda: self.set_full_day(c))
        a.setCheckable(True)
        a.setChecked(bool(sec_) and (c.start, c.end) == self.grid.full_day_range(sec_))
        m.addAction(icon("mdi6.account-switch-outline"), "تغيير الأستاذ…", lambda: self.change_teacher(c))
        if c.teacher:
            m.addAction(icon("mdi6.card-account-details-outline"), f"ملف الأستاذ: {c.tname}",
                        lambda: self.open_teacher(c.teacher))
            m.addAction(icon("mdi6.calendar-remove-outline"), "تسجيل إجازة للأستاذ واختيار المعوّض…",
                        lambda: self._leave_for(c.teacher))
        m.addAction(icon("mdi6.tray-arrow-down"), "إزالة إلى الشريط (Delete)", lambda: self.to_tray(c))
        sm = m.addMenu(icon("mdi6.list-status"), "الحالة")
        for k in ("planned", "done", "postponed", "cancelled"):
            a = sm.addAction(STATUS_LABELS[k], lambda k=k: self.set_status(c, k))
            a.setCheckable(True)
            a.setChecked(c.status == k)
        if self.grid.conflict_by_sid.get(c.sid):
            m.addSeparator()
            m.addAction(icon("mdi6.eye-off-outline"), "تجاهل تعارضات هذه الحصة", lambda: self._ignore(c))
            m.addAction(icon("mdi6.wrench-outline"), "إصلاح التعارض (نقل الحصة)", lambda: self.view_grid.pick(c))
        if self.grid.ignored_by_sid.get(c.sid):
            m.addAction(icon("mdi6.eye-outline"), "إلغاء تجاهل التعارض", lambda: self._unignore(c))
        m.addSeparator()
        m.addAction(icon("mdi6.delete-outline"), "حذف نهائي", lambda: self.delete_session(c.sid))
        m.exec(gpos)

    def show_conflicts(self):
        items = [x for x in self.grid.conflicts if not x.ignored]
        d = QDialog(self)
        d.setWindowTitle(f"التعارضات النشطة — {len(items)}")
        d.resize(720, 420)
        v = QVBoxLayout(d)
        if not items:
            v.addWidget(QLabel("لا توجد تعارضات نشطة في هذا الأسبوع."))
        lst = QListWidget()
        lst.setSelectionMode(QListWidget.ExtendedSelection)
        kinds = {"teacher": "أستاذ", "group": "قسم", "room": "قاعة"}
        for x in items:
            dd = date.fromisoformat(x.date)
            li = QListWidgetItem(f"[{kinds[x.kind]}] {DAY_NAMES[(dd.weekday() + 1) % 7]} {dd.strftime('%d/%m')} — {x.message}")
            li.setData(Qt.UserRole, x)
            lst.addItem(li)
        v.addWidget(lst)
        h = QHBoxLayout()
        b_go = QPushButton(icon("mdi6.target"), "الانتقال إلى الحصة")
        b_ign = QPushButton(icon("mdi6.eye-off-outline"), "تجاهل المحدد")
        b_all = QPushButton("تجاهل الكل")
        b_close = QPushButton("إغلاق")
        for b in (b_go, b_ign, b_all):
            h.addWidget(b)
        h.addStretch()
        h.addWidget(b_close)
        v.addLayout(h)

        def go():
            it = lst.currentItem()
            if it:
                x = it.data(Qt.UserRole)
                c = self.grid.cards.get(x.session_ids[0])
                if c:
                    self.view_grid.selected = c
                    self._scroll_to(c)
                d.accept()

        def ign(all_=False):
            sel = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())] if all_ else \
                [i.data(Qt.UserRole) for i in lst.selectedItems()]
            if all_ and not confirm(self, f"تجاهل كل التعارضات ({len(sel)})؟"):
                return
            CF.ignore(self.ctx.db, [x.key for x in sel], "تجاهل من قائمة التعارضات")
            d.accept()
            self.refresh()
        b_go.clicked.connect(go)
        lst.itemDoubleClicked.connect(lambda _: go())
        b_ign.clicked.connect(lambda: ign(False))
        b_all.clicked.connect(lambda: ign(True))
        b_close.clicked.connect(d.reject)
        d.exec()

    def _scroll_to(self, c: Card):
        gv = self.view_grid
        for ri, (key, *_r) in enumerate(gv.rows):
            if (key[0] == "s" and key[1] in c.sections) or (key[0] == "t" and key[1] == c.teacher):
                gv.verticalScrollBar().setValue(max(0, ri * gv.RH() - gv.viewport().height() // 3))
                break
        gv.viewport().update()
