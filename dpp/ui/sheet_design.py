"""لوحة «تصميم الورقة» في معاينة الطباعة: الورقة والهوامش، النصوص الحرة، شكل الجدول، وحفظ القالب.

كل تعديل هنا يغيّر شكل الطباعة فقط (التخطيط)، ولا يلمس الحصص المحفوظة.
"""
from __future__ import annotations

import copy

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFontComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QPlainTextEdit, QPushButton,
                               QRadioButton, QScrollArea, QSpinBox, QTabWidget, QToolButton, QVBoxLayout, QWidget)

from ..exporters import layout as L
from .widgets import confirm, icon, info

MARGIN_PRESETS = {"ضيقة": [10, 10, 10, 10], "عادية": [20, 20, 20, 20], "واسعة": [36, 36, 36, 36]}


def _spin(lo, hi, val, step=1.0, dec=1, suffix=""):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setSingleStep(step)
    s.setValue(float(val))
    if suffix:
        s.setSuffix(suffix)
    return s


class ColorButton(QPushButton):
    """زر يعرض اللون ويفتح منتقي الألوان؛ «بلا» يمسح اللون."""

    def __init__(self, color: str = "", allow_none=True):
        super().__init__()
        self.allow_none = allow_none
        self.setMinimumWidth(80)
        self.set(color)
        self.clicked.connect(self._pick)
        self.on_change = None

    def set(self, color: str):
        self.color = color or ""
        self.setText(self.color or "بلا")
        txt = "#000" if not self.color or QColor(self.color).lightness() > 140 else "#fff"
        self.setStyleSheet(f"background:{self.color or 'transparent'}; color:{txt};")

    def _pick(self):
        m = QMenu(self)
        m.addAction("اختيار لون…", self._dialog)
        if self.allow_none:
            m.addAction("بلا لون", lambda: self._done(""))
        for c in ("#000000", "#1F2A44", "#0E4C92", "#0E7C66", "#9B2C1F", "#E6E6E6", "#F2F2F2", "#FFF4D6"):
            a = m.addAction(c, lambda c=c: self._done(c))
            a.setIcon(icon("mdi6.square", c))
        m.exec(self.mapToGlobal(self.rect().bottomLeft()))

    def _dialog(self):
        c = QColorDialog.getColor(QColor(self.color or "#000000"), self, "اللون")
        if c.isValid():
            self._done(c.name())

    def _done(self, c):
        self.set(c)
        if self.on_change:
            self.on_change(c)


class TextDialog(QDialog):
    """تحرير نص مربع حر، مع إدراج الحقول التلقائية."""

    def __init__(self, parent, text: str):
        super().__init__(parent)
        self.setWindowTitle("نص المربع")
        self.resize(520, 300)
        v = QVBoxLayout(self)
        self.edit = QPlainTextEdit(text)
        self.edit.setLayoutDirection(Qt.RightToLeft)
        v.addWidget(self.edit, 1)
        h = QHBoxLayout()
        b = QPushButton(icon("mdi6.code-braces"), "إدراج حقل تلقائي")
        m = QMenu(b)
        for k, lab in L.PLACEHOLDERS.items():
            m.addAction(lab, lambda k=k: self.edit.insertPlainText("{" + k + "}"))
        b.setMenu(m)
        h.addWidget(b)
        hint = QLabel("الحقول بين { } تُملأ من البيانات في كل ورقة (اسم القسم، الأسبوع…).")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        h.addWidget(hint, 1)
        v.addLayout(h)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("تم")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def text(self) -> str:
        return self.edit.toPlainText()


