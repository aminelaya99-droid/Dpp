"""عناصر واجهة مشتركة: بطاقات، مخططات، رسائل، نوافذ نماذج، أيقونات."""
from __future__ import annotations

from PySide6.QtCore import QDate, QEvent, QRectF, Qt, QTime, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton,
                               QSizePolicy, QSpinBox, QTimeEdit, QVBoxLayout, QWidget)

from . import theme

try:
    import qtawesome as qta
except Exception:  # pragma: no cover
    qta = None


def icon(name: str, color: str | None = None):
    from PySide6.QtGui import QIcon
    if qta is None:
        return QIcon()
    try:
        return qta.icon(name, color=color or theme.CURRENT["text"])
    except Exception:
        return QIcon()


# ------------------------------------------------------------------ رسائل
def info(parent, text: str, title: str = "DPP"):
    QMessageBox.information(parent, title, text)


def error(parent, text: str, title: str = "خطأ"):
    QMessageBox.critical(parent, title, text)


def warn(parent, text: str, title: str = "تنبيه"):
    QMessageBox.warning(parent, title, text)


def confirm(parent, text: str, title: str = "تأكيد", danger=False) -> bool:
    box = QMessageBox(QMessageBox.Warning if danger else QMessageBox.Question, title, text,
                      QMessageBox.Yes | QMessageBox.No, parent)
    box.button(QMessageBox.Yes).setText("نعم")
    box.button(QMessageBox.No).setText("لا")
    box.setDefaultButton(QMessageBox.No if danger else QMessageBox.Yes)
    return box.exec() == QMessageBox.Yes


# ------------------------------------------------------------------ بطاقة إحصائية
class EmptyState(QFrame):
    """حالة فارغة احترافية: أيقونة + عنوان + شرح + إجراء اختياري.

    تُستعمل بدل سطر «لا توجد بيانات» وسط بطاقة فارغة كبيرة."""

    def __init__(self, icon_name: str, title: str, hint: str = "", action: str = "", on_action=None, parent=None):
        super().__init__(parent)
        self.setObjectName("EmptyState")
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 22, 18, 22)
        v.setSpacing(8)
        v.setAlignment(Qt.AlignCenter)
        self._icon_name = icon_name
        self.ic = QLabel()
        self.ic.setObjectName("EmptyIcon")
        self.ic.setFixedSize(52, 52)
        self.ic.setAlignment(Qt.AlignCenter)
        v.addWidget(self.ic, 0, Qt.AlignHCenter)
        self.title = QLabel(title)
        self.title.setObjectName("EmptyTitle")
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setWordWrap(True)
        v.addWidget(self.title)
        self.hint = QLabel(hint)
        self.hint.setObjectName("Muted")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        self.hint.setVisible(bool(hint))
        v.addWidget(self.hint)
        if action and on_action:
            b = QPushButton(action)
            b.setObjectName("Primary")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(on_action)
            v.addWidget(b, 0, Qt.AlignHCenter)
        self.recolor()

    def recolor(self):
        self.ic.setPixmap(icon(self._icon_name, theme.CURRENT["muted"]).pixmap(26, 26))

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == QEvent.PaletteChange:
            self.recolor()


class StatCard(QFrame):
    clicked = Signal(str)

    def __init__(self, key: str, title: str, value="—", sub: str = "", icon_name: str = ""):
        super().__init__()
        self.key = key
        self.setObjectName("Card")
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumSize(180, 104)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        top = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("CardTitle")
        top.addWidget(self.title)
        top.addStretch()
        if icon_name:
            ic = QLabel()
            ic.setPixmap(icon(icon_name, theme.CURRENT["accent"]).pixmap(22, 22))
            top.addWidget(ic)
        lay.addLayout(top)
        self.value = QLabel(str(value))
        self.value.setObjectName("CardValue")
        lay.addWidget(self.value)
        self.sub = QLabel(sub)
        self.sub.setObjectName("Muted")
        self.sub.setWordWrap(True)
        lay.addWidget(self.sub)

    def set(self, value, sub: str = ""):
        self.value.setText(str(value))
        self.sub.setText(sub)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(e)


