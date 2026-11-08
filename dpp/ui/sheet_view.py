"""رسم ورقة البرنامج الرسمية، المعاينة قبل الطباعة، والتعديل المباشر على الورقة.

الورقة تُرسم في QGraphicsScene بوحدة النقطة (A4 أفقي = 842×595)، فتخرج في المعاينة والطباعة وPDF
بنفس الشكل تماماً (أبيض وأسود افتراضياً). كل نص في الورقة قابل للتعديل في وضع «تعديل على الورقة».
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import (QBrush, QColor, QFont, QPageLayout, QPageSize, QPainter, QPen, QTextCharFormat,
                           QTextCursor, QTextOption)
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QGraphicsItem, QGraphicsRectItem, QGraphicsScene, QGraphicsTextItem, QGraphicsView,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
                               QSplitter, QToolButton, QVBoxLayout, QWidget)

from ..exporters import layout as L
from ..exporters import official as O
from .widgets import error, icon, info

PAGE_W, PAGE_H = 841.89, 595.28     # A4 أفقي بالنقطة
M = 20.0                            # الهامش


def _light(c: str | None, f: float = 0.72) -> QColor:
    q = QColor(c or "#ffffff")
    return QColor(int(q.red() + (255 - q.red()) * f), int(q.green() + (255 - q.green()) * f),
                  int(q.blue() + (255 - q.blue()) * f))


_PTF: list[float] = []


def _pt_factor() -> float:
    """وحدة المشهد = نقطة؛ النص يُقاس بدقة الشاشة المنطقية، فنصحح حتى يكون 9pt = 9 وحدات فعلاً."""
    if not _PTF:
        from PySide6.QtGui import QGuiApplication
        scr = QGuiApplication.primaryScreen()
        dpi = scr.logicalDotsPerInch() if scr else 96.0
        _PTF.append(72.0 / (dpi or 96.0))
    return _PTF[0]


class EditText(QGraphicsTextItem):
    """نص في صندوق ثابت: محاذاة أفقية وعمودية، قابل للتعديل في وضع التعديل."""

    def __init__(self, scene: "SheetScene", key: str, text: str, rect: QRectF, size: float, bold=False,
                 italic=False, underline=False, align=Qt.AlignHCenter, valign=Qt.AlignVCenter, line_h=0.0):
        super().__init__()
        self.sc, self.key, self.box = scene, key, QRectF(rect)
        self.align, self.valign = align, valign
        self._fmt = (size, bold, italic, underline, line_h)
        self.original = text
        f = QFont()
        f.setFamilies([scene.sheet.style.get("font") or "Arial", "Arial", "Almarai", "DejaVu Sans"])
        f.setPointSizeF(size * _pt_factor())
        f.setBold(bold)
        f.setItalic(italic)
        f.setUnderline(underline)
        self.setFont(f)
        self.setDefaultTextColor(QColor("#000000"))
        opt = QTextOption(align | Qt.AlignVCenter)
        opt.setTextDirection(Qt.RightToLeft)
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(opt)
        self.document().setDocumentMargin(1.5)
        self.setTextWidth(max(10.0, rect.width()))
        self.setPlainText(text)
        self._format_all()
        self.document().contentsChanged.connect(self._changed)
        self._relayout()

    def _format_all(self):
        size, bold, italic, underline, line_h = self._fmt
        cur = QTextCursor(self.document())
        cur.select(QTextCursor.Document)
        cf = QTextCharFormat()
        cf.setFont(self.font())
        cur.mergeCharFormat(cf)
        if line_h:
            bf = cur.blockFormat()
            bf.setLineHeight(line_h * 100, 1)     # ProportionalHeight
            cur.mergeBlockFormat(bf)

    def _relayout(self):
        h = self.document().size().height()
        if self.valign == Qt.AlignTop:
            y = self.box.top()
        elif self.valign == Qt.AlignBottom:
            y = self.box.bottom() - h
        else:
            y = self.box.center().y() - h / 2
        self.setPos(self.box.left(), y)

    def _changed(self):
        self._relayout()
        txt = self.toPlainText()
        self.sc.text_edited(self.key, txt, txt != self.original)

    def set_editable(self, on: bool):
        self.setTextInteractionFlags(Qt.TextEditorInteraction if on else Qt.NoTextInteraction)
        self.setFlag(QGraphicsItem.ItemIsFocusable, on)
        self.setCursor(Qt.IBeamCursor if on else Qt.ArrowCursor)
        self.update()

    def paint(self, painter, option, widget=None):
        if self.sc.edit_mode and not self.sc.printing:
            painter.save()
            painter.setPen(QPen(QColor("#0EA5A4") if self.hasFocus() else QColor(14, 165, 164, 90), 0.6,
                                Qt.SolidLine if self.hasFocus() else Qt.DashLine))
            painter.setBrush(QColor(14, 165, 164, 22) if self.hasFocus() else Qt.NoBrush)
            painter.drawRect(self.boundingRect().adjusted(0.3, 0.3, -0.3, -0.3))
            painter.restore()
        super().paint(painter, option, widget)


class FreeBox(QGraphicsRectItem):
    """مربع نص حر من القالب: يُحرّك ويُغيَّر حجمه ويُدار في وضع التصميم، ويلتصق بالشبكة."""

    HANDLE = 7.0

    def __init__(self, scene: "SheetScene", box: dict):
        super().__init__(0, 0, box["w"], box["h"])
        self.sc, self.box = scene, box
        self.setPos(box["x"], box["y"])
        self.setTransformOriginPoint(box["w"] / 2, box["h"] / 2)
        self.setRotation(float(box.get("rotation") or 0))
        self.setZValue(5)
        self._resizing = False
        self._press = None
        txt, self.missing = L.fill_text(box.get("text", ""), scene.values())
        self.text = txt
        self.setAcceptHoverEvents(True)

    def set_design(self, on: bool):
        self.setFlag(QGraphicsItem.ItemIsMovable, on)
        self.setFlag(QGraphicsItem.ItemIsSelectable, on)
        self.setFlag(QGraphicsItem.ItemIsFocusable, on)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, on)
        self.setCursor(Qt.SizeAllCursor if on else Qt.ArrowCursor)

    def font(self) -> QFont:
        f = QFont()
        fam = self.box.get("font") or self.sc.sheet.style.get("font") or "Arial"
        f.setFamilies([fam, "Arial", "Almarai", "DejaVu Sans"])
        f.setPointSizeF(float(self.box.get("size") or 11) * _pt_factor())
        f.setBold(bool(self.box.get("bold")))
        f.setItalic(bool(self.box.get("italic")))
        f.setUnderline(bool(self.box.get("underline")))
        return f

    def paint(self, p, option, widget=None):
        b = self.box
        r = self.rect()
        if b.get("fill"):
            p.fillRect(r, QColor(b["fill"]))
        fw = float(b.get("frame_w") or 0)
        if fw > 0:
            p.setPen(QPen(QColor(b.get("frame_color") or "#000"), fw))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.adjusted(fw / 2, fw / 2, -fw / 2, -fw / 2))
        pad = float(b.get("padding") or 0)
        if b.get("align") == "justify":
            from .justify import draw as jdraw
            p.setPen(QColor("#C62828") if (self.missing and not self.sc.printing) else QColor(b.get("color") or "#000000"))
            jdraw(p, r.adjusted(pad, pad, -pad, -pad), self.text, self.font(), b.get("valign", "middle"),
                  bool(b.get("kashida")), bool(b.get("justify_last")))
            self._paint_design(p, r)
            return
        al = {"right": Qt.AlignRight, "center": Qt.AlignHCenter, "left": Qt.AlignLeft}.get(b.get("align", "center"),
                                                                                           Qt.AlignHCenter)
        va = {"top": Qt.AlignTop, "middle": Qt.AlignVCenter, "bottom": Qt.AlignBottom}[b.get("valign", "middle")]
        p.setFont(self.font())
        p.setPen(QColor(b.get("color") or "#000000"))
        opt = QTextOption(al | va | Qt.AlignAbsolute)        # «يمين» = يمين الورقة حتى مع اتجاه RTL
        opt.setTextDirection(Qt.RightToLeft)
        opt.setWrapMode(QTextOption.WordWrap)
        tr = r.adjusted(pad, pad, -pad, -pad)
        if self.missing and not self.sc.printing:
            p.setPen(QColor("#C62828"))
        from PySide6.QtGui import QTextDocument
        doc = QTextDocument()
        doc.setDefaultFont(self.font())
        doc.setDefaultTextOption(opt)
        doc.setDocumentMargin(0)
        doc.setTextWidth(max(5.0, tr.width()))
        doc.setPlainText(self.text)
        h = doc.size().height()
        y = tr.top() if va == Qt.AlignTop else (tr.bottom() - h if va == Qt.AlignBottom else tr.center().y() - h / 2)
        p.save()
        p.translate(tr.left(), y)
        from PySide6.QtGui import QAbstractTextDocumentLayout
        ctx = QAbstractTextDocumentLayout.PaintContext()
        ctx.palette.setColor(ctx.palette.ColorRole.Text, p.pen().color())
        doc.documentLayout().draw(p, ctx)
        p.restore()
        self._paint_design(p, r)

    def _paint_design(self, p, r):
        if self.sc.design and not self.sc.printing:
            sel = self.isSelected()
            p.setPen(QPen(QColor("#2563EB") if sel else QColor(37, 99, 235, 110), 0.8,
                          Qt.SolidLine if sel else Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            if sel:
                p.setBrush(QColor("#2563EB"))
                p.drawRect(QRectF(r.right() - self.HANDLE, r.bottom() - self.HANDLE, self.HANDLE, self.HANDLE))

    def _on_handle(self, pos) -> bool:
        r = self.rect()
        return self.isSelected() and pos.x() >= r.right() - self.HANDLE - 2 and pos.y() >= r.bottom() - self.HANDLE - 2

    def hoverMoveEvent(self, e):
        if self.sc.design:
            self.setCursor(Qt.SizeFDiagCursor if self._on_handle(e.pos()) else Qt.SizeAllCursor)
        super().hoverMoveEvent(e)

    def mousePressEvent(self, e):
        if self.sc.design and self._on_handle(e.pos()):
            self._resizing = True
            self._press = e.pos()
            e.accept()
            return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._resizing:
            g = self.sc.grid_size if self.sc.snap else 1.0
            w = max(20.0, round(e.pos().x() / g) * g)
            h = max(10.0, round(e.pos().y() / g) * g)
            self.prepareGeometryChange()
            self.setRect(0, 0, w, h)
            self.setTransformOriginPoint(w / 2, h / 2)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        self._resizing = False
        self._commit_geometry()

    def mouseDoubleClickEvent(self, e):
        if self.sc.design:
            self.sc.request_edit_text.emit(self.box["id"])
            return
        super().mouseDoubleClickEvent(e)

    def keyPressEvent(self, e):
        if not self.sc.design:
            return super().keyPressEvent(e)
        step = self.sc.grid_size if e.modifiers() & Qt.ShiftModifier else 1.0
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}.get(e.key())
        if d:
            self.setPos(self.pos().x() + d[0], self.pos().y() + d[1])
            self._commit_geometry()
            return
        if e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            self.sc.request_delete.emit(self.box["id"])
            return
        super().keyPressEvent(e)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange and self.sc.snap and not self._resizing:
            g = self.sc.grid_size
            return QPointF(round(value.x() / g) * g, round(value.y() / g) * g)
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.sc.selection_box.emit(self.box["id"] if value else "")
        return super().itemChange(change, value)

    def _commit_geometry(self):
        r = self.rect()
        new = {"x": round(self.pos().x(), 1), "y": round(self.pos().y(), 1), "w": round(r.width(), 1),
               "h": round(r.height(), 1)}
        if any(abs(float(self.box.get(k, 0)) - v) > 0.05 for k, v in new.items()):
            self.sc.box_geometry.emit(self.box["id"], new)


class TableHandle(QGraphicsRectItem):
    """مقبض لتغيير عرض عمود أو ارتفاع سطر الجدول بالسحب (وضع التصميم فقط)."""

    def __init__(self, scene, kind: str, a: int, b: int, rect: QRectF, lo: float, hi: float):
        super().__init__(rect)
        self.sc, self.kind, self.a, self.b, self.lo, self.hi = scene, kind, a, b, lo, hi
        self.start = rect.center().x() if kind == "col" else rect.center().y()
        self.setPen(Qt.NoPen)
        self.setBrush(QColor(37, 99, 235, 60))
        self.setZValue(8)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        self.setCursor(Qt.SizeHorCursor if kind == "col" else Qt.SizeVerCursor)
        self.setToolTip("اسحب لتغيير " + ("عرض العمودين" if kind == "col" else "ارتفاع السطرين"))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            if self.kind == "col":
                c = self.start + value.x()
                c = max(self.lo + 12, min(self.hi - 12, c))
                return QPointF(c - self.start, 0)
            c = self.start + value.y()
            c = max(self.lo + 10, min(self.hi - 10, c))
            return QPointF(0, c - self.start)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        delta = self.pos().x() if self.kind == "col" else self.pos().y()
        if abs(delta) > 0.5:
            self.sc.table_resize.emit(self.kind, self.a, self.b, (self.start + delta - self.lo) / (self.hi - self.lo))


class SheetScene(QGraphicsScene):
    edited = Signal()
    selection_box = Signal(str)
    box_geometry = Signal(str, object)
    request_edit_text = Signal(str)
    request_delete = Signal(str)
    table_resize = Signal(str, int, int, float)

    def __init__(self, sheet: O.Sheet, show_room=True, color=False, edit_mode=False, design=False,
                 page_no: int = 1, pages: int = 1):
        if not sheet.layout:
            sheet.layout = L.effective_default()
        W, H = L.paper_size(sheet.layout)
        super().__init__(0, 0, W, H)
        self.W, self.H = W, H
        self.sheet, self.show_room, self.color = sheet, show_room, color
        self.edit_mode, self.printing, self.design = edit_mode, False, design
        self.page_no, self.pages = page_no, pages
        self.snap, self.grid_size, self.show_grid = True, 10.0, True
        self.texts: list[EditText] = []
        self.boxes: dict[str, FreeBox] = {}
        self.hidden_with_data: list[str] = []
        self.setBackgroundBrush(QBrush(QColor("#ffffff")))
        self._build()
        self.set_edit_mode(edit_mode)
        self.set_design(design)

    def values(self) -> dict:
        return self.sheet.values | {"page": self.page_no, "pages": self.pages}

    def missing_fields(self) -> list[str]:
        return sorted({m for b in self.boxes.values() for m in b.missing})

    def rebuild(self):
        sel = next((k for k, b in self.boxes.items() if b.isSelected()), "")
        self.clear()
        self.texts, self.boxes = [], {}
        W, H = L.paper_size(self.sheet.layout)
        self.W, self.H = W, H
        self.setSceneRect(0, 0, W, H)
        self._build()
        self.set_edit_mode(self.edit_mode)
        self.set_design(self.design)
        if sel in self.boxes:
            self.boxes[sel].setSelected(True)

    # ------------------------------------------------------------------ أدوات
    def _t(self, key, rect, size, bold=True, italic=False, underline=False, align=Qt.AlignHCenter,
           valign=Qt.AlignVCenter, default=None, line_h=0.0):
        if key in self.sheet.layout.get("hidden_fields", []):
            return None
        text = self.sheet.edits.get(key, self.sheet.fields.get(key, "") if default is None else default)
        orig = self.sheet.fields.get(key, "") if default is None else default
        it = EditText(self, key, text, rect, size, bold, italic, underline, align, valign, line_h)
        it.original = orig
        self.addItem(it)
        self.texts.append(it)
        return it

    def _rect(self, r: QRectF, w=0.8, fill=None, radius=0.0, color=None):
        pen = QPen(QColor(color or "#000000"), w)
        if radius:
            from PySide6.QtWidgets import QGraphicsPathItem
            from PySide6.QtGui import QPainterPath
            p = QPainterPath()
            p.addRoundedRect(r, radius, radius)
            it = QGraphicsPathItem(p)
            it.setPen(pen)
        else:
            it = QGraphicsRectItem(r)
            it.setPen(pen if w > 0 else QPen(Qt.NoPen))
            if fill is not None:
                it.setBrush(QBrush(fill))
        it.setZValue(-1)
        self.addItem(it)
        return it

    def text_edited(self, key, txt, changed):
        if changed:
            self.sheet.edits[key] = txt
        else:
            self.sheet.edits.pop(key, None)
        self.edited.emit()

    def set_edit_mode(self, on: bool):
        self.edit_mode = on
        for t in self.texts:
            t.set_editable(on and not self.design)
        if not on:
            self.clearFocus()
        self.update()

    def set_design(self, on: bool):
        self.design = on
        for b in self.boxes.values():
            b.set_design(on)
        for it in self.items():
            if isinstance(it, TableHandle):
                it.setVisible(on)
        for t in self.texts:
            t.set_editable(self.edit_mode and not on)
        self.update()

    # ------------------------------------------------------------------ الرسم
    def _build(self):
        if getattr(self.sheet, "report", None) is not None:
            self._build_report()
            return
        sh, st, lay = self.sheet, self.sheet.style, self.sheet.layout
        tb = lay["table"]
        hp, cp = st["head_pt"], st["center_pt"]
        W, H = self.W, self.H
        mt, mr, mb, ml = (float(x) for x in lay["page"].get("margins", [20, 20, 20, 20]))
        cx = W / 2
        side_w = min(190.0, W * 0.24)
        self._t("republic", QRectF(cx - (W - 2 * 220) / 2 if W > 600 else ml, mt - 8,
                                   (W - 440) if W > 600 else W - ml - mr, 16), hp + 1, underline=False)
        self._t("right_block", QRectF(W - mr - side_w, mt + 10, side_w, 110), hp, align=Qt.AlignRight,
                valign=Qt.AlignTop, line_h=1.2)
        self._t("left_block", QRectF(ml + 10, mt + 10, side_w, 52), hp, align=Qt.AlignRight, valign=Qt.AlignTop,
                line_h=1.15)
        if "approval" not in lay.get("hidden_fields", []):
            box = QRectF(ml, mt + 64, min(185.0, side_w), 76)
            self._rect(box, 0.9, radius=8)
            self._t("approval", QRectF(box.left() + 4, box.top() + 2, box.width() - 8, 32), hp + 0.5, underline=True,
                    valign=Qt.AlignTop)
        cw = max(160.0, W - 2 * (side_w + 25 + max(ml, mr)))
        self._t("center_block", QRectF(cx - cw / 2, mt + 30, cw, 120), cp, align=Qt.AlignHCenter,
                valign=Qt.AlignTop, line_h=1.45)

        # ---- الجدول
        top = max(mt + 140, float(tb.get("top") or 172.0) * (H / PAGE_H if H < PAGE_H else 1.0))
        bottom = H - max(mb + 40, float(tb.get("bottom_gap") or 80.0))
        day_w = float(tb.get("day_w") or 64.0)
        left, right = ml, W - mr
        head_h = float(tb.get("head_h") or 30.0)
        bw, ow, bcol = float(tb.get("border_w", 0.6)), float(tb.get("outer_w", 1.2)), tb.get("border_color") or "#000"
        hidden_c = {int(x) for x in tb.get("hidden_cols", [])}
        hidden_d = {int(x) for x in tb.get("hidden_days", [])}
        cols = [j for j in range(len(sh.periods)) if j not in hidden_c]
        days = [d for d in range(len(sh.days)) if d not in hidden_d]
        notes = bool(tb.get("notes_col"))
        # أعمدة/أيام مخفية فيها حصص: تنبيه (لا تُخفى بيانات دون علم)
        self.hidden_with_data = sorted(
            {f"الحصة {sh.periods[j][0]}" for c in sh.cells for j in range(c.c0, c.c1 + 1) if j in hidden_c}
            | {f"يوم {sh.days[c.day]}" for c in sh.cells if c.day in hidden_d})
        cw_ = {j: float(tb.get("col_weights", {}).get(str(j), 1.0)) for j in cols}
        nw = float(tb.get("notes_w") or 1.0) if notes else 0.0
        total_w = sum(cw_.values()) + nw or 1.0
        avail = right - day_w - left
        xs: dict[int, tuple[float, float]] = {}
        x = right - day_w
        for j in cols:                           # RTL: الحصة الأولى بجانب عمود الأيام (يمين)
            w = avail * cw_[j] / total_w
            xs[j] = (x - w, x)
            x -= w
        notes_r = (left, x) if notes else None
        rw = {d: float(tb.get("row_weights", {}).get(str(d), 1.0)) for d in days}
        total_h = sum(rw.values()) or 1.0
        ys: dict[int, tuple[float, float]] = {}
        y = top + head_h
        for d in days:
            h = (bottom - top - head_h) * rw[d] / total_h
            ys[d] = (y, y + h)
            y += h
        head_fill = QColor(tb["head_fill"]) if tb.get("head_fill") else None
        day_fill = QColor(tb["day_fill"]) if tb.get("day_fill") else None
        cell_fill = QColor(tb["cell_fill"]) if tb.get("cell_fill") else None
        head_pt = float(tb.get("head_pt") or hp)
        title_pt = float(tb.get("title_pt") or st["title_pt"])
        sub_pt = float(tb.get("sub_pt") or st["sub_pt"])

        self._rect(QRectF(left, top, right - left, bottom - top), ow, color=bcol)
        self._rect(QRectF(right - day_w, top, day_w, head_h), bw, head_fill, color=bcol)
        for j in cols:
            x0, x1 = xs[j]
            lab, tm = sh.periods[j]
            self._rect(QRectF(x0, top, x1 - x0, head_h), bw, head_fill, color=bcol)
            self._t(f"ph:{j}:label", QRectF(x0, top + 2, x1 - x0, 11), 6, bold=False, default=lab)
            self._t(f"ph:{j}:time", QRectF(x0, top + 12, x1 - x0, 16), head_pt, default=tm)
        if notes_r:
            self._rect(QRectF(notes_r[0], top, notes_r[1] - notes_r[0], head_h), bw, head_fill, color=bcol)
            self._t("notes_title", QRectF(notes_r[0], top, notes_r[1] - notes_r[0], head_h), head_pt,
                    default=tb.get("notes_title") or "ملاحظات")

        def span(c0, c1):
            vis = [j for j in range(c0, c1 + 1) if j in xs]
            if not vis:
                return None
            return min(xs[j][0] for j in vis), max(xs[j][1] for j in vis), vis

        occupied = {(c.day, j) for c in sh.cells for j in range(c.c0, c.c1 + 1)}
        merged = {(m["day"], j) for m in tb.get("merges", []) for j in range(int(m["c0"]), int(m["c1"]) + 1)}
        cell_texts = tb.get("cell_texts", {})
        for d in days:
            y0, y1 = ys[d]
            self._rect(QRectF(right - day_w, y0, day_w, y1 - y0), bw, day_fill, color=bcol)
            self._t(f"day:{d}", QRectF(right - day_w, y0, day_w, y1 - y0), float(tb.get("day_pt") or 12.5),
                    default=sh.days[d])
            for j in cols:
                if (d, j) in occupied or (d, j) in merged:
                    continue
                x0, x1 = xs[j]
                self._rect(QRectF(x0, y0, x1 - x0, y1 - y0), bw, cell_fill, color=bcol)
                t = cell_texts.get(f"{d}:{j}")
                if t:
                    self._t(f"ctext:{d}:{j}", QRectF(x0 + 2, y0 + 2, x1 - x0 - 4, y1 - y0 - 4), title_pt, False,
                            default=L.fill_text(t, self.values())[0])
            if notes_r:
                self._rect(QRectF(notes_r[0], y0, notes_r[1] - notes_r[0], y1 - y0), bw, cell_fill, color=bcol)
        for c in sh.cells:
            if c.day not in ys:
                continue
            sp = span(c.c0, c.c1)
            if not sp:
                continue
            x0, x1, vis = sp
            if all((c.day, j) in merged for j in vis):
                continue
            y0, y1 = ys[c.day]
            row_h = y1 - y0
            fill = _light(c.color) if (self.color and c.color) else cell_fill
            self._rect(QRectF(x0, y0, x1 - x0, row_h), bw, fill, color=bcol)
            key = f"cell:{c.day}:{c.c0}"
            has_sub = bool(c.sub) or bool(c.corner and self.show_room)
            title_r = QRectF(x0 + 3, y0 + 2, x1 - x0 - 6, row_h - (15 if has_sub else 4))
            self._t(key + ":title", title_r, title_pt, st["title_bold"], st["title_italic"],
                    st["title_underline"], default=c.title,
                    align=Qt.AlignJustify if tb.get("cell_align") == "justify" else Qt.AlignHCenter)
            sub_w = (x1 - x0) * (0.72 if (c.corner and self.show_room) else 0.96)
            if c.sub:
                self._t(key + ":sub", QRectF(x1 - sub_w - 2, y0 + row_h - 14, sub_w, 13), sub_pt, False,
                        align=Qt.AlignRight, valign=Qt.AlignBottom, default=c.sub)
            if c.corner and self.show_room:
                self._t(key + ":corner", QRectF(x0 + 2, y0 + row_h - 14, (x1 - x0) * 0.26, 13), sub_pt, True,
                        align=Qt.AlignLeft, valign=Qt.AlignBottom, default=c.corner)
            if c.note:
                self._t(key + ":note", QRectF(x0 + 2, y0 + 1, (x1 - x0) * 0.5, 10), 5.5, False,
                        align=Qt.AlignLeft, valign=Qt.AlignTop, default=c.note)
        for k, m in enumerate(tb.get("merges", [])):
            d = int(m["day"])
            if d not in ys:
                continue
            sp = span(int(m["c0"]), int(m["c1"]))
            if not sp:
                continue
            x0, x1, _v = sp
            y0, y1 = ys[d]
            self._rect(QRectF(x0, y0, x1 - x0, y1 - y0), bw, cell_fill or QColor("#ffffff"), color=bcol).setZValue(0.5)
            t = self._t(f"merge:{k}", QRectF(x0 + 3, y0 + 2, x1 - x0 - 6, y1 - y0 - 4), title_pt, True,
                        default=L.fill_text(m.get("text", ""), self.values())[0])
            if t:
                t.setZValue(1)
        # مقابض تغيير العرض والارتفاع (وضع التصميم)
        for a, b in zip(cols, cols[1:]):
            xa = xs[a][0]
            lo, hi = xs[b][0], xs[a][1]
            self.addItem(TableHandle(self, "col", a, b, QRectF(xa - 2.5, top, 5, head_h), lo, hi))
        for a, b in zip(days, days[1:]):
            yb = ys[a][1]
            self.addItem(TableHandle(self, "row", a, b, QRectF(right - day_w, yb - 2.5, day_w, 5), ys[a][0], ys[b][1]))

        # ---- التذييل
        fy = bottom + 3
        self._t("created", QRectF(W - mr - 170, fy, 170, 12), 6, bold=False, align=Qt.AlignRight, valign=Qt.AlignTop)
        self._t("note", QRectF(min(220.0, W * 0.26), fy, W - 2 * min(220.0, W * 0.26) + 60, 14), hp + 1,
                underline=True, align=Qt.AlignRight, valign=Qt.AlignTop)
        sy = fy + 24
        self._t("sign_right", QRectF(W - mr - 220, sy, 220, 16), hp + 0.5, underline=True, align=Qt.AlignRight)
        self._t("sign_center", QRectF(W / 2 - 130, sy, 260, 16), hp + 0.5, underline=True)
        self._t("sign_left", QRectF(ml, sy, 200, 16), hp + 0.5, underline=True, align=Qt.AlignLeft)
        # ---- النصوص الحرة
        for b in lay.get("boxes", []):
            it = FreeBox(self, b)
            self.addItem(it)
            self.boxes[b["id"]] = it

    # ------------------------------------------------------------------ التقارير
    def _build_report(self):
        """صفحة تقرير: الرأس الرسمي (في الصفحة الأولى)، ثم الجداول والفقرات، ثم التوقيعات ورقم الصفحة."""
        from ..exporters import report_sheet as RS
        sh, st, lay = self.sheet, self.sheet.style, self.sheet.layout
        pg, doc = sh.report, sh.doc
        tb = lay["table"]
        W, H = self.W, self.H
        mt, mr, mb, ml = (float(x) for x in lay["page"].get("margins", [22, 22, 22, 22]))
        hp, cp = RS._sizes(lay)
        head_pt = float(st.get("head_pt", 9))
        side_w = min(190.0, W * 0.3)
        if pg.get("first"):
            self._t("republic", QRectF(ml, mt - 6, W - ml - mr, 16), head_pt + 1)
            self._t("right_block", QRectF(W - mr - side_w, mt + 12, side_w, 90), head_pt - 0.5, align=Qt.AlignRight,
                    valign=Qt.AlignTop, line_h=1.15)
            self._t("left_block", QRectF(ml, mt + 12, side_w, 40), head_pt - 0.5, align=Qt.AlignLeft,
                    valign=Qt.AlignTop, line_h=1.15)
            top = float(tb.get("top") or 150)
            cw = W - 2 * (side_w * 0.55 + max(ml, mr))
            self._t("center_block", QRectF(W / 2 - cw / 2, mt + 52, cw, max(40.0, top - mt - 58)),
                    float(st.get("center_pt", 10)) + 1, align=Qt.AlignHCenter, valign=Qt.AlignTop, line_h=1.35)
        else:
            self._t("rpt_title", QRectF(ml, mt, W - ml - mr, 22), head_pt + 1.5, default=doc.title)
        bw, ow = float(tb.get("border_w", 0.6)), float(tb.get("outer_w", 1.2))
        bcol = tb.get("border_color") or "#000"
        head_fill = QColor(tb["head_fill"]) if tb.get("head_fill") else QColor("#E8EDF3")
        cell_fill = QColor(tb["cell_fill"]) if tb.get("cell_fill") else None
        justify = tb.get("cell_align") == "justify"
        right = W - mr
        avail = W - ml - mr
        handles_done = False
        for item in pg["items"]:
            b = doc.blocks[item["block"]]
            if item["type"] == "image":
                from PySide6.QtGui import QPixmap
                from PySide6.QtWidgets import QGraphicsPixmapItem
                pm = QPixmap()
                pm.loadFromData(b["png"])
                if not pm.isNull():
                    sc_ = min(avail / pm.width(), item["h"] / pm.height())
                    it = QGraphicsPixmapItem(pm)
                    it.setTransformationMode(Qt.SmoothTransformation)
                    it.setScale(sc_)
                    it.setPos(ml + (avail - pm.width() * sc_) / 2, item["y"])
                    self.addItem(it)
                continue
            if item["type"] == "para":
                pt = float(b.get("size") or (cp + 1.5))
                self._t(f"p:{item['block']}", QRectF(ml, item["y"], avail, item["h"]), pt, bool(b.get("bold")),
                        align=Qt.AlignJustify if (justify and not b.get("heading")) else Qt.AlignRight,
                        valign=Qt.AlignTop, default=b["text"])
                continue
            widths = RS.col_widths(b, avail, lay)
            xs, x = {}, right
            for j, w in widths:
                xs[j] = (x - w, x)
                x -= w
            y = item["y"]
            if item.get("caption"):
                self._t(f"cap:{item['block']}:{y:.0f}", QRectF(ml, y, avail, item["cap_h"]), cp + 2, True,
                        align=Qt.AlignRight, default=item["caption"])
                y += item["cap_h"]
            hh = item["head_h"]
            for j, (x0, x1) in xs.items():
                self._rect(QRectF(x0, y, x1 - x0, hh), bw, head_fill, color=bcol)
                self._t(f"h:{item['block']}:{j}:{y:.0f}", QRectF(x0 + 2, y + 1, x1 - x0 - 4, hh - 2), hp,
                        default=b["headers"][j])
            top_y = y
            y += hh
            covered = set()
            for ri, h in zip(item["rows"], item["heights"]):
                row = b["rows"][ri]
                bold = ri in b.get("bold_rows", ())
                for j, (x0, x1) in xs.items():
                    if (ri, j) in covered:
                        continue
                    span = int(b.get("spans", {}).get(f"{ri}:{j}", 1))
                    hh2 = h
                    if span > 1:
                        k = item["rows"].index(ri)
                        hh2 = sum(item["heights"][k:k + span])
                        for d in range(1, span):
                            covered.add((ri + d, j))
                    col = b["fills"].get(f"{ri}:{j}")
                    fill = QColor(col) if col else (head_fill if bold else cell_fill)
                    self._rect(QRectF(x0, y, x1 - x0, hh2), bw, fill, color=bcol)
                    al = (b.get("align") or [None] * 99)[j] if b.get("align") else None
                    qal = {"right": Qt.AlignRight, "left": Qt.AlignLeft, "center": Qt.AlignHCenter}.get(al)
                    if qal is None:
                        qal = Qt.AlignJustify if justify else Qt.AlignHCenter
                    self._t(f"c:{item['block']}:{ri}:{j}", QRectF(x0 + 3, y + 1, x1 - x0 - 6, hh2 - 2), cp, bold,
                            align=qal, default=row[j] if j < len(row) else "")
                y += h
            self._rect(QRectF(min(a for a, _ in xs.values()), top_y, sum(b_ - a for a, b_ in xs.values()), y - top_y),
                       ow, color=bcol)
            if not handles_done:                          # مقابض عرض الأعمدة (وضع التصميم)
                cols = list(xs)
                for a, b2 in zip(cols, cols[1:]):
                    xa = xs[a][0]
                    self.addItem(TableHandle(self, "col", a, b2, QRectF(xa - 2.5, top_y, 5, hh), xs[b2][0], xs[a][1]))
                handles_done = True
        # التذييل: التوقيعات في آخر صفحة، ورقم الصفحة في كل صفحة
        last = getattr(sh, "page_index", 0) == getattr(sh, "page_count", 1) - 1
        bottom = H - max(mb + 30, float(tb.get("bottom_gap") or 70))
        if last:
            sy = bottom + 10
            self._t("sign_right", QRectF(W - mr - 200, sy, 200, 16), head_pt + 0.5, underline=True, align=Qt.AlignRight)
            self._t("sign_center", QRectF(W / 2 - 120, sy, 240, 16), head_pt + 0.5, underline=True)
            self._t("sign_left", QRectF(ml, sy, 180, 16), head_pt + 0.5, underline=True, align=Qt.AlignLeft)
        self._t("pageno", QRectF(W / 2 - 60, H - mb - 4, 120, 12), 7, False,
                default=f"الصفحة {self.page_no} من {self.pages}")
        for bx in lay.get("boxes", []):
            it = FreeBox(self, bx)
            self.addItem(it)
            self.boxes[bx["id"]] = it

    # ------------------------------------------------------------------ الإخراج
    def render_page(self, painter: QPainter, target: QRectF):
        self.printing = True
        was = self.edit_mode
        if was:
            for t in self.texts:
                t.setTextInteractionFlags(Qt.NoTextInteraction)
        handles = [it for it in self.items() if isinstance(it, TableHandle)]
        for h in handles:
            h.setVisible(False)
        self.clearSelection()
        self.setFocusItem(None)
        self.render(painter, target, QRectF(0, 0, self.W, self.H), Qt.KeepAspectRatio)
        for h in handles:
            h.setVisible(self.design)
        if was:
            self.set_edit_mode(True)
        self.printing = False

    def page_layout(self) -> QPageLayout:
        lay = self.sheet.layout["page"]
        size = {"A4": QPageSize.A4, "A3": QPageSize.A3, "A5": QPageSize.A5, "Letter": QPageSize.Letter,
                "Legal": QPageSize.Legal}.get(lay.get("paper", "A4"), QPageSize.A4)
        ori = QPageLayout.Landscape if lay.get("orientation", "landscape") == "landscape" else QPageLayout.Portrait
        return QPageLayout(QPageSize(size), ori, QMarginsF(0, 0, 0, 0))


def _page_layout() -> QPageLayout:
    return QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape, QMarginsF(0, 0, 0, 0))


def render_to_pdf(scenes: list[SheetScene], path: str):
    from PySide6.QtGui import QPdfWriter
    w = QPdfWriter(str(path))
    w.setPageLayout(scenes[0].page_layout() if scenes else _page_layout())
    w.setResolution(300)
    w.setTitle(scenes[0].sheet.name if scenes else "DPP")
    w.setCreator("DPP")
    p = QPainter(w)
    try:
        for i, sc in enumerate(scenes):
            if i:
                w.setPageLayout(sc.page_layout())
                w.newPage()
            vp = p.viewport()
            sc.render_page(p, QRectF(0, 0, vp.width(), vp.height()))
    finally:
        p.end()
    return path


def print_scenes(scenes: list[SheetScene], parent=None) -> bool:
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    pr = QPrinter(QPrinter.HighResolution)
    pr.setPageLayout(scenes[0].page_layout() if scenes else _page_layout())
    pr.setFullPage(True)
    dlg = QPrintDialog(pr, parent)
    dlg.setWindowTitle("طباعة البرنامج")
    if dlg.exec() != QDialog.Accepted:
        return False
    p = QPainter(pr)
    try:
        for i, sc in enumerate(scenes):
            if i:
                pr.setPageLayout(sc.page_layout())
                pr.newPage()
            sc.render_page(p, pr.pageRect(QPrinter.DevicePixel))
    finally:
        p.end()
    return True


# ====================================================================== المعاينة
class PaperView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setBackgroundBrush(QColor("#8A9199"))
        self.setAlignment(Qt.AlignCenter)
        self.setLayoutDirection(Qt.LeftToRight)       # الورقة نفسها مرسومة من اليمين
        self.zoom = 1.0
        self.fit = True

    def _wh(self):
        sc = self.scene()
        return (sc.W, sc.H) if isinstance(sc, SheetScene) else (PAGE_W, PAGE_H)

    def set_scene(self, sc):
        self.setScene(sc)
        self.apply_zoom()

    def apply_zoom(self):
        self.resetTransform()
        if self.fit and self.scene():
            W, H = self._wh()
            vw = max(100, self.viewport().width() - 30)
            vh = max(100, self.viewport().height() - 30)
            self.zoom = min(vw / W, vh / H)
        self.scale(self.zoom, self.zoom)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit:
            self.apply_zoom()

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        W, H = self._wh()
        painter.fillRect(QRectF(4, 5, W, H), QColor(0, 0, 0, 70))
        painter.fillRect(QRectF(0, 0, W, H), QColor("#ffffff"))

    def drawForeground(self, painter, rect):
        """الشبكة الخفيفة: في وضع التصميم فقط، ولا تُطبع أبداً (الطباعة ترسم المشهد لا العرض)."""
        sc = self.scene()
        if not isinstance(sc, SheetScene) or not sc.design or not sc.show_grid:
            return
        g = max(2.0, sc.grid_size)
        W, H = sc.W, sc.H
        painter.save()
        pen = QPen(QColor(37, 99, 235, 28), 0)
        strong = QPen(QColor(37, 99, 235, 60), 0)
        k = 0
        x = 0.0
        while x <= W:
            painter.setPen(strong if k % 5 == 0 else pen)
            painter.drawLine(QPointF(x, 0), QPointF(x, H))
            x += g
            k += 1
        k = 0
        y = 0.0
        while y <= H:
            painter.setPen(strong if k % 5 == 0 else pen)
            painter.drawLine(QPointF(0, y), QPointF(W, y))
            y += g
            k += 1
        mt, mr, mb, ml = (float(v) for v in sc.sheet.layout["page"].get("margins", [20, 20, 20, 20]))
        painter.setPen(QPen(QColor(220, 38, 38, 90), 0, Qt.DashLine))
        painter.drawRect(QRectF(ml, mt, W - ml - mr, H - mt - mb))
        painter.restore()

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.step(1 if e.angleDelta().y() > 0 else -1)
            return
        super().wheelEvent(e)

    def step(self, d):
        self.fit = False
        self.zoom = max(0.3, min(4.0, self.zoom * (1.15 if d > 0 else 1 / 1.15)))
        self.apply_zoom()


class PreviewDialog(QDialog):
    """معاينة الأوراق قبل الطباعة + تعديل النصوص مباشرة على الورقة."""

    def __init__(self, db, sheets: list[O.Sheet], parent=None, show_room=True, color=False, one_file=False):
        super().__init__(parent)
        self.db, self.sheets = db, sheets
        self.doc = getattr(sheets[0], "doc", None) if sheets else None     # تقرير متعدد الصفحات
        self.show_room, self.color, self.one_file = show_room, color, one_file
        self.scenes: dict[int, SheetScene] = {}
        import json as _json
        self._json = _json
        self.saved_layouts = {i: _json.dumps(s.layout, sort_keys=True) for i, s in enumerate(sheets)}
        self.undo_stack: dict[int, list[str]] = {}
        self.redo_stack: dict[int, list[str]] = {}
        self.grid_opts = {"show": True, "snap": True, "size": 10.0}
        self.setWindowTitle(f"معاينة الطباعة — {self.doc.title}" if self.doc else f"معاينة الطباعة — {len(sheets)} ورقة")
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.resize(1250, 820)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        bar = QHBoxLayout()

        def btn(ic, text, fn, tip=""):
            b = QPushButton(icon(ic), text)
            b.setToolTip(tip or text)
            b.clicked.connect(fn)
            bar.addWidget(b)
            return b

        btn("mdi6.printer", "طباعة…", self.do_print, "طباعة كل الأوراق")
        btn("mdi6.file-pdf-box", "PDF", self.do_pdf, "حفظ PDF")
        btn("mdi6.file-excel-outline", "Excel", self.do_xlsx, "حفظ Excel")
        btn("mdi6.file-eye-outline", "معاينة PDF", self.preview_pdf,
            "يُخرج الورقة الحالية PDF مؤقتاً ويفتحه، لترى ما ستطبعه بالضبط")
        bar.addSpacing(12)
        self.chk_room = QCheckBox("إظهار القاعة في الخانات")
        self.chk_room.setChecked(show_room)
        self.chk_room.toggled.connect(self._opts)
        bar.addWidget(self.chk_room)
        self.chk_color = QCheckBox("بالألوان")
        self.chk_color.setChecked(color)
        self.chk_color.toggled.connect(self._opts)
        bar.addWidget(self.chk_color)
        if self.doc is not None:
            self.chk_room.hide()
            self.chk_color.hide()
        bar.addSpacing(12)
        self.b_edit = QPushButton(icon("mdi6.pencil-outline"), "تعديل على الورقة")
        self.b_edit.setCheckable(True)
        self.b_edit.toggled.connect(self._edit_mode)
        bar.addWidget(self.b_edit)
        self.b_save = QPushButton(icon("mdi6.content-save-outline"), "حفظ التعديلات…")
        self.b_save.clicked.connect(self.save_edits)
        self.b_save.setEnabled(False)
        bar.addWidget(self.b_save)
        bar.addSpacing(12)
        self.b_design = QPushButton(icon("mdi6.palette-swatch-variant"), "تصميم الورقة")
        self.b_design.setToolTip("إضافة نصوص حرة، الشبكة، الورقة والهوامش، وشكل الجدول، وحفظ القالب")
        self.b_design.setCheckable(True)
        self.b_design.toggled.connect(self._design_mode)
        bar.addWidget(self.b_design)
        self.b_undo = QToolButton()
        self.b_undo.setIcon(icon("mdi6.undo"))
        self.b_undo.setToolTip("تراجع (Ctrl+Z)")
        self.b_undo.clicked.connect(self.undo)
        bar.addWidget(self.b_undo)
        self.b_redo = QToolButton()
        self.b_redo.setIcon(icon("mdi6.redo"))
        self.b_redo.setToolTip("إعادة (Ctrl+Y)")
        self.b_redo.clicked.connect(self.redo)
        bar.addWidget(self.b_redo)
        from PySide6.QtGui import QKeySequence, QShortcut
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self.undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self.redo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self, activated=self.redo)
        bar.addStretch()
        for txt, tip, fn in (("−", "تصغير (Ctrl+عجلة)", lambda: self.view.step(-1)),
                             ("+", "تكبير (Ctrl+عجلة)", lambda: self.view.step(1))):
            b = QToolButton()
            b.setText(txt)
            b.setToolTip(tip)
            b.setFixedWidth(30)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bfit = QToolButton()
        bfit.setText("ملء")
        bfit.setToolTip("ملاءمة الورقة للنافذة")
        bfit.clicked.connect(self._fit)
        bar.addWidget(bfit)
        lay.addLayout(bar)

        split = QSplitter(Qt.Horizontal)
        self.pages = QListWidget()
        self.pages.setMaximumWidth(260)
        self._fill_page_list()
        self.pages.currentRowChanged.connect(self.show_page)
        self.view = PaperView()
        split.addWidget(self.pages)
        split.addWidget(self.view)
        from .sheet_design import DesignPanel
        self.design = DesignPanel(self)
        self.design.hide()
        split.addWidget(self.design)
        split.setStretchFactor(1, 1)
        if len(sheets) <= 1:
            self.pages.hide()
        lay.addWidget(split, 1)
        self.hint = QLabel("للتعديل: اضغط «تعديل على الورقة» ثم انقر على أي نص في الورقة واكتب. "
                           "التعديلات تُطبع مباشرة، و«حفظ التعديلات» يحفظها في القالب إذا أردت.")
        self.hint.setObjectName("Muted")
        lay.addWidget(self.hint)
        self.pages.setCurrentRow(0)
        if sheets:
            self.show_page(0)

    def _fill_page_list(self):
        self.pages.blockSignals(True)
        self.pages.clear()
        for i, s in enumerate(self.sheets):
            lab = f"الصفحة {i + 1}" if self.doc is not None else f"{O.week_label(self.db, s.ws)} · {s.name}"
            self.pages.addItem(QListWidgetItem(lab))
        self.pages.blockSignals(False)
        if self.doc is not None:
            self.pages.setVisible(len(self.sheets) > 1)

    def _repaginate(self, layout=None, used=None):
        """التقرير: إعادة توزيع الصفحات بعد تغيير التصميم (الورق، الهوامش، الخطوط، الأعمدة)."""
        from ..exporters import report_sheet as RS
        cur = self.cur_index()
        lay = layout if layout is not None else self.sheets[0].layout
        used = used if used is not None else self.sheets[0].layout_scopes
        edits = self.sheets[0].edits
        self.sheets = RS.sheets(self.db, self.doc, lay, used)
        for s in self.sheets:
            s.edits = edits
        self.scenes.clear()
        self._fill_page_list()
        i = min(cur, len(self.sheets) - 1)
        self.pages.setCurrentRow(i)
        self.show_page(i)

    def _key(self, i: int | None = None) -> int:
        return 0 if self.doc is not None else (self.cur_index() if i is None else i)

    # ------------------------------------------------------------------
    def scene(self, i: int) -> SheetScene:
        if i not in self.scenes:
            sc = SheetScene(self.sheets[i], self.show_room, self.color, self.b_edit.isChecked(),
                            design=self.b_design.isChecked(), page_no=i + 1, pages=len(self.sheets))
            sc.snap, sc.show_grid, sc.grid_size = self.grid_opts["snap"], self.grid_opts["show"], self.grid_opts["size"]
            sc.edited.connect(self._edited)
            sc.selection_box.connect(self._box_selected)
            sc.box_geometry.connect(self._box_moved)
            sc.request_edit_text.connect(lambda bid: self.design.edit_text(bid))
            sc.request_delete.connect(self.delete_box)
            sc.table_resize.connect(self._table_resized)
            self.scenes[i] = sc
        return self.scenes[i]

    # ------------------------------------------------------------------ تصميم الورقة
    def cur_index(self) -> int:
        return max(0, self.pages.currentRow())

    def cur_sheet(self):
        return self.sheets[self.cur_index()]

    def cur_scene(self) -> SheetScene:
        return self.scene(self.cur_index())

    def is_dirty(self, i: int | None = None) -> bool:
        i = self._key(i)
        return self._json.dumps(self.sheets[i].layout, sort_keys=True) != self.saved_layouts.get(i)

    def _design_mode(self, on: bool):
        if on and self.b_edit.isChecked():
            self.b_edit.setChecked(False)
        for sc in self.scenes.values():
            sc.set_design(on)
        self.design.setVisible(on)
        if on:
            self.design.sync()
            self.hint.setText("وضع التصميم: «إضافة نص» ثم اسحبه إلى مكانه (يلتصق بالشبكة)، وانقر مرتين لكتابته. "
                              "اسحب زاويته الزرقاء لتغيير حجمه. التعديلات للطباعة فقط حتى تحفظها في قالب.")
        self.view.viewport().update()

    def apply_layout_change(self, fn, rebuild=True):
        i = self._key()
        sh = self.sheets[self.cur_index()]
        before = self._json.dumps(sh.layout)
        fn(sh.layout)
        if self._json.dumps(sh.layout) == before:
            return
        self.undo_stack.setdefault(i, []).append(before)
        self.redo_stack[i] = []
        if self.doc is not None:
            if rebuild:
                self._after_doc_change()
            return
        if rebuild:
            self._rebuild_current()

    def _after_doc_change(self):
        from PySide6.QtCore import QTimer

        def go():
            self._repaginate()
            if self.design.isVisible():
                self.design.sync()
        QTimer.singleShot(0, go)

    def _rebuild_current(self):
        from PySide6.QtCore import QTimer

        def go():
            sc = self.cur_scene()
            sc.rebuild()
            self.view.set_scene(sc)
            self.view.viewport().update()
            if self.design.isVisible():
                self.design.sync()
        QTimer.singleShot(0, go)

    def undo(self):
        self._undo_redo(self.undo_stack, self.redo_stack)

    def redo(self):
        self._undo_redo(self.redo_stack, self.undo_stack)

    def _undo_redo(self, src, dst):
        i = self._key()
        st = src.get(i) or []
        if not st:
            return
        cur = self.sheets[self.cur_index()]
        dst.setdefault(i, []).append(self._json.dumps(cur.layout))
        lay = self._json.loads(st.pop())
        if self.doc is not None:
            self._repaginate(lay)
            if self.design.isVisible():
                self.design.sync()
            return
        cur.layout = lay
        self._rebuild_current()

    def select_box(self, bid: str):
        from PySide6.QtCore import QTimer

        def go():
            sc = self.cur_scene()
            sc.clearSelection()
            if bid in sc.boxes:
                sc.boxes[bid].setSelected(True)
                sc.setFocusItem(sc.boxes[bid])
            self.design.select_box(bid)
        QTimer.singleShot(10, go)

    def _box_selected(self, bid: str):
        if bid or not any(b.isSelected() for b in self.cur_scene().boxes.values()):
            self.design.select_box(bid)

    def _box_moved(self, bid: str, geo: dict):
        def fn(l):
            for b in l.get("boxes", []):
                if b["id"] == bid:
                    b.update(geo)
        # الحركة ظاهرة أصلاً: لا داعي لإعادة الرسم، إلا عند تغيير الحجم (لتحديث مركز الدوران)
        self.apply_layout_change(fn, rebuild=False)
        self.design.select_box(bid)

    def delete_box(self, bid: str):
        if bid:
            self.apply_layout_change(lambda l: l.__setitem__("boxes", [b for b in l.get("boxes", []) if b["id"] != bid]))
            self.design.select_box("")

    def _table_resized(self, kind: str, a: int, b: int, frac: float):
        frac = max(0.08, min(0.92, frac))
        key = "col_weights" if kind == "col" else "row_weights"

        def fn(l):
            w = l["table"].setdefault(key, {})
            wa, wb = float(w.get(str(a), 1.0)), float(w.get(str(b), 1.0))
            tot = wa + wb
            # للأعمدة: الحد السفلي (lo) من جهة العمود b (يسار)، فالنسبة تخص b
            if kind == "col":
                w[str(b)], w[str(a)] = round(tot * frac, 3), round(tot * (1 - frac), 3)
            else:
                w[str(a)], w[str(b)] = round(tot * frac, 3), round(tot * (1 - frac), 3)
        self.apply_layout_change(fn)

    def set_grid(self, show=None, snap=None, size=None):
        if show is not None:
            self.grid_opts["show"] = show
        if snap is not None:
            self.grid_opts["snap"] = snap
        if size is not None:
            self.grid_opts["size"] = float(size)
        for sc in self.scenes.values():
            sc.snap, sc.show_grid, sc.grid_size = self.grid_opts["snap"], self.grid_opts["show"], self.grid_opts["size"]
        self.view.viewport().update()

    def reload_layouts(self, keep_current=False):
        """يعيد تحميل التصميم الفعلي (المحفوظ) لكل الأوراق بعد الحفظ أو الإرجاع."""
        from ..exporters import layout as LL
        if self.doc is not None:
            lay, used = LL.effective(self.db, self.sheets[0].kind)
            self.saved_layouts[0] = self._json.dumps(lay, sort_keys=True)
            self.undo_stack[0], self.redo_stack[0] = [], []
            self._repaginate(lay, used)
            if self.design.isVisible():
                self.design.sync()
            return
        for i, sh in enumerate(self.sheets):
            if keep_current and i == self.cur_index():
                continue
            sh.layout, sh.layout_scopes = LL.effective(self.db, sh.kind, sh.level_id, sh.section_id)
            self.saved_layouts[i] = self._json.dumps(sh.layout, sort_keys=True)
            self.undo_stack[i], self.redo_stack[i] = [], []
        self.scenes.clear()
        self.show_page(self.cur_index())
        if self.design.isVisible():
            self.design.sync()

    def preflight(self, scenes) -> bool:
        """قبل الطباعة: حقول بلا قيمة، أو حصص في أعمدة مخفية — تنبيه بدل طباعة ناقصة دون علم."""
        msgs = []
        for sc in scenes:
            miss = sc.missing_fields()
            if miss:
                msgs.append(f"{sc.sheet.name}: حقول بلا قيمة: " + "، ".join(L.PLACEHOLDERS.get(m, m) for m in miss))
            if sc.hidden_with_data:
                msgs.append(f"{sc.sheet.name}: حصص في المخفي لن تُطبع: " + "، ".join(sc.hidden_with_data))
        if not msgs:
            return True
        box = QMessageBox(QMessageBox.Warning, "قبل الطباعة",
                          "انتبه:\n\n• " + "\n• ".join(msgs[:12]) + ("\n…" if len(msgs) > 12 else ""), parent=self)
        go = box.addButton("متابعة رغم ذلك", QMessageBox.AcceptRole)
        box.addButton("رجوع للتعديل", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is go

    def all_scenes(self):
        return [self.scene(i) for i in range(len(self.sheets))]

    def show_page(self, i):
        if 0 <= i < len(self.sheets):
            self.view.set_scene(self.scene(i))
            if getattr(self, "design", None) is not None and self.design.isVisible():
                self.design.sync()

    def _fit(self):
        self.view.fit = True
        self.view.apply_zoom()

    def _opts(self):
        self.show_room, self.color = self.chk_room.isChecked(), self.chk_color.isChecked()
        self.db.set_setting("print_show_room", int(self.show_room))
        self.db.set_setting("print_color", int(self.color))
        self.scenes.clear()
        self.show_page(max(0, self.pages.currentRow()))

    def _edit_mode(self, on):
        if on and self.b_design.isChecked():
            self.b_design.setChecked(False)
        for sc in self.scenes.values():
            sc.set_edit_mode(on)

    PRINT_ONLY = ("cell:", "ph:", "day:", "c:", "h:", "p:", "cap:", "rpt_title", "pageno", "merge:", "ctext:")

    def _field_edits(self):
        seen, out = set(), []
        for s in self.sheets:
            for k in s.edits:
                if not k.startswith(self.PRINT_ONLY) and (id(s.edits), k) not in seen:
                    seen.add((id(s.edits), k))
                    out.append((s, k))
        return out

    def _edited(self):
        self.b_save.setEnabled(bool(self._field_edits()))

    def save_edits(self) -> bool:
        edits = self._field_edits()
        if not edits:
            info(self, "لا توجد تعديلات على نصوص القالب.\nتعديلات خانات الجدول تخص هذه الطباعة فقط.")
            return True
        box = QMessageBox(QMessageBox.Question, "حفظ التعديلات",
                          "أين تريد حفظ تعديلات النصوص (الرأس، المقرر، الملاحظة، التوقيعات)؟\n"
                          "تعديلات خانات الجدول تبقى لهذه الطباعة فقط.", parent=self)
        b_lvl = box.addButton("في قالب التقارير" if self.doc is not None else "في قالب هذا الطور",
                              QMessageBox.AcceptRole)
        b_all = box.addButton("في قالب كل الأوراق" if self.doc is not None else "في قالب كل الأطوار",
                              QMessageBox.AcceptRole)
        b_once = box.addButton("لهذه الطباعة فقط", QMessageBox.RejectRole)
        box.addButton("إلغاء", QMessageBox.DestructiveRole)
        box.exec()
        ch = box.clickedButton()
        if ch is b_once:
            self.b_save.setEnabled(False)
            return True
        if ch not in (b_lvl, b_all):
            return False
        done_scopes = set()
        for s, k in edits:
            new_raw = O.unfill(s.edits[k], s.raw.get(k, ""), s.values)
            scope = "global" if (ch is b_all and k in O.COMMON) else s.scope
            if (scope, k) in done_scopes:
                continue
            O.save_template_fields(self.db, scope, {k: new_raw})
            done_scopes.add((scope, k))
        # تحديث كل الأوراق المفتوحة بالقالب الجديد
        for s in self.sheets:
            s.raw = O.template_fields(self.db, s.kind, s.level_id)
            s.fields = {k: O.fill(v, s.values) for k, v in s.raw.items()}
            for k in [k for k in s.edits if not k.startswith(self.PRINT_ONLY)]:
                if s.edits[k] == s.fields.get(k):
                    s.edits.pop(k)
        self.scenes.clear()
        self.show_page(max(0, self.pages.currentRow()))
        self.b_save.setEnabled(bool(self._field_edits()))
        info(self, "تم حفظ التعديلات في القالب.")
        return True

    def _unsaved_design(self) -> bool:
        dirty = [i for i in ([0] if self.doc is not None else range(len(self.sheets))) if self.is_dirty(i)]
        if not dirty:
            return True
        box = QMessageBox(QMessageBox.Question, "تصميم غير محفوظ",
                          "في تصميم الورقة تعديلات لم تُحفظ في قالب. ستضيع عند الإغلاق.\n"
                          "احفظها من «تصميم الورقة ← القالب» إن أردت استعمالها لاحقاً.", parent=self)
        close = box.addButton("إغلاق دون حفظ التصميم", QMessageBox.AcceptRole)
        box.addButton("رجوع", QMessageBox.RejectRole)
        box.exec()
        return box.clickedButton() is close

    def closeEvent(self, e):
        if not self._unsaved_design():
            e.ignore()
            return
        if self._field_edits() and self.b_save.isEnabled():
            if not self.save_edits():
                e.ignore()
                return
        super().closeEvent(e)

    def reject(self):
        if not self._unsaved_design():
            return
        if self._field_edits() and self.b_save.isEnabled():
            if not self.save_edits():
                return
        super().reject()

    # ------------------------------------------------------------------ الإخراج
    def do_print(self):
        if not self.preflight(self.all_scenes()):
            return
        try:
            print_scenes(self.all_scenes(), self)
        except Exception as e:
            error(self, f"تعذرت الطباعة: {e}")

    def _default_dir(self) -> str:
        return self.db.get_setting("print_dir", "") or str(Path.home() / "Documents")

    def file_name(self, s: O.Sheet, ext: str) -> str:
        if self.doc is not None:
            return O.safe_filename(self.doc.name or self.doc.title) + "." + ext
        return O.safe_filename(f"{s.name}_الأسبوع{O.week_number(self.db, s.ws)}") + "." + ext

    def do_pdf(self):
        if not self.preflight(self.all_scenes()):
            return
        export_pdf(self, self.db, self.all_scenes(), self.one_file or self.doc is not None,
                   name=self.file_name(self.sheets[0], "pdf") if self.doc is not None else None)

    def current_index(self) -> int:
        sc = self.view.scene()
        for i, x in self.scenes.items():
            if x is sc:
                return i
        return 0

    def preview_pdf(self):
        """الورقة المعروضة كملف PDF مؤقت يُفتح في قارئ PDF — نفس محرك الحفظ والطباعة."""
        import tempfile
        i = self.current_index()
        path = Path(tempfile.gettempdir()) / f"dpp_preview_{i + 1}.pdf"
        try:
            render_to_pdf([self.scene(i)], str(path))
        except Exception as e:
            error(self, f"تعذر إنشاء المعاينة: {e}")
            return
        _open(path)

    def do_xlsx(self):
        if self.doc is not None:
            path, _ = QFileDialog.getSaveFileName(self, "حفظ Excel", str(Path(self._default_dir()) /
                                                                      self.file_name(self.sheets[0], "xlsx")), "*.xlsx")
            if not path:
                return
            if not path.lower().endswith(".xlsx"):
                path += ".xlsx"
            try:
                fn = getattr(self.doc, "xlsx", None)
                if fn:
                    fn(path)
                else:
                    from ..exporters import report_sheet as RS
                    RS.to_xlsx(self.doc, path, self.sheets[0].layout)
            except Exception as e:
                error(self, f"تعذر الحفظ: {e}")
                return
            _open(path)
            return
        name = self.file_name(self.sheets[0], "xlsx") if len(self.sheets) == 1 else "برامج_الأسبوع.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "حفظ Excel", str(Path(self._default_dir()) / name), "*.xlsx")
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            O.to_xlsx(self.sheets, path, self.show_room, self.color)
        except Exception as e:
            error(self, f"تعذر الحفظ: {e}")
            return
        _open(path)


def _open(path):
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def export_pdf(parent, db, scenes: list[SheetScene], one_file=False, folder: str | None = None,
               name: str | None = None) -> list[str]:
    """ملف PDF لكل ورقة (افتراضياً) أو ملف واحد لكل الأوراق."""
    if not scenes:
        return []
    base = db.get_setting("print_dir", "") or str(Path.home() / "Documents")

    def fname(s):
        return O.safe_filename(f"{s.name}_الأسبوع{O.week_number(db, s.ws)}") + ".pdf"
    try:
        if len(scenes) == 1 or one_file:
            name = name or (fname(scenes[0].sheet) if len(scenes) == 1 else "برامج_الأسبوع.pdf")
            if folder:
                path = str(Path(folder) / name)
            else:
                path, _ = QFileDialog.getSaveFileName(parent, "حفظ PDF", str(Path(base) / name), "*.pdf")
                if not path:
                    return []
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
            render_to_pdf(scenes, path)
            db.set_setting("print_dir", str(Path(path).parent))
            if not folder:
                _open(path)
            return [path]
        if not folder:
            folder = QFileDialog.getExistingDirectory(parent, "اختر المجلد (ملف لكل قسم)", base)
            if not folder:
                return []
        out, seen = [], set()
        for sc in scenes:
            n = fname(sc.sheet)
            stem, k = n[:-4], 2
            while n in seen:
                n, k = f"{stem}_{k}.pdf", k + 1
            seen.add(n)
            out.append(render_to_pdf([sc], str(Path(folder) / n)))
        db.set_setting("print_dir", folder)
        if parent is not None:
            info(parent, f"تم حفظ {len(out)} ملف PDF في:\n{folder}")
            _open(folder)
        return out
    except Exception as e:
        if parent is not None:
            error(parent, f"تعذر حفظ PDF: {e}")
        return []


# ====================================================================== نافذة الطباعة
PRINT_KINDS = [("section", "برنامج قسم"), ("all_sections", "كل الأقسام"), ("level", "أقسام طور"),
               ("teacher", "برنامج أستاذ"), ("all_teachers", "كل الأساتذة"), ("room", "برنامج قاعة")]


class PrintDialog(QDialog):
    """اختيار ماذا يُطبع: قسم، كل الأقسام، طور، أستاذ، كل الأساتذة، قاعة — لأسبوع أو عدة أسابيع."""

    def __init__(self, ctx, ws, parent=None, kind="section", target=None):
        super().__init__(parent)
        from ..services.grid import week_of_number
        self.ctx, self.db = ctx, ctx.db
        O.seed_decrees_once(self.db)
        self.setWindowTitle("طباعة البرنامج")
        self.setMinimumWidth(520)
        form = QFormLayout(self)
        self.kind = QComboBox()
        for k, lab in PRINT_KINDS:
            self.kind.addItem(lab, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(kind)))
        form.addRow("ماذا تطبع", self.kind)
        self.target = QComboBox()
        self.target.setMinimumWidth(320)
        self.target_lbl = QLabel("القسم")
        form.addRow(self.target_lbl, self.target)
        cur = O.week_number(self.db, ws)
        self.w_from, self.w_to = QComboBox(), QComboBox()
        for n in range(1, 56):
            w = week_of_number(self.db, n)
            lab = f"الأسبوع {n} ({w.strftime('%d/%m')})"
            self.w_from.addItem(lab, n)
            self.w_to.addItem(lab, n)
        self.w_from.setCurrentIndex(max(0, cur - 1))
        self.w_to.setCurrentIndex(max(0, cur - 1))
        self.w_from.currentIndexChanged.connect(
            lambda i: self.w_to.setCurrentIndex(i) if self.w_to.currentIndex() < i else None)
        wh = QHBoxLayout()
        wh.addWidget(self.w_from)
        wh.addWidget(QLabel("إلى"))
        wh.addWidget(self.w_to)
        form.addRow("الأسبوع", wh)
        self.chk_room = QCheckBox("إظهار القاعة في الخانات")
        self.chk_room.setChecked(self.db.get_setting("print_show_room", "1") == "1")
        self.chk_color = QCheckBox("بالألوان (الافتراضي أبيض وأسود)")
        self.chk_color.setChecked(self.db.get_setting("print_color", "0") == "1")
        self.chk_one = QCheckBox("كل الأوراق في ملف PDF واحد (الافتراضي ملف لكل قسم)")
        self.chk_one.setChecked(self.db.get_setting("print_one_file", "0") == "1")
        form.addRow("", self.chk_room)
        form.addRow("", self.chk_color)
        form.addRow("", self.chk_one)
        self.count_lbl = QLabel()
        self.count_lbl.setObjectName("Muted")
        form.addRow("", self.count_lbl)
        bb = QDialogButtonBox()
        self.b_prev = bb.addButton("معاينة", QDialogButtonBox.AcceptRole)
        self.b_pdf = bb.addButton("PDF مباشرة", QDialogButtonBox.ActionRole)
        self.b_print = bb.addButton("طباعة مباشرة", QDialogButtonBox.ActionRole)
        bb.addButton("إلغاء", QDialogButtonBox.RejectRole)
        self.b_prev.setIcon(icon("mdi6.eye-outline"))
        self.b_pdf.setIcon(icon("mdi6.file-pdf-box"))
        self.b_print.setIcon(icon("mdi6.printer"))
        self.b_prev.setDefault(True)
        self.action = None
        self.b_prev.clicked.connect(lambda: self._go("preview"))
        self.b_pdf.clicked.connect(lambda: self._go("pdf"))
        self.b_print.clicked.connect(lambda: self._go("print"))
        bb.rejected.connect(self.reject)
        form.addRow(bb)
        self.kind.currentIndexChanged.connect(self._fill_targets)
        for w in (self.target, self.w_from, self.w_to):
            w.currentIndexChanged.connect(self._count)
        self._fill_targets()
        if target is not None:
            i = self.target.findData(target)
            if i >= 0:
                self.target.setCurrentIndex(i)

    def _fill_targets(self):
        k = self.kind.currentData()
        self.target.blockSignals(True)
        self.target.clear()
        fids = self.ctx.formation_ids()
        q = ",".join("?" * len(fids)) or "NULL"
        if k == "section":
            self.target_lbl.setText("القسم")
            for r in self.db.q(f"SELECT id, short, name FROM sections WHERE formation_id IN ({q}) ORDER BY sort, id",
                               fids):
                self.target.addItem(r["short"] or r["name"], r["id"])
        elif k == "level":
            self.target_lbl.setText("الطور")
            for r in self.db.q(f"""SELECT DISTINCT l.id, l.code, l.name FROM levels l JOIN sections s ON s.level_id=l.id
                                   WHERE s.formation_id IN ({q}) ORDER BY l.sort, l.id""", fids):
                self.target.addItem(f"{r['code'] or ''} — {r['name']}", r["id"])
        elif k == "teacher":
            self.target_lbl.setText("الأستاذ")
            for r in self.db.q("SELECT id, full_name, rank FROM teachers WHERE active=1 ORDER BY full_name"):
                self.target.addItem(f"{r['full_name']}" + (f" ({r['rank']})" if r["rank"] else ""), r["id"])
        elif k == "room":
            self.target_lbl.setText("القاعة")
            for r in self.db.q("SELECT id, name FROM rooms ORDER BY name"):
                self.target.addItem(r["name"], r["id"])
        else:
            self.target_lbl.setText("")
        self.target.setVisible(k in ("section", "level", "teacher", "room"))
        self.target.blockSignals(False)
        self._count()

    def weeks(self):
        from ..services.grid import week_of_number
        a, b = self.w_from.currentData(), self.w_to.currentData()
        return [week_of_number(self.db, n) for n in range(a, max(a, b) + 1)]

    def jobs(self) -> list[tuple[str, int, object]]:
        k, t = self.kind.currentData(), self.target.currentData()
        out = []
        for ws in self.weeks():
            if k == "section" and t:
                out.append(("section", t, ws))
            elif k in ("all_sections", "level"):
                lvl = t if k == "level" else None
                out += [("section", s["id"], ws) for s in
                        O.sections_with_sessions(self.db, ws, self.ctx.formation_ids(), lvl)]
            elif k == "teacher" and t:
                out.append(("teacher", t, ws))
            elif k == "all_teachers":
                out += [("teacher", r["id"], ws) for r in O.teachers_with_sessions(self.db, ws)]
            elif k == "room" and t:
                out.append(("room", t, ws))
        return out

    def _count(self):
        n = len(self.jobs())
        self.count_lbl.setText(f"عدد الأوراق: {n}" if n else "لا توجد حصص في هذا الاختيار")

    def _go(self, action):
        self.action = action
        for key, chk in (("print_show_room", self.chk_room), ("print_color", self.chk_color),
                         ("print_one_file", self.chk_one)):
            self.db.set_setting(key, int(chk.isChecked()))
        self.accept()


def open_print(ctx, ws, parent=None, kind="section", target=None):
    """نقطة الدخول من الجدول العام والقائمة: نافذة الاختيار ثم المعاينة أو PDF أو الطباعة."""
    from PySide6.QtWidgets import QApplication
    dlg = PrintDialog(ctx, ws, parent, kind, target)
    if dlg.exec() != QDialog.Accepted or not dlg.action:
        return None
    jobs = dlg.jobs()
    if not jobs:
        info(parent, "لا توجد حصص لطباعتها في هذا الاختيار.")
        return None
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        sheets = [O.build(ctx.db, k, t, ws) for k, t, ws in jobs]
    finally:
        QApplication.restoreOverrideCursor()
    room, color, one = dlg.chk_room.isChecked(), dlg.chk_color.isChecked(), dlg.chk_one.isChecked()
    if dlg.action == "preview":
        pv = PreviewDialog(ctx.db, sheets, parent, room, color, one)
        pv.exec()
        return pv
    scenes = [SheetScene(s, room, color) for s in sheets]
    if dlg.action == "pdf":
        export_pdf(parent, ctx.db, scenes, one)
    else:
        try:
            print_scenes(scenes, parent)
        except Exception as e:
            error(parent, f"تعذرت الطباعة: {e}")
    return None


__all__ = ["SheetScene", "PreviewDialog", "PrintDialog", "open_print", "render_to_pdf", "export_pdf", "QSizeF"]
