"""محرر قوالب الطباعة: مربعات نص حرة، شبكة والتصاق، تعديل الجدول للطباعة فقط، معاينة وPDF."""
from __future__ import annotations

import copy
import json

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QFileDialog, QFontComboBox,
                               QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox,
                               QStackedWidget, QVBoxLayout, QWidget)

from dpp.models import DAY_NAMES, Level, Section, Training
from dpp.printing import output
from dpp.printing import template as tpl
from dpp.printing.render import (RenderContext, build_table_data, render_page, sample_table_data,
                                 table_geometry)
from dpp.services import planner, structure
from dpp.ui.theme import T, subject_color
from dpp.ui.widgets import Page, ask_form, button, confirm, info, warn

MIN_MM = 3.0


class PageCanvas(QWidget):
    """لوحة الصفحة: تعرض القالب بنفس محرك الطباعة، مع شبكة خفيفة (لا تُطبع) ومقابض التحرير."""
    selectionChanged = Signal(str)
    edited = Signal()

    def __init__(self):
        super().__init__()
        self.layout_data: dict = tpl.default_layout()
        self.ctx = RenderContext({}, sample_table_data())
        self.k = 2.4
        self.pad = 24
        self.selected = ""
        self._drag = None
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    # ---------------------------------------------------- إعداد
    def set_data(self, layout: dict, ctx: RenderContext) -> None:
        self.layout_data, self.ctx = layout, ctx
        if not tpl.find_item(layout, self.selected):
            self.selected = ""
        self.relayout()

    def relayout(self) -> None:
        w, h = tpl.page_mm(self.layout_data)
        self.setFixedSize(int(w * self.k + 2 * self.pad), int(h * self.k + 2 * self.pad))
        self.update()

    def set_zoom(self, k: float) -> None:
        self.k = max(1.0, min(8.0, k))
        self.relayout()

    def mm(self, pos) -> tuple[float, float]:
        return (pos.x() - self.pad) / self.k, (pos.y() - self.pad) / self.k

    def snap(self, v: float, force: bool = False) -> float:
        g = self.layout_data["grid"]
        if g.get("snap", True) or force:
            size = max(0.5, float(g.get("size", 5)))
            return round(v / size) * size
        return round(v, 1)

    # ---------------------------------------------------- الرسم
    def paintEvent(self, _ev) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#CBD5E1"))
        pw, ph = tpl.page_mm(self.layout_data)
        page = QRectF(self.pad, self.pad, pw * self.k, ph * self.k)
        p.fillRect(page.translated(3, 3), QColor(0, 0, 0, 40))
        p.fillRect(page, QColor("white"))
        g = self.layout_data["grid"]
        if g.get("show", True):
            size = max(1.0, float(g.get("size", 5)))
            p.setPen(QPen(QColor(148, 163, 184, 55), 1))
            x = 0.0
            while x <= pw:
                p.drawLine(QPointF(self.pad + x * self.k, page.top()), QPointF(self.pad + x * self.k, page.bottom()))
                x += size
            y = 0.0
            while y <= ph:
                p.drawLine(QPointF(page.left(), self.pad + y * self.k), QPointF(page.right(), self.pad + y * self.k))
                y += size
        m = self.layout_data["page"].get("margins", [10, 10, 10, 10])  # أعلى، يمين، أسفل، يسار
        p.setPen(QPen(QColor("#60A5FA"), 1, Qt.DashLine))
        p.drawRect(QRectF(self.pad + m[3] * self.k, self.pad + m[0] * self.k,
                          (pw - m[1] - m[3]) * self.k, (ph - m[0] - m[2]) * self.k))
        render_page(p, self.layout_data, self.ctx, self.k, self.pad, self.pad)
        it = tpl.find_item(self.layout_data, self.selected)
        if it:
            r = QRectF(self.pad + it["x"] * self.k, self.pad + it["y"] * self.k, it["w"] * self.k, it["h"] * self.k)
            p.setPen(QPen(QColor(T["accent"]), 1.5, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setBrush(QColor(T["accent"]))
            for hp in (r.bottomRight(), r.bottomLeft()):
                p.drawRect(QRectF(hp.x() - 4, hp.y() - 4, 8, 8))
        p.end()

    # ---------------------------------------------------- الفأرة
    def _items_at(self, x, y) -> list[dict]:
        out = [it for it in self.layout_data["items"]
               if it["x"] <= x <= it["x"] + it["w"] and it["y"] <= y <= it["y"] + it["h"]]
        out.sort(key=lambda i: i["type"] == "table")  # النصوص فوق الجدول
        return out

    def _table_handle(self, it: dict, x: float, y: float):
        g = table_geometry(it, self.ctx.table)
        tol = 1.4
        if not (it["y"] <= y <= it["y"] + it["h"]):
            return None
        cols = g.cols
        for i in range(len(cols) - 1):
            right, left = cols[i], cols[i + 1]
            if abs(x - right[1]) < tol:
                return ("col", right[0], left[0])
        for i in range(len(g.rows) - 1):
            if abs(y - g.rows[i][2]) < tol and it["x"] <= x <= it["x"] + it["w"]:
                return ("row", g.rows[i][0], g.rows[i + 1][0])
        return None

    def _handle_at(self, it: dict, pos) -> str | None:
        r = QRectF(self.pad + it["x"] * self.k, self.pad + it["y"] * self.k, it["w"] * self.k, it["h"] * self.k)
        for name, hp in (("br", r.bottomRight()), ("bl", r.bottomLeft())):
            if abs(pos.x() - hp.x()) <= 6 and abs(pos.y() - hp.y()) <= 6:
                return name
        return None

    def mousePressEvent(self, ev) -> None:
        pos = ev.position()
        x, y = self.mm(pos)
        sel = tpl.find_item(self.layout_data, self.selected)
        if sel and self._handle_at(sel, pos):
            self._drag = ("resize", self._handle_at(sel, pos), x, y, copy.deepcopy(sel))
            return
        for it in self._items_at(x, y):
            if it["type"] == "table":
                h = self._table_handle(it, x, y)
                if h:
                    self.selected = it["id"]
                    self.selectionChanged.emit(self.selected)
                    self._drag = (h[0], h, x, y, copy.deepcopy(it))
                    return
            self.selected = it["id"]
            self.selectionChanged.emit(self.selected)
            self._drag = ("move", None, x, y, copy.deepcopy(it))
            self.update()
            return
        self.selected = ""
        self.selectionChanged.emit("")
        self._drag = None
        self.update()

    def mouseMoveEvent(self, ev) -> None:
        pos = ev.position()
        x, y = self.mm(pos)
        if not self._drag:
            cursor = Qt.ArrowCursor
            sel = tpl.find_item(self.layout_data, self.selected)
            if sel and self._handle_at(sel, pos):
                cursor = Qt.SizeFDiagCursor
            else:
                for it in self._items_at(x, y):
                    if it["type"] == "table":
                        h = self._table_handle(it, x, y)
                        if h:
                            cursor = Qt.SplitHCursor if h[0] == "col" else Qt.SplitVCursor
                            break
                    cursor = Qt.SizeAllCursor
                    break
            self.setCursor(cursor)
            return
        mode, info_, x0, y0, orig = self._drag
        it = tpl.find_item(self.layout_data, orig["id"])
        dx, dy = x - x0, y - y0
        if mode == "move":
            it["x"], it["y"] = self.snap(orig["x"] + dx), self.snap(orig["y"] + dy)
        elif mode == "resize":
            if info_ == "br":
                it["w"] = max(MIN_MM, self.snap(orig["x"] + orig["w"] + dx) - orig["x"])
            else:
                nx = min(self.snap(orig["x"] + dx), orig["x"] + orig["w"] - MIN_MM)
                it["w"], it["x"] = orig["x"] + orig["w"] - nx, nx
            it["h"] = max(MIN_MM, self.snap(orig["y"] + orig["h"] + dy) - orig["y"])
        elif mode == "col":
            self._drag_col(it, orig, info_, dx)
        elif mode == "row":
            self._drag_row(it, orig, info_, dy)
        self.update()

    def _drag_col(self, it, orig, info_, dx) -> None:
        _, right_key, left_key = info_
        g = table_geometry(orig, self.ctx.table)
        width = {k: b - a for k, a, b in g.cols}
        if right_key == "__day__" and orig.get("day_col_side", "right") == "right":
            it["day_col_w"] = max(MIN_MM, orig["day_col_w"] - dx)
            return
        if left_key == "__day__":
            it["day_col_w"] = max(MIN_MM, orig["day_col_w"] + dx)
            return
        wr, wl = width[right_key] - dx, width[left_key] + dx
        if wr < MIN_MM or wl < MIN_MM:
            return
        weights = {c.key: width[c.key] for c in g.timecols}
        if right_key in weights:
            weights[right_key] = wr
        if left_key in weights:
            weights[left_key] = wl
        for i, e in enumerate(it.get("extra_cols", [])):
            key = f"__extra{i}__"
            if key == right_key:
                e["width"] = wr
            if key == left_key:
                e["width"] = wl
        it["col_weights"] = {k: round(v, 2) for k, v in weights.items()}

    def _drag_row(self, it, orig, info_, dy) -> None:
        _, top_key, bottom_key = info_
        g = table_geometry(orig, self.ctx.table)
        height = {k: b - a for k, a, b in g.rows}
        if top_key == "header":
            it["header_h"] = max(MIN_MM, orig["header_h"] + dy)
            return
        ht, hb = height[top_key] + dy, height[bottom_key] - dy
        if ht < MIN_MM or hb < MIN_MM:
            return
        weights = {str(k): v for k, v in height.items() if k != "header"}
        weights[str(top_key)], weights[str(bottom_key)] = ht, hb
        it["row_weights"] = {k: round(v, 2) for k, v in weights.items()}

    def mouseReleaseEvent(self, _ev) -> None:
        if self._drag:
            self._drag = None
            self.edited.emit()

    def keyPressEvent(self, ev) -> None:
        it = tpl.find_item(self.layout_data, self.selected)
        if not it:
            return super().keyPressEvent(ev)
        step = float(self.layout_data["grid"].get("size", 5)) if self.layout_data["grid"].get("snap") else 0.5
        moves = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}
        if ev.key() in moves:
            dx, dy = moves[ev.key()]
            it["x"] += dx
            it["y"] += dy
            self.update()
            self.edited.emit()
        elif ev.key() == Qt.Key_Delete and it["type"] == "text":
            self.layout_data["items"].remove(it)
            self.selected = ""
            self.selectionChanged.emit("")
            self.update()
            self.edited.emit()
        else:
            super().keyPressEvent(ev)


def color_button(get, set_, parent) -> QPushButton:
    b = QPushButton()
    b.setFixedWidth(60)

    def paint():
        c = get() or "#FFFFFF"
        b.setStyleSheet(f"background: {c}; border: 1px solid #94A3B8; border-radius: 4px;")
        b.setText("" if get() else "—")

    def pick():
        c = QColorDialog.getColor(QColor(get() or "#FFFFFF"), parent)
        if c.isValid():
            set_(c.name())
            paint()
    b.clicked.connect(pick)
    b.repaint_color = paint
    paint()
    return b


class PrintPage(Page):
    title = "الطباعة"
    subtitle = "قوالب قابلة للتعديل لكل طور ولكل فرع — الشبكة والإطارات الزرقاء لا تُطبع"

    def __init__(self, main):
        super().__init__(main)
        self.add_action("معاينة وطباعة", self.preview, primary=True)
        self.add_action("تصدير PDF للفرع", self.export_section)
        self.add_action("PDF لكل فروع الطور", self.export_level)
        self.layout_data = tpl.default_layout()
        self.undo_stack: list[str] = []
        self.redo_stack: list[str] = []
        self.dirty = False
        self._sync = False
        # ---- شريط النطاق
        bar = QHBoxLayout()
        self.training = QComboBox()
        self.level = QComboBox()
        self.section = QComboBox()
        self.week = QSpinBox()
        self.week.setRange(1, 200)
        self.week.setPrefix("أسبوع المعاينة ")
        self.scope = QComboBox()
        self.scope.addItem("القالب الافتراضي", "default")
        self.scope.addItem("قالب الطور", "level")
        self.scope.addItem("قالب الفرع", "section")
        self.training.currentIndexChanged.connect(self._fill_levels)
        self.level.currentIndexChanged.connect(self._fill_sections)
        self.section.currentIndexChanged.connect(self.load_scope)
        self.scope.currentIndexChanged.connect(self.load_scope)
        self.week.valueChanged.connect(self.update_ctx)
        for lbl, w in (("التكوين", self.training), ("الطور", self.level), ("الفرع", self.section),
                       ("", self.week), ("تحرير", self.scope)):
            if lbl:
                bar.addWidget(QLabel(lbl))
            w.setSizeAdjustPolicy(QComboBox.AdjustToContents) if isinstance(w, QComboBox) else None
            bar.addWidget(w)
        self.src_lbl = QLabel()
        self.src_lbl.setObjectName("Badge")
        bar.addWidget(self.src_lbl)
        bar.addStretch(1)
        self.root.addLayout(bar)
        # ---- شريط الأدوات
        tb = QHBoxLayout()
        tb.addWidget(button("حفظ القالب", self.save, primary=True))
        tb.addWidget(button("الرجوع للموروث", self.revert_inherited, danger=True))
        tb.addWidget(button("القالب المدمج", self.reset_builtin))
        tb.addWidget(button("نسخ إلى…", self.copy_to))
        tb.addWidget(button("تراجع", self.undo))
        tb.addWidget(button("إعادة", self.redo))
        tb.addWidget(button("نص جديد", self.add_text))
        self.grid_btn = QCheckBox("الشبكة")
        self.snap_btn = QCheckBox("الالتصاق بالشبكة")
        self.grid_size = QDoubleSpinBox()
        self.grid_size.setRange(1, 50)
        self.grid_size.setSuffix(" مم")
        self.grid_btn.toggled.connect(lambda v: self._grid("show", v))
        self.snap_btn.toggled.connect(lambda v: self._grid("snap", v))
        self.grid_size.valueChanged.connect(lambda v: self._grid("size", v))
        for w in (self.grid_btn, self.snap_btn, self.grid_size):
            tb.addWidget(w)
        tb.addStretch(1)
        tb.addWidget(button("−", lambda: self.canvas.set_zoom(self.canvas.k - 0.4)))
        tb.addWidget(button("+", lambda: self.canvas.set_zoom(self.canvas.k + 0.4)))
        self.root.addLayout(tb)
        # ---- اللوحة + الخصائص
        body = QHBoxLayout()
        self.props = QStackedWidget()
        self.props.setFixedWidth(330)
        self.props.addWidget(self._page_props())
        self.props.addWidget(self._text_props())
        self.props.addWidget(self._table_props())
        ps = QScrollArea()
        ps.setWidget(self.props)
        ps.setWidgetResizable(True)
        ps.setFixedWidth(350)
        ps.setFrameShape(QFrame.NoFrame)
        body.addWidget(ps)
        self.canvas = PageCanvas()
        self.canvas.selectionChanged.connect(self.on_select)
        self.canvas.edited.connect(self.on_canvas_edited)
        sc = QScrollArea()
        sc.setWidget(self.canvas)
        sc.setAlignment(Qt.AlignCenter)
        body.addWidget(sc, 1)
        self.root.addLayout(body, 1)

    # ================================================================ الخصائص
    def _page_props(self) -> QWidget:
        box = QGroupBox("الصفحة")
        f = QFormLayout(box)
        self.p_size = QComboBox()
        for k in tpl.PAGE_SIZES:
            self.p_size.addItem(k, k)
        self.p_orient = QComboBox()
        self.p_orient.addItem("أفقي", "landscape")
        self.p_orient.addItem("عمودي", "portrait")
        self.p_margins = []
        f.addRow("المقاس", self.p_size)
        f.addRow("الاتجاه", self.p_orient)
        for lbl in ("الهامش العلوي", "الهامش الأيمن", "الهامش السفلي", "الهامش الأيسر"):
            sp = QDoubleSpinBox()
            sp.setRange(0, 60)
            sp.setSuffix(" مم")
            sp.valueChanged.connect(self._apply_page)
            self.p_margins.append(sp)
            f.addRow(lbl, sp)
        self.p_size.currentIndexChanged.connect(self._apply_page)
        self.p_orient.currentIndexChanged.connect(self._apply_page)
        hint = QLabel("انقر عنصراً لتعديله. اسحب لتحريكه، المقبض الأخضر لتغيير الحجم، "
                      "وحدود أعمدة/صفوف الجدول لتغيير العرض والارتفاع. الأسهم للتحريك الدقيق، Delete للحذف.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        f.addRow(hint)
        return box

    def _text_props(self) -> QWidget:
        box = QGroupBox("مربع نص")
        f = QFormLayout(box)
        self.t_text = QPlainTextEdit()
        self.t_text.setFixedHeight(70)
        self.t_text.textChanged.connect(lambda: self._set("text", self.t_text.toPlainText()))
        self.t_field = QComboBox()
        self.t_field.addItem("إدراج حقل تلقائي…", None)
        for k, v in tpl.FIELDS.items():
            self.t_field.addItem(v, k)
        self.t_field.activated.connect(self._insert_field)
        self.t_font = QFontComboBox()
        self.t_font.currentFontChanged.connect(lambda fnt: self._set("font", fnt.family()))
        self.t_size = QDoubleSpinBox()
        self.t_size.setRange(4, 120)
        self.t_size.valueChanged.connect(lambda v: self._set("size", v))
        st = QHBoxLayout()
        self.t_bold = QCheckBox("غامق")
        self.t_italic = QCheckBox("مائل")
        self.t_bold.toggled.connect(lambda v: self._set("bold", v))
        self.t_italic.toggled.connect(lambda v: self._set("italic", v))
        st.addWidget(self.t_bold)
        st.addWidget(self.t_italic)
        self.t_color = color_button(lambda: self._cur().get("color") if self._cur() else "#000", lambda c: self._set("color", c), self)
        self.t_align = QComboBox()
        for k, v in (("right", "يمين"), ("center", "وسط"), ("left", "يسار")):
            self.t_align.addItem(v, k)
        self.t_align.currentIndexChanged.connect(lambda: self._set("align", self.t_align.currentData()))
        self.t_valign = QComboBox()
        for k, v in (("top", "أعلى"), ("middle", "وسط"), ("bottom", "أسفل")):
            self.t_valign.addItem(v, k)
        self.t_valign.currentIndexChanged.connect(lambda: self._set("valign", self.t_valign.currentData()))
        self.t_border = QDoubleSpinBox()
        self.t_border.setRange(0, 5)
        self.t_border.setSingleStep(0.1)
        self.t_border.setSuffix(" مم")
        self.t_border.valueChanged.connect(lambda v: self._set("border", v))
        self.t_bcolor = color_button(lambda: self._cur().get("border_color") if self._cur() else "#000", lambda c: self._set("border_color", c), self)
        self.t_bg = color_button(lambda: self._cur().get("bg") if self._cur() else "", lambda c: self._set("bg", c), self)
        rot = QHBoxLayout()
        self.t_rot = QSpinBox()
        self.t_rot.setRange(-180, 180)
        self.t_rot.setSuffix("°")
        self.t_rot.valueChanged.connect(lambda v: self._set("rotation", v))
        rot.addWidget(self.t_rot)
        for v, lbl in ((0, "أفقي"), (-90, "عمودي ↑"), (90, "عمودي ↓")):
            rot.addWidget(button(lbl, lambda _=False, v=v: self.t_rot.setValue(v)))
        self.t_geo = []
        geo = QHBoxLayout()
        for key in ("x", "y", "w", "h"):
            sp = QDoubleSpinBox()
            sp.setRange(0, 500)
            sp.setDecimals(1)
            sp.setPrefix(f"{key} ")
            sp.valueChanged.connect(lambda v, key=key: self._set(key, v))
            self.t_geo.append(sp)
            geo.addWidget(sp)
        f.addRow("النص", self.t_text)
        f.addRow("", self.t_field)
        f.addRow("الخط", self.t_font)
        f.addRow("الحجم", self.t_size)
        f.addRow("", st)
        f.addRow("اللون", self.t_color)
        f.addRow("المحاذاة", self.t_align)
        f.addRow("عمودياً", self.t_valign)
        f.addRow("الإطار", self.t_border)
        f.addRow("لون الإطار", self.t_bcolor)
        f.addRow("الخلفية", self.t_bg)
        f.addRow("الدوران", rot)
        f.addRow(geo)
        r1 = QHBoxLayout()
        r1.addWidget(button("توسيط أفقي", lambda: self._center("h")))
        r1.addWidget(button("توسيط عمودي", lambda: self._center("v")))
        f.addRow(r1)
        r2 = QHBoxLayout()
        r2.addWidget(button("تكرار", self.duplicate))
        r2.addWidget(button("حذف", self.delete_item, danger=True))
        f.addRow(r2)
        return box

    def _table_props(self) -> QWidget:
        box = QGroupBox("الجدول (مظهر الطباعة فقط — لا يغير البيانات)")
        f = QFormLayout(box)
        self.tb_spins = {}
        for key, lbl, lo, hi, step in (("header_size", "خط الرأس", 4, 30, 0.5), ("day_size", "خط الأيام", 4, 30, 0.5),
                                       ("cell_size", "خط الخلايا", 4, 30, 0.5), ("border", "سمك الحدود", 0, 3, 0.1),
                                       ("day_col_w", "عرض عمود الأيام", 5, 80, 1), ("header_h", "ارتفاع الرأس", 4, 40, 0.5)):
            sp = QDoubleSpinBox()
            sp.setRange(lo, hi)
            sp.setSingleStep(step)
            sp.valueChanged.connect(lambda v, key=key: self._set(key, v))
            self.tb_spins[key] = sp
            f.addRow(lbl, sp)
        self.tb_font = QFontComboBox()
        self.tb_font.currentFontChanged.connect(lambda fnt: self._set("font", fnt.family()))
        f.addRow("الخط", self.tb_font)
        self.tb_bcolor = color_button(lambda: self._cur().get("border_color") if self._cur() else "#000", lambda c: self._set("border_color", c), self)
        self.tb_hbg = color_button(lambda: self._cur().get("header_bg") if self._cur() else "", lambda c: self._set("header_bg", c), self)
        self.tb_dbg = color_button(lambda: self._cur().get("day_bg") if self._cur() else "", lambda c: self._set("day_bg", c), self)
        f.addRow("لون الحدود", self.tb_bcolor)
        f.addRow("خلفية الرأس", self.tb_hbg)
        f.addRow("خلفية الأيام", self.tb_dbg)
        self.tb_checks = {}
        for key, lbl in (("show_teacher", "إظهار لقب الأستاذ"), ("show_time", "إظهار الوقت"),
                         ("use_colors", "ألوان المواد حسب النوع")):
            cb = QCheckBox(lbl)
            cb.toggled.connect(lambda v, key=key: self._set(key, v))
            self.tb_checks[key] = cb
            f.addRow(cb)
        self.tb_side = QComboBox()
        self.tb_side.addItem("عمود الأيام يميناً", "right")
        self.tb_side.addItem("عمود الأيام يساراً", "left")
        self.tb_side.currentIndexChanged.connect(lambda: self._set("day_col_side", self.tb_side.currentData()))
        f.addRow(self.tb_side)
        self.tb_lunch = QLineEdit()
        self.tb_lunch.textChanged.connect(lambda v: self._set("lunch_label", v))
        f.addRow("نص الغداء", self.tb_lunch)
        f.addRow(QLabel("الأيام الظاهرة:"))
        self.tb_days = QListWidget()
        self.tb_days.setFixedHeight(120)
        self.tb_days.itemChanged.connect(self._days_changed)
        f.addRow(self.tb_days)
        f.addRow(QLabel("الأعمدة الظاهرة:"))
        self.tb_cols = QListWidget()
        self.tb_cols.setFixedHeight(140)
        self.tb_cols.itemChanged.connect(self._cols_changed)
        f.addRow(self.tb_cols)
        r = QHBoxLayout()
        r.addWidget(button("عمود ملاحظات +", self.add_extra_col))
        r.addWidget(button("حذف عمود إضافي", self.del_extra_col))
        f.addRow(r)
        r2 = QHBoxLayout()
        r2.addWidget(button("توزيع متساوٍ", self.reset_weights))
        f.addRow(r2)
        f.addRow(QLabel("دمج خلايا بنص (للطباعة فقط):"))
        self.tb_merges = QListWidget()
        self.tb_merges.setFixedHeight(90)
        f.addRow(self.tb_merges)
        r3 = QHBoxLayout()
        r3.addWidget(button("دمج جديد…", self.add_merge))
        r3.addWidget(button("حذف الدمج", self.del_merge))
        f.addRow(r3)
        return box

    # ================================================================ النطاق والتحميل
    def refresh(self) -> None:
        cur = self.training.currentData()
        self.training.blockSignals(True)
        self.training.clear()
        for t in structure.trainings(self.s):
            self.training.addItem(t.name, t.id)
        self.training.setCurrentIndex(max(0, self.training.findData(cur)))
        self.training.blockSignals(False)
        self._fill_levels()

    def _fill_levels(self) -> None:
        t = self.s.get(Training, self.training.currentData()) if self.training.currentData() else None
        self.level.blockSignals(True)
        self.level.clear()
        for lv in (t.levels if t else []):
            self.level.addItem(lv.code, lv.id)
        self.level.blockSignals(False)
        if t:
            self.week.blockSignals(True)
            self.week.setValue(min(t.weeks_count, structure.current_week_number(t)))
            self.week.blockSignals(False)
        self._fill_sections()

    def _fill_sections(self) -> None:
        self.section.blockSignals(True)
        self.section.clear()
        lid = self.level.currentData()
        for sec in structure.all_sections(self.s, level_id=lid) if lid else []:
            self.section.addItem(sec.name, sec.id)
        self.section.blockSignals(False)
        self.load_scope()

    def _section(self) -> Section | None:
        return self.s.get(Section, self.section.currentData()) if self.section.currentData() else None

    def _scope_keys(self) -> tuple:
        sc = self.scope.currentData()
        if sc == "level":
            return (self.level.currentData(), None)
        if sc == "section":
            return (self.level.currentData(), self.section.currentData())
        return (None, None)

    def load_scope(self) -> None:
        if self.dirty and not confirm(self, "توجد تعديلات غير محفوظة على القالب. تجاهلها؟"):
            return
        lvl, sec = self._scope_keys()
        if self.scope.currentData() != "default" and not lvl:
            lvl = None
        lay = tpl.load(self.s, lvl, sec) if (self.scope.currentData() == "default" or lvl) else None
        if lay is not None:
            self.src_lbl.setText("محفوظ لهذا النطاق")
            self.src_lbl.setObjectName("BadgeOk")
        else:
            # يبدأ من القالب الموروث
            section = self._section() if self.scope.currentData() == "section" else None
            if self.scope.currentData() == "level" and lvl:
                lay = tpl.load(self.s, None, None) or tpl.default_layout()
                src = "default"
            else:
                lay, src = tpl.effective(self.s, section)
            self.src_lbl.setText(tpl.SOURCE_LABELS.get(src, "") + " — يُنشأ تخصيص عند الحفظ")
            self.src_lbl.setObjectName("Badge")
        self.src_lbl.style().unpolish(self.src_lbl)
        self.src_lbl.style().polish(self.src_lbl)
        self.layout_data = tpl.upgrade(lay)
        self.undo_stack = [json.dumps(self.layout_data)]
        self.redo_stack = []
        self.dirty = False
        self.update_ctx()

    def update_ctx(self) -> None:
        sec = self._section()
        week = None
        if sec:
            week = planner.get_week(self.s, sec.training, self.week.value(), create=False)
            data = build_table_data(sec, week, subject_color)
        else:
            data = sample_table_data()
        values = tpl.field_values(self.s, sec, week)
        self.canvas.set_data(self.layout_data, RenderContext(values, data))
        self._sync_props()

    # ================================================================ التحرير
    def _cur(self) -> dict | None:
        if not hasattr(self, "canvas"):
            return None
        return tpl.find_item(self.layout_data, self.canvas.selected)

    def _push(self) -> None:
        snap = json.dumps(self.layout_data)
        if not self.undo_stack or self.undo_stack[-1] != snap:
            self.undo_stack.append(snap)
            self.undo_stack = self.undo_stack[-200:]
            self.redo_stack.clear()
            self.dirty = True

    def _set(self, key: str, value) -> None:
        if self._sync:
            return
        it = self._cur()
        if it is None:
            return
        it[key] = value
        self.canvas.update()
        self._push()

    def _grid(self, key, value) -> None:
        if self._sync:
            return
        self.layout_data["grid"][key] = value
        self.canvas.update()
        self._push()

    def _apply_page(self) -> None:
        if self._sync:
            return
        pg = self.layout_data["page"]
        pg["size"], pg["orientation"] = self.p_size.currentData(), self.p_orient.currentData()
        pg["margins"] = [sp.value() for sp in self.p_margins]
        self.canvas.relayout()
        self._push()

    def on_canvas_edited(self) -> None:
        self._push()
        self._sync_props()

    def on_select(self, _id: str) -> None:
        self._sync_props()

    def _sync_props(self) -> None:
        self._sync = True
        try:
            lay = self.layout_data
            g = lay["grid"]
            self.grid_btn.setChecked(g.get("show", True))
            self.snap_btn.setChecked(g.get("snap", True))
            self.grid_size.setValue(float(g.get("size", 5)))
            it = self._cur()
            if it is None:
                self.props.setCurrentIndex(0)
                pg = lay["page"]
                self.p_size.setCurrentIndex(max(0, self.p_size.findData(pg.get("size", "A4"))))
                self.p_orient.setCurrentIndex(max(0, self.p_orient.findData(pg.get("orientation"))))
                for sp, v in zip(self.p_margins, pg.get("margins", [10] * 4)):
                    sp.setValue(v)
            elif it["type"] == "text":
                self.props.setCurrentIndex(1)
                if self.t_text.toPlainText() != it["text"]:
                    self.t_text.setPlainText(it["text"])
                self.t_font.setCurrentFont(QFont(it.get("font", "Tahoma")))
                self.t_size.setValue(it.get("size", 11))
                self.t_bold.setChecked(it.get("bold", False))
                self.t_italic.setChecked(it.get("italic", False))
                self.t_align.setCurrentIndex(max(0, self.t_align.findData(it.get("align"))))
                self.t_valign.setCurrentIndex(max(0, self.t_valign.findData(it.get("valign"))))
                self.t_border.setValue(it.get("border", 0))
                self.t_rot.setValue(int(it.get("rotation", 0)))
                for sp, key in zip(self.t_geo, ("x", "y", "w", "h")):
                    sp.setValue(it[key])
                for b in (self.t_color, self.t_bcolor, self.t_bg):
                    b.repaint_color()
            else:
                self.props.setCurrentIndex(2)
                for key, sp in self.tb_spins.items():
                    sp.setValue(float(it.get(key, 0)))
                for key, cb in self.tb_checks.items():
                    cb.setChecked(bool(it.get(key)))
                self.tb_font.setCurrentFont(QFont(it.get("font", "Tahoma")))
                self.tb_side.setCurrentIndex(max(0, self.tb_side.findData(it.get("day_col_side", "right"))))
                self.tb_lunch.setText(it.get("lunch_label", ""))
                for b in (self.tb_bcolor, self.tb_hbg, self.tb_dbg):
                    b.repaint_color()
                self.tb_days.clear()
                for d in self.canvas.ctx.table.days:
                    li = QListWidgetItem(DAY_NAMES[d])
                    li.setData(Qt.UserRole, d)
                    li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
                    li.setCheckState(Qt.Unchecked if d in it.get("hidden_days", []) else Qt.Checked)
                    self.tb_days.addItem(li)
                self.tb_cols.clear()
                for c in self.canvas.ctx.table.cols:
                    li = QListWidgetItem(c.key + ("  (غداء)" if c.is_lunch else ""))
                    li.setData(Qt.UserRole, c.key)
                    li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
                    li.setCheckState(Qt.Unchecked if c.key in it.get("hidden_cols", []) else Qt.Checked)
                    self.tb_cols.addItem(li)
                self.tb_merges.clear()
                for m in it.get("merges", []):
                    self.tb_merges.addItem(f"صف {m['row']}، عمود {m['col']} ({m.get('rows', 1)}×{m.get('cols', 1)}): {m.get('text', '')}")
        finally:
            self._sync = False

    def _insert_field(self, idx: int) -> None:
        key = self.t_field.itemData(idx)
        if key:
            self.t_text.insertPlainText("{" + key + "}")
        self.t_field.setCurrentIndex(0)

    def _center(self, axis: str) -> None:
        it = self._cur()
        if not it:
            return
        pw, ph = tpl.page_mm(self.layout_data)
        if axis == "h":
            it["x"] = round((pw - it["w"]) / 2, 1)
        else:
            it["y"] = round((ph - it["h"]) / 2, 1)
        self.canvas.update()
        self._push()
        self._sync_props()

    def add_text(self) -> None:
        pw, ph = tpl.page_mm(self.layout_data)
        it = tpl.text_item("نص جديد", round(pw / 2 - 40), 20, 80, 10, 12)
        self.layout_data["items"].append(it)
        self.canvas.selected = it["id"]
        self.canvas.update()
        self._push()
        self._sync_props()

    def duplicate(self) -> None:
        it = self._cur()
        if it and it["type"] == "text":
            c = copy.deepcopy(it)
            c["id"] = tpl.new_id()
            c["x"] += 5
            c["y"] += 5
            self.layout_data["items"].append(c)
            self.canvas.selected = c["id"]
            self.canvas.update()
            self._push()
            self._sync_props()

    def delete_item(self) -> None:
        it = self._cur()
        if it and it["type"] == "text":
            self.layout_data["items"].remove(it)
            self.canvas.selected = ""
            self.canvas.update()
            self._push()
            self._sync_props()

    def _days_changed(self, _it) -> None:
        if self._sync:
            return
        hidden = [self.tb_days.item(i).data(Qt.UserRole) for i in range(self.tb_days.count())
                  if self.tb_days.item(i).checkState() != Qt.Checked]
        self._set("hidden_days", hidden)

    def _cols_changed(self, _it) -> None:
        if self._sync:
            return
        hidden = [self.tb_cols.item(i).data(Qt.UserRole) for i in range(self.tb_cols.count())
                  if self.tb_cols.item(i).checkState() != Qt.Checked]
        self._set("hidden_cols", hidden)

    def add_extra_col(self) -> None:
        it = self._cur()
        if it:
            v = ask_form(self, "عمود إضافي", [("title", "العنوان", "text", "ملاحظات"),
                                               ("width", "العرض (مم)", "float", 30)])
            if v:
                it.setdefault("extra_cols", []).append({"title": v["title"], "width": v["width"]})
                self.canvas.update()
                self._push()

    def del_extra_col(self) -> None:
        it = self._cur()
        if it and it.get("extra_cols"):
            it["extra_cols"].pop()
            self.canvas.update()
            self._push()

    def reset_weights(self) -> None:
        it = self._cur()
        if it:
            it["col_weights"], it["row_weights"] = {}, {}
            self.canvas.update()
            self._push()

    def add_merge(self) -> None:
        it = self._cur()
        if not it:
            return
        g = table_geometry(it, self.canvas.ctx.table)
        v = ask_form(self, "دمج خلايا (الصف 0 = الرأس، العمود 0 = أقصى اليمين)", [
            ("row", "من الصف", "int", 1, (0, len(g.rows) - 1)), ("col", "من العمود", "int", 1, (0, len(g.cols) - 1)),
            ("rows", "عدد الصفوف", "int", 1, (1, len(g.rows))), ("cols", "عدد الأعمدة", "int", 2, (1, len(g.cols))),
            ("text", "النص", "text", ""), ("size", "حجم الخط", "float", it.get("cell_size", 8.5))])
        if v:
            it.setdefault("merges", []).append(dict(v, bold=True))
            self.canvas.update()
            self._push()
            self._sync_props()

    def del_merge(self) -> None:
        it = self._cur()
        r = self.tb_merges.currentRow()
        if it and r >= 0:
            it["merges"].pop(r)
            self.canvas.update()
            self._push()
            self._sync_props()

    def undo(self) -> None:
        if len(self.undo_stack) > 1:
            self.redo_stack.append(self.undo_stack.pop())
            self.layout_data = json.loads(self.undo_stack[-1])
            self.dirty = True
            self.canvas.set_data(self.layout_data, self.canvas.ctx)
            self._sync_props()

    def redo(self) -> None:
        if self.redo_stack:
            snap = self.redo_stack.pop()
            self.undo_stack.append(snap)
            self.layout_data = json.loads(snap)
            self.dirty = True
            self.canvas.set_data(self.layout_data, self.canvas.ctx)
            self._sync_props()

    # ================================================================ الحفظ والتوريث
    def save(self) -> None:
        lvl, sec = self._scope_keys()
        if self.scope.currentData() == "level" and not lvl:
            warn(self, "اختر الطور")
            return
        if self.scope.currentData() == "section" and not sec:
            warn(self, "اختر الفرع")
            return
        tpl.save(self.s, self.layout_data, lvl, sec)
        self.dirty = False
        self.src_lbl.setText("محفوظ لهذا النطاق")
        self.main and self.main.status("حُفظ القالب")

    def revert_inherited(self) -> None:
        if self.scope.currentData() == "default":
            warn(self, "القالب الافتراضي لا يرث من شيء؛ استعمل «القالب المدمج» لإعادة ضبطه")
            return
        lvl, sec = self._scope_keys()
        if confirm(self, "حذف تخصيص هذا النطاق والرجوع للقالب الموروث؟"):
            tpl.remove(self.s, lvl, sec)
            self.dirty = False
            self.load_scope()

    def reset_builtin(self) -> None:
        if confirm(self, "استبدال القالب الحالي بالقالب المدمج في البرنامج؟ (يمكن التراجع قبل الحفظ)"):
            self.layout_data = tpl.default_layout()
            self._push()
            self.update_ctx()

    def copy_to(self) -> None:
        s = self.s
        targets = [("default", "القالب الافتراضي")]
        for t in structure.trainings(s):
            for lv in t.levels:
                targets.append((f"L{lv.id}", f"طور {lv.code}"))
                for sp in lv.specialties:
                    for sec in sp.sections:
                        targets.append((f"S{sec.id}", f"فرع {sec.name} ({lv.code})"))
        v = ask_form(self, "نسخ القالب إلى", [("t", "الوجهة", "combo", "default", targets)])
        if not v:
            return
        key = v["t"]
        if key == "default":
            lvl = sec = None
        elif key.startswith("L"):
            lvl, sec = int(key[1:]), None
        else:
            section = s.get(Section, int(key[1:]))
            lvl, sec = section.level.id, section.id
        if tpl.load(s, lvl, sec) and not confirm(self, "للوجهة قالب محفوظ. استبداله؟"):
            return
        tpl.save(s, copy.deepcopy(self.layout_data), lvl, sec)
        info(self, "نُسخ القالب")

    # ================================================================ الإخراج
    def _check_missing(self, sheets) -> bool:
        miss = set()
        for sh in sheets:
            miss |= set(tpl.missing_fields(sh.layout, tpl.field_values(self.s, sh.section, sh.week)))
        if miss:
            names = "، ".join(tpl.FIELDS.get(m, m) for m in sorted(miss))
            return confirm(self, f"حقول بلا قيمة ستظهر كعلامة [؟]: {names}\n(اسم المؤسسة يُضبط من الإعدادات). المتابعة؟")
        return True

    def _sheets(self, all_level: bool):
        if self.dirty and confirm(self, "حفظ تعديلات القالب قبل الطباعة؟"):
            self.save()
        lid = self.level.currentData()
        secs = structure.all_sections(self.s, level_id=lid) if all_level else ([self._section()] if self._section() else [])
        if not secs:
            warn(self, "لا توجد فروع")
            return []
        wn = self.week.value()
        sheets = output.make_sheets(self.s, secs, lambda sec: planner.get_week(self.s, sec.training, wn, create=False))
        if not all_level and self.dirty:
            sheets[0].layout = self.layout_data  # معاينة التعديلات غير المحفوظة
        return sheets if self._check_missing(sheets) else []

    def preview(self) -> None:
        sheets = self._sheets(False)
        if sheets:
            output.print_preview(self, self.s, sheets)

    def _export(self, all_level: bool) -> None:
        sheets = self._sheets(all_level)
        if not sheets:
            return
        name = f"جدول_{self.level.currentText() if all_level else sheets[0].section.name}_أسبوع{self.week.value()}.pdf"
        path, _ = QFileDialog.getSaveFileName(self, "تصدير PDF", name, "PDF (*.pdf)")
        if path:
            output.export_pdf(self.s, sheets, path)
            info(self, f"صُدِّر {len(sheets)} صفحة إلى\n{path}")

    def export_section(self) -> None:
        self._export(False)

    def export_level(self) -> None:
        self._export(True)