# ------------------------------------------------------------------ مخطط حلقي
class DonutChart(QWidget):
    def __init__(self, title: str = "", percent: float = 0.0, detail: str = "", color: str | None = None,
                 size: int = 130):
        super().__init__()
        self.title, self.percent, self.detail, self.color = title, percent, detail, color
        self.setMinimumSize(size, size + 38)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._size = size
        self.setToolTip(f"{title}\n{detail}")

    def set(self, percent: float, detail: str = ""):
        self.percent, self.detail = percent, detail
        self.setToolTip(f"{self.title}\n{detail}")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self._size
        r = QRectF(10, 4, s - 20, s - 20)
        pen = QPen(QColor(theme.CURRENT["grid"]), 14)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawArc(r, 0, 360 * 16)
        pct = max(0.0, min(100.0, self.percent))
        col = self.color or (theme.CURRENT["ok"] if pct >= 66 else theme.CURRENT["warn"] if pct >= 33 else theme.CURRENT["accent"])
        pen.setColor(QColor(col))
        p.setPen(pen)
        p.drawArc(r, 90 * 16, int(-pct * 3.6 * 16))
        p.setPen(QColor(theme.CURRENT["text"]))
        f = QFont(self.font())
        f.setPointSize(13)
        f.setBold(True)
        p.setFont(f)
        p.drawText(r, Qt.AlignCenter, f"{pct:.0f}%")
        f.setPointSize(9)
        f.setBold(False)
        p.setFont(f)
        p.drawText(QRectF(0, s - 14, s, 18), Qt.AlignCenter | Qt.TextSingleLine,
                   p.fontMetrics().elidedText(self.title, Qt.ElideMiddle, s))
        p.setPen(QColor(theme.CURRENT["muted"]))
        p.drawText(QRectF(0, s + 4, s, 18), Qt.AlignCenter, self.detail)