class DesignPanel(QTabWidget):
    def __init__(self, dlg):
        super().__init__()
        self.dlg = dlg
        self.box_id = ""
        self._loading = False
        self.setMinimumWidth(410)
        self.setMaximumWidth(500)
        self.addTab(self._scroll(self._page_tab()), icon("mdi6.file-outline"), "الورقة")
        self.addTab(self._scroll(self._text_tab()), icon("mdi6.format-text"), "النص")
        self.addTab(self._scroll(self._table_tab()), icon("mdi6.table-edit"), "الجدول")
        self.addTab(self._scroll(self._tpl_tab()), icon("mdi6.content-save-cog-outline"), "القالب")

    @staticmethod
    def _scroll(w):
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        for f in w.findChildren(QFormLayout):
            f.setRowWrapPolicy(QFormLayout.WrapLongRows)
            f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        sc.setWidget(w)
        return sc

    @property
    def lay(self) -> dict:
        return self.dlg.cur_sheet().layout

    def change(self, fn, rebuild=True):
        """كل تعديل: نسخة للتراجع، ثم التطبيق، ثم إعادة رسم الورقة."""
        if self._loading:
            return
        self.dlg.apply_layout_change(fn, rebuild)

    # ------------------------------------------------------------------ الورقة
    def _page_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        g = QGroupBox("الورقة")
        f = QFormLayout(g)
        self.paper = QComboBox()
        for k, lab in L.PAPER_LABELS.items():
            self.paper.addItem(lab, k)
        self.paper.currentIndexChanged.connect(lambda _: self.change(lambda l: l["page"].update(paper=self.paper.currentData())))
        f.addRow("المقاس", self.paper)
        self.orient = QComboBox()
        self.orient.addItem("أفقي", "landscape")
        self.orient.addItem("عمودي", "portrait")
        self.orient.currentIndexChanged.connect(
            lambda _: self.change(lambda l: l["page"].update(orientation=self.orient.currentData())))
        f.addRow("الاتجاه", self.orient)
        v.addWidget(g)
        g2 = QGroupBox("الهوامش (نقطة)")
        f2 = QGridLayout(g2)
        self.margins = []
        for i, lab in enumerate(("أعلى", "يمين", "أسفل", "يسار")):
            s = _spin(0, 120, 20, 2, 0)
            s.valueChanged.connect(lambda _v: self.change(lambda l: l["page"].update(
                margins=[m.value() for m in self.margins])))
            f2.addWidget(QLabel(lab), i // 2, (i % 2) * 2)
            f2.addWidget(s, i // 2, (i % 2) * 2 + 1)
            self.margins.append(s)
        pr = QHBoxLayout()
        for name, vals in MARGIN_PRESETS.items():
            b = QPushButton(name)
            b.clicked.connect(lambda _=False, vals=vals: self._preset(vals))
            pr.addWidget(b)
        f2.addLayout(pr, 2, 0, 1, 4)
        v.addWidget(g2)
        g3 = QGroupBox("الشبكة (لا تُطبع)")
        f3 = QFormLayout(g3)
        self.grid_on = QCheckBox("إظهار الشبكة")
        self.grid_on.setChecked(True)
        self.grid_on.toggled.connect(lambda on: self.dlg.set_grid(show=on))
        f3.addRow(self.grid_on)
        self.snap = QCheckBox("التصاق النصوص بالشبكة")
        self.snap.setChecked(True)
        self.snap.toggled.connect(lambda on: self.dlg.set_grid(snap=on))
        f3.addRow(self.snap)
        self.grid_size = _spin(2, 50, 10, 1, 0, " نقطة")
        self.grid_size.valueChanged.connect(lambda val: self.dlg.set_grid(size=val))
        f3.addRow("حجم المربع", self.grid_size)
        hint = QLabel("الأسهم تحرّك النص المحدد نقطة واحدة، ومع Shift بحجم مربع الشبكة.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        f3.addRow(hint)
        v.addWidget(g3)
        g4 = QGroupBox("خط الأوراق (لكل الأوراق والتقارير)")
        f4 = QFormLayout(g4)
        self.sheet_font = QFontComboBox()
        self.sheet_font.currentFontChanged.connect(self._sheet_font)
        f4.addRow("الخط", self.sheet_font)
        self.st_sizes = {}
        for k, lab in (("head_pt", "الرأس"), ("center_pt", "وسط الرأس")):
            sp = _spin(4, 24, 9, 0.5, 1, " pt")
            sp.valueChanged.connect(lambda val, k=k: self._sheet_style(k, val))
            f4.addRow(f"حجم خط {lab}", sp)
            self.st_sizes[k] = sp
        v.addWidget(g4)
        v.addStretch()
        return w

    def _sheet_style(self, k, val):
        if self._loading:
            return
        from ..exporters import official as O
        import json as _j
        st = O.load_store(self.dlg.db)
        st.setdefault("style", {})[k] = val
        self.dlg.db.set_setting("official_tpl", _j.dumps(st, ensure_ascii=False))
        for sh in self.dlg.sheets:
            sh.style = O.template_style(self.dlg.db)
        self.dlg.scenes.clear()
        self.dlg.show_page(self.dlg.cur_index())

    def _sheet_font(self, fnt):
        self._sheet_style("font", fnt.family())

    def _preset(self, vals):
        self._loading = True
        for s, x in zip(self.margins, vals):
            s.setValue(x)
        self._loading = False
        self.change(lambda l: l["page"].update(margins=list(vals)))

    # ------------------------------------------------------------------ النص
    def _text_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        b_add = QPushButton(icon("mdi6.format-text-variant-outline"), "إضافة نص")
        b_add.setObjectName("Primary")
        b_add.clicked.connect(self.add_box)
        top.addWidget(b_add)
        self.b_dup = QPushButton(icon("mdi6.content-copy"), "نسخ")
        self.b_dup.clicked.connect(self.dup_box)
        top.addWidget(self.b_dup)
        self.b_del = QPushButton(icon("mdi6.delete-outline"), "حذف")
        self.b_del.clicked.connect(lambda: self.dlg.delete_box(self.box_id))
        top.addWidget(self.b_del)
        v.addLayout(top)
        self.box_hint = QLabel("انقر على نص حر في الورقة لتحديده، أو أضف نصاً جديداً. انقر مرتين على النص لكتابته.")
        self.box_hint.setObjectName("Muted")
        self.box_hint.setWordWrap(True)
        v.addWidget(self.box_hint)
        self.box_w = QWidget()
        f = QFormLayout(self.box_w)
        self.b_text = QPushButton(icon("mdi6.pencil"), "كتابة النص والحقول…")
        self.b_text.clicked.connect(lambda: self.edit_text(self.box_id))
        f.addRow(self.b_text)
        ah = QHBoxLayout()
        self.align_grp = QButtonGroup(self)
        for k, ic, tip in (("right", "mdi6.format-align-right", "يمين"), ("center", "mdi6.format-align-center", "وسط"),
                           ("left", "mdi6.format-align-left", "يسار"),
                           ("justify", "mdi6.format-align-justify", "ضبط: تمتد الأسطر حتى تملأ العرض (مثل Word)")):
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setProperty("k", k)
            self.align_grp.addButton(b)
            ah.addWidget(b)
        ah.addSpacing(8)
        self.valign_grp = QButtonGroup(self)
        for k, ic, tip in (("top", "mdi6.format-vertical-align-top", "أعلى"),
                           ("middle", "mdi6.format-vertical-align-center", "وسط عمودي"),
                           ("bottom", "mdi6.format-vertical-align-bottom", "أسفل")):
            b = QToolButton()
            b.setIcon(icon(ic))
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setProperty("k", k)
            self.valign_grp.addButton(b)
            ah.addWidget(b)
        ah.addStretch()
        self.align_grp.buttonClicked.connect(lambda b: self.set_box(align=b.property("k")))
        self.valign_grp.buttonClicked.connect(lambda b: self.set_box(valign=b.property("k")))
        f.addRow("المحاذاة", ah)
        jh = QHBoxLayout()
        self.kashida = QCheckBox("بالتطويل (ـ)")
        self.kashida.setToolTip("تُمدّ الحروف العربية المتصلة بدل توسيع المسافات فقط")
        self.kashida.toggled.connect(lambda on: self.set_box(kashida=on))
        self.just_last = QCheckBox("ضبط السطر الأخير أيضاً")
        self.just_last.toggled.connect(lambda on: self.set_box(justify_last=on))
        jh.addWidget(self.kashida)
        jh.addWidget(self.just_last)
        jh.addStretch()
        self.just_w = QWidget()
        self.just_w.setLayout(jh)
        f.addRow("الضبط", self.just_w)
        ch = QHBoxLayout()
        b_ch = QPushButton(icon("mdi6.format-horizontal-align-center"), "أفقي")
        b_ch.clicked.connect(lambda: self.center_box(True, False))
        b_cv = QPushButton(icon("mdi6.format-vertical-align-center"), "عمودي")
        b_cv.clicked.connect(lambda: self.center_box(False, True))
        ch.addWidget(b_ch)
        ch.addWidget(b_cv)
        f.addRow("توسيط في الورقة", ch)
        self.font_cb = QFontComboBox()
        self.font_cb.currentFontChanged.connect(lambda fnt: self.set_box(font=fnt.family()))
        f.addRow("الخط", self.font_cb)
        self.size = _spin(4, 72, 11, 0.5, 1)
        self.size.valueChanged.connect(lambda val: self.set_box(size=val))
        f.addRow("الحجم", self.size)
        sh = QHBoxLayout()
        self.bold = QCheckBox("غامق")
        self.italic = QCheckBox("مائل")
        self.under = QCheckBox("مسطّر")
        self.bold.toggled.connect(lambda on: self.set_box(bold=on))
        self.italic.toggled.connect(lambda on: self.set_box(italic=on))
        self.under.toggled.connect(lambda on: self.set_box(underline=on))
        for x in (self.bold, self.italic, self.under):
            sh.addWidget(x)
        f.addRow("الشكل", sh)
        self.color = ColorButton("#000000", allow_none=False)
        self.color.on_change = lambda c: self.set_box(color=c)
        f.addRow("لون النص", self.color)
        self.fill = ColorButton("")
        self.fill.on_change = lambda c: self.set_box(fill=c)
        f.addRow("خلفية", self.fill)
        self.frame_w = _spin(0, 6, 0, 0.25, 2)
        self.frame_w.valueChanged.connect(lambda val: self.set_box(frame_w=val))
        f.addRow("سمك الإطار (0 = بلا)", self.frame_w)
        self.frame_c = ColorButton("#000000", allow_none=False)
        self.frame_c.on_change = lambda c: self.set_box(frame_color=c)
        f.addRow("لون الإطار", self.frame_c)
        self.pad = _spin(0, 30, 3, 0.5, 1)
        self.pad.valueChanged.connect(lambda val: self.set_box(padding=val))
        f.addRow("المسافة الداخلية", self.pad)
        self.rot = _spin(-180, 180, 0, 5, 0, "°")
        self.rot.valueChanged.connect(lambda val: self.set_box(rotation=val))
        f.addRow("الدوران (مائل بأي زاوية)", self.rot)
        rh = QHBoxLayout()
        for a, lab in ((0, "أفقي"), (-90, "عمودي ↑"), (90, "عمودي ↓")):
            b = QPushButton(lab)
            b.clicked.connect(lambda _=False, a=a: self.rot.setValue(a))
            rh.addWidget(b)
        f.addRow("", rh)
        v.addWidget(self.box_w)
        v.addStretch()
        self.select_box("")
        return w

    def add_box(self):
        sc = self.dlg.cur_scene()
        b = L.new_box(sc.W / 2 - 110, sc.H / 2 - 14, "نص جديد", 220, 28)
        self.change(lambda l: l.setdefault("boxes", []).append(b))
        self.dlg.select_box(b["id"])
        self.edit_text(b["id"])

    def dup_box(self):
        b = self._box()
        if not b:
            return
        nb = copy.deepcopy(b)
        nb["id"] = L.new_box(0, 0)["id"]
        nb["x"], nb["y"] = b["x"] + 15, b["y"] + 15
        self.change(lambda l: l["boxes"].append(nb))
        self.dlg.select_box(nb["id"])

    def _box(self):
        return next((b for b in self.lay.get("boxes", []) if b["id"] == self.box_id), None)

    def select_box(self, bid: str):
        self.box_id = bid
        b = self._box()
        self.box_w.setEnabled(bool(b))
        self.b_dup.setEnabled(bool(b))
        self.b_del.setEnabled(bool(b))
        if not b:
            return
        self._loading = True
        for grp, k in ((self.align_grp, "align"), (self.valign_grp, "valign")):
            for btn in grp.buttons():
                btn.setChecked(btn.property("k") == b.get(k))
        self.kashida.setChecked(bool(b.get("kashida")))
        self.just_last.setChecked(bool(b.get("justify_last")))
        self.just_w.setEnabled(b.get("align") == "justify")
        self.font_cb.setCurrentFont(QFont(b.get("font") or self.dlg.cur_sheet().style.get("font") or "Arial"))
        self.size.setValue(float(b.get("size") or 11))
        self.bold.setChecked(bool(b.get("bold")))
        self.italic.setChecked(bool(b.get("italic")))
        self.under.setChecked(bool(b.get("underline")))
        self.color.set(b.get("color") or "#000000")
        self.fill.set(b.get("fill") or "")
        self.frame_w.setValue(float(b.get("frame_w") or 0))
        self.frame_c.set(b.get("frame_color") or "#000000")
        self.pad.setValue(float(b.get("padding") or 0))
        self.rot.setValue(float(b.get("rotation") or 0))
        self._loading = False
        self.setCurrentIndex(1)

    def set_box(self, **kv):
        bid = self.box_id
        if not bid or self._loading:
            return

        def fn(l):
            for b in l.get("boxes", []):
                if b["id"] == bid:
                    b.update(kv)
        self.change(fn)

    def center_box(self, h: bool, v: bool):
        b = self._box()
        if not b:
            return
        sc = self.dlg.cur_scene()
        bid = b["id"]

        def fn(l):
            for x in l["boxes"]:
                if x["id"] == bid:
                    if h:
                        x["x"] = round((sc.W - x["w"]) / 2, 1)
                    if v:
                        x["y"] = round((sc.H - x["h"]) / 2, 1)
        self.change(fn)

    def edit_text(self, bid: str):
        self.box_id = bid
        b = self._box()
        if not b:
            return
        d = TextDialog(self, b.get("text", ""))
        if d.exec() == QDialog.Accepted:
            self.set_box(text=d.text())

    # ------------------------------------------------------------------ الجدول
    def _table_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel("هذه الخيارات تغيّر شكل الطباعة فقط، ولا تغيّر الحصص. اسحب الخطوط الزرقاء في رأس الجدول "
                      "وعمود الأيام لتغيير عرض الأعمدة وارتفاع الأسطر.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        g = QGroupBox("الحدود والألوان")
        f = QFormLayout(g)
        self.t_bw = _spin(0, 4, 0.6, 0.1, 2)
        self.t_bw.valueChanged.connect(lambda val: self.change(lambda l: l["table"].update(border_w=val)))
        f.addRow("سمك الخطوط", self.t_bw)
        self.t_ow = _spin(0, 5, 1.2, 0.1, 2)
        self.t_ow.valueChanged.connect(lambda val: self.change(lambda l: l["table"].update(outer_w=val)))
        f.addRow("سمك الإطار الخارجي", self.t_ow)
        self.t_bc = ColorButton("#000000", allow_none=False)
        self.t_bc.on_change = lambda c: self.change(lambda l: l["table"].update(border_color=c))
        f.addRow("لون الخطوط", self.t_bc)
        self.t_hf = ColorButton("")
        self.t_hf.on_change = lambda c: self.change(lambda l: l["table"].update(head_fill=c))
        f.addRow("خلفية رأس الجدول", self.t_hf)
        self.t_df = ColorButton("")
        self.t_df.on_change = lambda c: self.change(lambda l: l["table"].update(day_fill=c))
        f.addRow("خلفية عمود الأيام", self.t_df)
        self.t_cf = ColorButton("")
        self.t_cf.on_change = lambda c: self.change(lambda l: l["table"].update(cell_fill=c))
        f.addRow("خلفية الخانات", self.t_cf)
        v.addWidget(g)
        g2 = QGroupBox("أحجام الخطوط (0 = حسب القالب)")
        f2 = QFormLayout(g2)
        self.t_sizes = {}
        for k, lab in (("head_pt", "أوقات الحصص"), ("day_pt", "أسماء الأيام"), ("title_pt", "اسم المادة"),
                       ("sub_pt", "الأستاذ والقاعة")):
            s = _spin(0, 30, 0, 0.5, 1)
            s.valueChanged.connect(lambda val, k=k: self.change(lambda l: l["table"].update({k: val or None})))
            f2.addRow(lab, s)
            self.t_sizes[k] = s
        v.addWidget(g2)
        g2b = QGroupBox("نص الخانات")
        f2b = QFormLayout(g2b)
        self.t_align = QComboBox()
        self.t_align.addItem("في الوسط", "center")
        self.t_align.addItem("ضبط (تمتد الأسطر حتى تملأ الخانة)", "justify")
        self.t_align.currentIndexChanged.connect(
            lambda _: self.change(lambda l: l["table"].update(cell_align=self.t_align.currentData())))
        f2b.addRow("المحاذاة", self.t_align)
        self.t_rowh = _spin(0, 80, 0, 1, 0, " نقطة")
        self.t_rowh.valueChanged.connect(lambda val: self.change(lambda l: l["table"].update(row_h=val)))
        f2b.addRow("أقل ارتفاع للسطر (التقارير، 0 = تلقائي)", self.t_rowh)
        self.t_top = _spin(60, 400, 172, 2, 0, " نقطة")
        self.t_top.valueChanged.connect(lambda val: self.change(lambda l: l["table"].update(top=val)))
        f2b.addRow("بداية الجدول من أعلى الورقة", self.t_top)
        v.addWidget(g2b)
        g3 = QGroupBox("الأعمدة والأيام الظاهرة")
        f3 = QVBoxLayout(g3)
        self.cols_box = QHBoxLayout()
        self.days_box = QHBoxLayout()
        f3.addWidget(QLabel("الحصص:"))
        f3.addLayout(self.cols_box)
        f3.addWidget(QLabel("الأيام:"))
        f3.addLayout(self.days_box)
        self.hidden_warn = QLabel()
        self.hidden_warn.setWordWrap(True)
        self.hidden_warn.setStyleSheet("color:#B45309;")
        f3.addWidget(self.hidden_warn)
        nh = QHBoxLayout()
        self.t_notes = QCheckBox("عمود ملاحظات فارغ")
        self.t_notes.toggled.connect(lambda on: self.change(lambda l: l["table"].update(notes_col=on)))
        nh.addWidget(self.t_notes)
        self.t_notes_t = QLineEdit()
        self.t_notes_t.setPlaceholderText("عنوانه")
        self.t_notes_t.editingFinished.connect(
            lambda: self.change(lambda l: l["table"].update(notes_title=self.t_notes_t.text())))
        nh.addWidget(self.t_notes_t)
        f3.addLayout(nh)
        b_reset = QPushButton(icon("mdi6.table-refresh"), "إرجاع العروض والارتفاعات متساوية")
        b_reset.clicked.connect(lambda: self.change(lambda l: l["table"].update(col_weights={}, row_weights={})))
        f3.addWidget(b_reset)
        v.addWidget(g3)
        g4 = QGroupBox("دمج خلايا ونص داخلها (للطباعة فقط)")
        f4 = QVBoxLayout(g4)
        row = QHBoxLayout()
        self.m_day = QComboBox()
        self.m_c0 = QComboBox()
        self.m_c1 = QComboBox()
        row.addWidget(self.m_day)
        row.addWidget(QLabel("من"))
        row.addWidget(self.m_c0)
        row.addWidget(QLabel("إلى"))
        row.addWidget(self.m_c1)
        f4.addLayout(row)
        self.m_text = QLineEdit()
        self.m_text.setPlaceholderText("النص داخل الخلايا المدمجة (مثلاً: استراحة)")
        f4.addWidget(self.m_text)
        mh = QHBoxLayout()
        b_m = QPushButton(icon("mdi6.table-merge-cells"), "دمج")
        b_m.clicked.connect(self.add_merge)
        mh.addWidget(b_m)
        self.m_all = QCheckBox("كل الأيام")
        mh.addWidget(self.m_all)
        mh.addStretch()
        f4.addLayout(mh)
        self.m_list = QListWidget()
        self.m_list.setMaximumHeight(90)
        f4.addWidget(self.m_list)
        b_um = QPushButton(icon("mdi6.table-split-cell"), "إلغاء الدمج المحدد")
        b_um.clicked.connect(self.remove_merge)
        f4.addWidget(b_um)
        v.addWidget(g4)
        v.addStretch()
        return w

    def add_merge(self):
        c0, c1 = self.m_c0.currentData(), self.m_c1.currentData()
        if c0 is None or c1 is None:
            return
        c0, c1 = min(c0, c1), max(c0, c1)
        days = [self.m_day.itemData(i) for i in range(self.m_day.count())] if self.m_all.isChecked() \
            else [self.m_day.currentData()]
        txt = self.m_text.text()
        self.change(lambda l: l["table"].setdefault("merges", []).extend(
            {"day": d, "c0": c0, "c1": c1, "text": txt} for d in days))

    def remove_merge(self):
        i = self.m_list.currentRow()
        if i >= 0:
            self.change(lambda l: l["table"]["merges"].pop(i))

    # ------------------------------------------------------------------ القالب
    def _tpl_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.inherit = QLabel()
        self.inherit.setWordWrap(True)
        v.addWidget(self.inherit)
        g = QGroupBox("حفظ التصميم الحالي في قالب")
        f = QVBoxLayout(g)
        self.scope_btns = QButtonGroup(self)
        self.scope_box = QVBoxLayout()
        f.addLayout(self.scope_box)
        b_save = QPushButton(icon("mdi6.content-save-outline"), "حفظ في القالب المحدد")
        b_save.setObjectName("Primary")
        b_save.clicked.connect(self.save_scope)
        f.addWidget(b_save)
        note = QLabel("يُحفظ ما يختلف عن القالب الأعم فقط؛ الباقي يبقى موروثاً ويتبع أي تعديل لاحق عليه. "
                      "دون حفظ، التصميم يبقى لهذه الطباعة فقط.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        f.addWidget(note)
        v.addWidget(g)
        g2 = QGroupBox("الرجوع")
        f2 = QVBoxLayout(g2)
        b_r = QPushButton(icon("mdi6.backup-restore"), "إرجاع القالب المحدد إلى الموروث")
        b_r.clicked.connect(self.reset_scope)
        f2.addWidget(b_r)
        b_cur = QPushButton(icon("mdi6.undo-variant"), "إلغاء تعديلات هذه الورقة (القالب الفعلي)")
        b_cur.clicked.connect(self.dlg.reload_layouts)
        f2.addWidget(b_cur)
        v.addWidget(g2)
        v.addStretch()
        return w

    def save_scope(self):
        b = self.scope_btns.checkedButton()
        if not b:
            return
        scope = b.property("scope")
        sh = self.dlg.cur_sheet()
        if not confirm(self, f"حفظ التصميم في قالب «{L.scope_label(self.dlg.db, scope)}»؟\n"
                             "كل الأوراق التي ترث هذا القالب ستُطبع بهذا الشكل."):
            return
        L.save(self.dlg.db, scope, sh.layout, sh.kind, sh.level_id, sh.section_id)
        self.dlg.reload_layouts(keep_current=False)
        info(self, "حُفظ القالب.")

    def reset_scope(self):
        b = self.scope_btns.checkedButton()
        if not b:
            return
        scope = b.property("scope")
        if confirm(self, f"إرجاع قالب «{L.scope_label(self.dlg.db, scope)}» إلى الموروث؟ (تُحذف تعديلاته)",
                   danger=True):
            L.reset(self.dlg.db, scope)
            self.dlg.reload_layouts(keep_current=False)

    # ------------------------------------------------------------------ المزامنة مع الورقة الحالية
    def sync(self):
        """تحميل قيم اللوحة من تخطيط الورقة الحالية."""
        sh = self.dlg.cur_sheet()
        lay = sh.layout
        sc = self.dlg.cur_scene()
        self._loading = True
        self.paper.setCurrentIndex(max(0, self.paper.findData(lay["page"].get("paper", "A4"))))
        self.orient.setCurrentIndex(max(0, self.orient.findData(lay["page"].get("orientation", "landscape"))))
        for s, x in zip(self.margins, lay["page"].get("margins", [20, 20, 20, 20])):
            s.setValue(float(x))
        tb = lay["table"]
        self.t_bw.setValue(float(tb.get("border_w", 0.6)))
        self.t_ow.setValue(float(tb.get("outer_w", 1.2)))
        self.t_bc.set(tb.get("border_color") or "#000000")
        self.t_hf.set(tb.get("head_fill") or "")
        self.t_df.set(tb.get("day_fill") or "")
        self.t_cf.set(tb.get("cell_fill") or "")
        for k, s in self.t_sizes.items():
            s.setValue(float(tb.get(k) or 0))
        self.t_notes.setChecked(bool(tb.get("notes_col")))
        self.t_align.setCurrentIndex(max(0, self.t_align.findData(tb.get("cell_align") or "center")))
        self.t_rowh.setValue(float(tb.get("row_h") or 0))
        self.t_top.setValue(float(tb.get("top") or 172))
        from ..exporters import official as O
        st = O.template_style(self.dlg.db)
        self.sheet_font.setCurrentFont(QFont(st.get("font") or "Arial"))
        for k, sp in self.st_sizes.items():
            sp.setValue(float(st.get(k) or 9))
        self.t_notes_t.setText(tb.get("notes_title") or "ملاحظات")
        for box, items, key in ((self.cols_box, [(j, p[0].replace("الحصة ", "")) for j, p in enumerate(sh.periods)],
                                 "hidden_cols"),
                                (self.days_box, list(enumerate(sh.days)), "hidden_days")):
            while box.count():
                it = box.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
            hidden = {int(x) for x in tb.get(key, [])}
            for j, lab in items:
                cb = QCheckBox(lab)
                cb.setChecked(j not in hidden)
                cb.toggled.connect(lambda on, j=j, key=key: self._toggle_hidden(key, j, on))
                box.addWidget(cb)
            box.addStretch()
        self.hidden_warn.setText(("تنبيه: في المخفي حصص لن تُطبع: " + "، ".join(sc.hidden_with_data))
                                 if sc.hidden_with_data else "")
        self.m_day.clear()
        for d, n in enumerate(sh.days):
            if d not in {int(x) for x in tb.get("hidden_days", [])}:
                self.m_day.addItem(n, d)
        for cb in (self.m_c0, self.m_c1):
            cb.clear()
            for j, p in enumerate(sh.periods):
                cb.addItem(p[0], j)
        self.m_list.clear()
        for m in tb.get("merges", []):
            self.m_list.addItem(f"{sh.days[int(m['day'])]}: {sh.periods[int(m['c0'])][0]} ← "
                                f"{sh.periods[int(m['c1'])][0]} «{m.get('text', '')}»")
        # القالب
        while self.scope_box.count():
            it = self.scope_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        for b in list(self.scope_btns.buttons()):
            self.scope_btns.removeButton(b)
        chain = L.scope_chain(sh.kind, sh.level_id, sh.section_id)
        saved = set(L.saved_scopes(self.dlg.db))
        for i, scope in enumerate(reversed(chain)):
            rb = QRadioButton(L.scope_label(self.dlg.db, scope) + ("  (له تعديلات محفوظة)" if scope in saved else ""))
            rb.setProperty("scope", scope)
            rb.setChecked(i == min(1, len(chain) - 1))
            self.scope_btns.addButton(rb)
            self.scope_box.addWidget(rb)
        src = [L.scope_label(self.dlg.db, s) for s in sh.layout_scopes]
        self.inherit.setText("<b>مصدر تصميم هذه الورقة:</b> " + (" ← ".join(src) if src else "التصميم الافتراضي")
                             + ("<br><span style='color:#B45309'>فيها تعديلات غير محفوظة.</span>"
                                if self.dlg.is_dirty() else ""))
        self._loading = False
        self.select_box(self.box_id if self._box() else "")

    def _toggle_hidden(self, key, j, visible):
        def fn(l):
            s = {int(x) for x in l["table"].get(key, [])}
            (s.discard if visible else s.add)(j)
            l["table"][key] = sorted(s)
        self.change(fn)