# ------------------------------------------------------------------ مخطط أعمدة مزدوج (مبرمج/منجز)
class BarCompare(QWidget):
    def __init__(self):
        super().__init__()
        self.items: list[tuple[str, float, float]] = []
        self.setMinimumHeight(180)

    def set_items(self, items):
        self.items = items[:12]
        self.setMinimumHeight(max(180, 26 * len(self.items) + 30))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme.CURRENT
        if not self.items:
            p.setPen(QColor(t["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "لا توجد ساعات مبرمجة أو منجزة في هذه المدة.")
            return
        w = self.width()
        label_w = min(170, w // 3)
        mx = max(max(a, b) for _, a, b in self.items) or 1
        y = 8
        bar_w = w - label_w - 70
        for name, planned, done in self.items:
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(w - label_w, y, label_w - 6, 20), Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(name, Qt.ElideLeft, label_w - 6))
            x0 = w - label_w - 8
            pw = bar_w * planned / mx
            dw = bar_w * done / mx
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(t["grid"]))
            p.drawRoundedRect(QRectF(x0 - pw, y + 3, pw, 14), 3, 3)
            p.setBrush(QColor(t["accent"]))
            p.drawRoundedRect(QRectF(x0 - dw, y + 3, dw, 14), 3, 3)
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(4, y, 60, 20), Qt.AlignLeft | Qt.AlignVCenter, f"{done:g}/{planned:g}")
            y += 26


# ------------------------------------------------------------------ منحنى خطي (سلاسل متعددة)
class LineChart(QWidget):
    """منحنى بسيط: محور أفقي بتسميات (الأسابيع)، وعدة سلاسل ملوّنة، مع مفتاح وقيمة عند المؤشر."""

    def __init__(self):
        super().__init__()
        self.labels: list[str] = []
        self.series: list[tuple[str, str, list[float]]] = []    # (الاسم، اللون، القيم)
        self.setMinimumHeight(260)
        self.setMouseTracking(True)
        self._hover = None

    def set_data(self, labels: list[str], series: list[tuple[str, str, list[float]]]):
        self.labels, self.series = labels, series
        self.update()

    def _geom(self):
        m_l, m_r, m_t, m_b = 46, 16, 34, 44
        return QRectF(m_l, m_t, max(10, self.width() - m_l - m_r), max(10, self.height() - m_t - m_b))

    def mouseMoveEvent(self, e):
        r = self._geom()
        n = len(self.labels)
        if n:
            k = round((e.position().x() - r.left()) / max(1, r.width()) * (n - 1)) if n > 1 else 0
            self._hover = max(0, min(n - 1, int(k)))
            self.update()

    def leaveEvent(self, _):
        self._hover = None
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        t = theme.CURRENT
        p.fillRect(self.rect(), QColor(t["surface"]))
        if not self.labels or not self.series:
            p.setPen(QColor(t["muted"]))
            p.drawText(self.rect(), Qt.AlignCenter, "لا توجد بيانات لرسمها في هذه المدة.")
            return
        # الرسم من اليسار إلى اليمين (الزمن)، مستقل عن اتجاه الواجهة
        p.setLayoutDirection(Qt.LeftToRight)
        r = self._geom()
        mx = max((max(v) if v else 0) for _n, _c, v in self.series) or 1
        step = 10 ** max(0, len(str(int(mx))) - 1)
        mx = ((mx // step) + 1) * step
        n = len(self.labels)
        xs = [r.left() + (r.width() * i / (n - 1) if n > 1 else r.width() / 2) for i in range(n)]
        grid = QPen(QColor(t["grid"]))
        p.setFont(self.font())
        fm = p.fontMetrics()
        for k in range(5):
            y = r.bottom() - r.height() * k / 4
            p.setPen(grid)
            p.drawLine(r.left(), y, r.right(), y)
            p.setPen(QColor(t["muted"]))
            p.drawText(QRectF(0, y - 9, r.left() - 6, 18), Qt.AlignRight | Qt.AlignVCenter, f"{mx * k / 4:g}")
        every = max(1, n // 12)
        for i, lab in enumerate(self.labels):
            if i % every == 0 or i == n - 1:
                p.drawText(QRectF(xs[i] - 40, r.bottom() + 6, 80, 18), Qt.AlignCenter, lab)
        for name, col, vals in self.series:
            pen = QPen(QColor(col), 2.4)
            p.setPen(pen)
            pts = [(xs[i], r.bottom() - r.height() * (v / mx)) for i, v in enumerate(vals)]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                p.drawLine(x1, y1, x2, y2)
            p.setBrush(QColor(col))
            for x, y in pts:
                p.drawEllipse(QRectF(x - 2.6, y - 2.6, 5.2, 5.2))
        # المفتاح
        x = r.left()
        for name, col, _v in self.series:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col))
            p.drawRoundedRect(QRectF(x, 10, 14, 10), 2, 2)
            p.setPen(QColor(t["text"]))
            w = fm.horizontalAdvance(name) + 10
            p.drawText(QRectF(x + 18, 4, w, 22), Qt.AlignLeft | Qt.AlignVCenter, name)
            x += 18 + w + 14
        if self._hover is not None:
            i = self._hover
            p.setPen(QPen(QColor(t["muted"]), 1, Qt.DashLine))
            p.drawLine(xs[i], r.top(), xs[i], r.bottom())
            txt = f"{self.labels[i]}: " + " · ".join(f"{n_} {v[i]:g}" for n_, _c, v in self.series)
            w = fm.horizontalAdvance(txt) + 16
            bx = min(max(r.left(), xs[i] - w / 2), r.right() - w)
            p.setPen(QColor(t["border"]))
            p.setBrush(QColor(t["surface2"]))
            p.drawRoundedRect(QRectF(bx, r.top() - 2, w, 22), 5, 5)
            p.setPen(QColor(t["text"]))
            p.drawText(QRectF(bx, r.top() - 2, w, 22), Qt.AlignCenter, txt)


# ------------------------------------------------------------------ نافذة نموذج عامة
class FormDialog(QDialog):
    """نافذة إدخال مبنية من وصف الحقول.

    fields: [(key, label, kind, options)] حيث kind ∈ text|int|float|bool|combo|date|time|multiline|color
    """

    def __init__(self, parent, title: str, fields: list[tuple], values: dict | None = None, required=()):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(460)
        self.fields, self.required = fields, set(required)
        self.widgets: dict[str, QWidget] = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        values = values or {}
        for key, label, kind, opts in fields:
            w = self._make(kind, opts, values.get(key))
            self.widgets[key] = w
            form.addRow(label + (" *" if key in self.required else ""), w)
        lay.addLayout(form)
        self.err = QLabel("")
        self.err.setStyleSheet(f"color: {theme.CURRENT['bad']};")
        lay.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _make(self, kind, opts, v):
        if kind == "int":
            w = QSpinBox()
            w.setRange(*(opts or (0, 100000)))
            w.setValue(int(v or 0))
        elif kind == "float":
            w = QDoubleSpinBox()
            w.setRange(*(opts or (0, 100000)))
            w.setDecimals(1)
            w.setValue(float(v or 0))
        elif kind == "bool":
            w = QCheckBox()
            w.setChecked(bool(v))
        elif kind == "combo":
            w = QComboBox()
            for val, lab in (opts or []):
                w.addItem(lab, val)
            if v is not None:
                i = w.findData(v)
                if i >= 0:
                    w.setCurrentIndex(i)
        elif kind == "date":
            w = QDateEdit()
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy")
            w.setDate(QDate.fromString(str(v)[:10], "yyyy-MM-dd") if v else QDate.currentDate())
        elif kind == "time":
            w = QTimeEdit()
            w.setDisplayFormat("HH:mm")
            m = int(v or 480)
            w.setTime(QTime(m // 60, m % 60))
        elif kind == "multiline":
            w = QPlainTextEdit(str(v or ""))
            w.setMaximumHeight(90)
        elif kind == "days":
            from ..utils import DAY_NAMES, parse_rest_days
            w = QWidget()
            hl = QHBoxLayout(w)
            hl.setContentsMargins(0, 0, 0, 0)
            sel = parse_rest_days(v if v is not None else "5,6")
            w.boxes = []
            for i, n in enumerate(DAY_NAMES):
                cb = QCheckBox(n)
                cb.setChecked(i in sel)
                hl.addWidget(cb)
                w.boxes.append(cb)
        elif kind == "color":
            from PySide6.QtWidgets import QPushButton, QColorDialog
            w = QPushButton(str(v or "#4F7CAC"))
            w.color = str(v or "#4F7CAC")

            def pick(_=False, b=w):
                c = QColorDialog.getColor(QColor(b.color), self, "اختيار اللون")
                if c.isValid():
                    b.color = c.name()
                    b.setText(b.color)
                    b.setStyleSheet(f"background:{b.color}; color: white;")
            w.setStyleSheet(f"background:{w.color}; color: white;")
            w.clicked.connect(pick)
        else:
            w = QLineEdit(str(v) if v is not None else "")
            if opts:
                w.setPlaceholderText(str(opts))
        return w

    def values(self) -> dict:
        out = {}
        for key, _label, kind, _opts in self.fields:
            w = self.widgets[key]
            if kind == "int":
                out[key] = w.value()
            elif kind == "float":
                out[key] = w.value()
            elif kind == "bool":
                out[key] = int(w.isChecked())
            elif kind == "combo":
                out[key] = w.currentData()
            elif kind == "date":
                out[key] = w.date().toString("yyyy-MM-dd")
            elif kind == "time":
                t = w.time()
                out[key] = t.hour() * 60 + t.minute()
            elif kind == "multiline":
                out[key] = w.toPlainText().strip()
            elif kind == "days":
                out[key] = ",".join(str(i) for i, cb in enumerate(w.boxes) if cb.isChecked())
            elif kind == "color":
                out[key] = w.color
            else:
                out[key] = w.text().strip()
        return out

    def _accept(self):
        v = self.values()
        missing = [lab for key, lab, *_ in self.fields if key in self.required and v.get(key) in ("", None)]
        if missing:
            self.err.setText("حقول إلزامية فارغة: " + "، ".join(missing))
            return
        self.accept()


def page_title(text: str, sub: str = "") -> QWidget:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 6)
    t = QLabel(text)
    t.setObjectName("PageTitle")
    lay.addWidget(t)
    if sub:
        s = QLabel(sub)
        s.setObjectName("Muted")
        s.setWordWrap(True)
        lay.addWidget(s)
    return w


# ------------------------------------------------------------------ تخطيط ينساب على أسطر (لا يفرض عرضاً كبيراً على النافذة)
from PySide6.QtCore import QPoint, QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QLayout  # noqa: E402


class FlowLayout(QLayout):
    """يضع العناصر في سطر، وينزل إلى سطر جديد إذا ضاق العرض (يراعي اتجاه اليمين إلى اليسار)."""

    def __init__(self, parent=None, spacing: int = 6):
        super().__init__(parent)
        self._items = []
        self._sp = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._do(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do(rect, False)

    def sizeHint(self):
        w = sum(it.sizeHint().width() + self._sp for it in self._items)
        h = max((it.sizeHint().height() for it in self._items), default=0)
        m = self.contentsMargins()
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self):
        s = QSize()
        for it in self._items:
            s = s.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        rtl = (self.parentWidget().layoutDirection() if self.parentWidget() else Qt.LeftToRight) == Qt.RightToLeft
        x, y, line_h = r.x(), r.y(), 0
        rows, row = [], []
        for it in self._items:
            if not it.widget() or not it.widget().isVisible():
                if it.widget() is not None:
                    continue
            sh = it.sizeHint()
            if row and x + sh.width() > r.right() + 1:
                rows.append((row, line_h))
                x, y, row, line_h = r.x(), y + line_h + self._sp, [], 0
            row.append((it, x, sh))
            x += sh.width() + self._sp
            line_h = max(line_h, sh.height())
        if row:
            rows.append((row, line_h))
        if not test:
            yy = r.y()
            for row, lh in rows:
                for it, xx, sh in row:
                    if rtl:
                        xx = r.right() + 1 - (xx - r.x()) - sh.width()
                    it.setGeometry(QRect(QPoint(xx, yy + (lh - sh.height()) // 2), sh))
                yy += lh + self._sp
        total = sum(lh for _, lh in rows) + self._sp * max(0, len(rows) - 1)
        return total + m.top() + m.bottom()
