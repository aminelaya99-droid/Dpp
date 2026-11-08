"""تبويبات الإعدادات الإضافية: القالب الرسمي والطباعة، البرمجة والتعارضات، الجدول العام."""
from __future__ import annotations

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout,
                               QGridLayout, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...exporters import official as O
from ..widgets import confirm, icon, info


def _scroll(inner: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QScrollArea.NoFrame)
    sc.setWidget(inner)
    return sc


# ====================================================================== القالب الرسمي والطباعة
class PrintSettings(QWidget):
    """الطباعة: الخيارات الافتراضية + الدخول إلى محرر الطباعة الواحد (كل الأوراق والتقارير) + القوالب المحفوظة."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        v = QVBoxLayout(inner)
        g = QGroupBox("محرر الطباعة (نظام واحد لكل الأوراق والتقارير)")
        gl = QVBoxLayout(g)
        hint = QLabel("كل الأوراق تُصمَّم وتُعدَّل في مكان واحد: الورق والهوامش، النصوص الحرة (مع الضبط والتطويل)، "
                      "رأس الورقة والتوقيعات، شكل الجدول، والخط. اختر الورقة ثم «تصميم الورقة» واحفظ في القالب "
                      "المناسب (كل الأطوار، الطور، القسم، أو كل التقارير، أو تقرير بعينه).")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        gl.addWidget(hint)
        row = QHBoxLayout()
        for lab, ic, kind in (("ورقة قسم", "mdi6.google-classroom", "section"),
                              ("ورقة أستاذ", "mdi6.human-male-board", "teacher"),
                              ("ورقة قاعة", "mdi6.door", "room"),
                              ("التقارير", "mdi6.file-document-outline", "report")):
            b = QPushButton(icon(ic), lab)
            b.clicked.connect(lambda _=False, k=kind: self.open_editor(k))
            row.addWidget(b)
        row.addStretch()
        gl.addLayout(row)
        v.addWidget(g)
        self.word = WordTemplates(ctx)
        v.addWidget(self.word)

        g3 = QGroupBox("خيارات الطباعة الافتراضية")
        f3 = QFormLayout(g3)
        self.room = QCheckBox("إظهار القاعة في خانات الجدول")
        self.room.setChecked(self.db.get_setting("print_show_room", "1") == "1")
        self.color = QCheckBox("الطباعة بالألوان (الافتراضي أبيض وأسود)")
        self.color.setChecked(self.db.get_setting("print_color", "0") == "1")
        self.one = QCheckBox("طباعة كل الأقسام في ملف PDF واحد (الافتراضي ملف لكل قسم)")
        self.one.setChecked(self.db.get_setting("print_one_file", "0") == "1")
        dr = QHBoxLayout()
        self.pdir = QLineEdit(self.db.get_setting("print_dir", ""))
        self.pdir.setPlaceholderText("المستندات")
        b = QPushButton("تغيير…")
        b.clicked.connect(self._pick_dir)
        dr.addWidget(self.pdir)
        dr.addWidget(b)
        dw = QWidget()
        dw.setLayout(dr)
        for w in (self.room, self.color, self.one):
            f3.addRow("", w)
        f3.addRow("مجلد حفظ ملفات PDF", dw)
        sv = QPushButton(icon("mdi6.content-save"), "حفظ الخيارات")
        sv.setObjectName("Primary")
        sv.clicked.connect(self.save)
        f3.addRow("", sv)
        v.addWidget(g3)

        g4 = QGroupBox("القوالب المحفوظة")
        l4 = QVBoxLayout(g4)
        self.scopes = QListWidget()
        self.scopes.setMaximumHeight(180)
        l4.addWidget(self.scopes)
        rb = QPushButton(icon("mdi6.restore"), "إرجاع القالب المحدد إلى الموروث")
        rb.clicked.connect(self._reset_scope)
        l4.addWidget(rb, 0, Qt.AlignLeft)
        v.addWidget(g4)
        v.addStretch()
        outer.addWidget(_scroll(inner))
        self._fill_scopes()

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "مجلد PDF", self.pdir.text())
        if d:
            self.pdir.setText(d)

    def _fill_scopes(self):
        from ...exporters import layout as L
        self.scopes.clear()
        for sc in L.saved_scopes(self.db):
            it = QListWidgetItem(f"تصميم: {L.scope_label(self.db, sc)}")
            it.setData(Qt.UserRole, ("layout", sc))
            self.scopes.addItem(it)
        names = {f"level:{r['id']}": f"الطور {r['code'] or r['name']}" for r in self.db.q("SELECT * FROM levels")}
        names |= {"teacher": "أوراق الأساتذة", "room": "أوراق القاعات", "global": "كل الأوراق", "report": "التقارير"}
        for k, vals in O.load_store(self.db).items():
            if k == "style" or not vals:
                continue
            it = QListWidgetItem(f"نصوص: {names.get(k, k)} ({', '.join(O.FIELD_LABELS.get(x, x) for x in vals)})")
            it.setData(Qt.UserRole, ("text", k))
            self.scopes.addItem(it)

    def _reset_scope(self):
        from ...exporters import layout as L
        it = self.scopes.currentItem()
        if not it or not confirm(self, "إرجاع هذا القالب إلى الموروث؟ (تُحذف تعديلاته)", danger=True):
            return
        kind, key = it.data(Qt.UserRole)
        if kind == "layout":
            L.reset(self.db, key)
        else:
            O.reset_template(self.db, key)
        self._fill_scopes()

    def save(self):
        for key, chk in (("print_show_room", self.room), ("print_color", self.color), ("print_one_file", self.one)):
            self.db.set_setting(key, int(chk.isChecked()))
        self.db.set_setting("print_dir", self.pdir.text().strip())
        self.db.log("تعديل خيارات الطباعة", "settings")
        info(self, "تم حفظ خيارات الطباعة.")

    def open_editor(self, kind: str):
        """يفتح محرر الطباعة على ورقة نموذجية من النوع المطلوب، في وضع التصميم."""
        from datetime import date

        from ...exporters import report_sheet as RS
        from ...utils import week_start
        from ..sheet_view import PreviewDialog
        db = self.db
        if kind == "report":
            doc = RS.ReportDoc("report", "تقرير نموذجي", ["معلومات التقرير"])
            doc.para("هذه ورقة نموذجية لتصميم شكل كل التقارير (الرأس، الجدول، الخطوط، التوقيعات).")
            doc.table(["البند", "القيمة", "النسبة"], [["مثال", "10", "50%"], ["مثال آخر", "20", "75%"]])
            sheets = RS.sheets(db, doc)
        else:
            if kind == "section":
                r = db.one("""SELECT sec.id tid, MAX(s.date) d FROM sections sec JOIN groups_ g ON g.section_id=sec.id
                              JOIN session_groups sg ON sg.group_id=g.id JOIN sessions s ON s.id=sg.session_id
                              WHERE s.date<=? GROUP BY sec.id ORDER BY d DESC LIMIT 1""", (date.today().isoformat(),))
            elif kind == "teacher":
                r = db.one("""SELECT teacher_id tid, MAX(date) d FROM sessions WHERE teacher_id IS NOT NULL AND date<=?
                              GROUP BY teacher_id ORDER BY d DESC LIMIT 1""", (date.today().isoformat(),))
            else:
                r = db.one("""SELECT room_id tid, MAX(date) d FROM sessions WHERE room_id IS NOT NULL AND date<=?
                              GROUP BY room_id ORDER BY d DESC LIMIT 1""", (date.today().isoformat(),))
            if not r or not r["tid"]:
                info(self, "لا توجد حصص بعد لعرض ورقة نموذجية من هذا النوع.")
                return
            sheets = [O.build(db, kind, r["tid"], week_start(date.fromisoformat(r["d"])))]
        dlg = PreviewDialog(db, sheets, self, self.room.isChecked(), self.color.isChecked())
        dlg.b_design.setChecked(True)
        dlg.exec()
        self._fill_scopes()


class SoundSettings(QWidget):
    """التنبيهات الصوتية: التفعيل، مستوى الصوت، كل نوع على حدة، ومدة التذكير قبل الحصة."""

    def __init__(self, ctx):
        super().__init__()
        from .. import sounds
        self.ctx, self.db, self.S = ctx, ctx.db, sounds
        o = sounds.load(self.db)
        v = QVBoxLayout(self)
        g = QGroupBox("التنبيهات الصوتية")
        f = QFormLayout(g)
        self.on = QCheckBox("تفعيل الأصوات")
        self.on.setChecked(bool(o["enabled"]))
        f.addRow(self.on)
        from PySide6.QtWidgets import QSlider, QSpinBox
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(o["volume"]))
        f.addRow("مستوى الصوت", self.vol)
        self.kinds = {}
        for k, lab in sounds.KINDS.items():
            row = QHBoxLayout()
            cb = QCheckBox(lab)
            cb.setChecked(bool(o.get(k, True)))
            self.kinds[k] = cb
            row.addWidget(cb)
            t = QPushButton(icon("mdi6.play-circle-outline"), "تجربة")
            t.clicked.connect(lambda _=False, k=k: self._test(k))
            row.addWidget(t)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            f.addRow(w)
        self.mins = QSpinBox()
        self.mins.setRange(1, 120)
        self.mins.setValue(int(o.get("reminder_min", 10)))
        self.mins.setSuffix(" دقيقة")
        f.addRow("التذكير قبل بداية الحصة بـ", self.mins)
        note = QLabel("التذكير يعمل ما دام البرنامج مفتوحاً. الأصوات قصيرة ومدمجة في البرنامج.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        f.addRow(note)
        v.addWidget(g)
        sv = QPushButton(icon("mdi6.content-save"), "حفظ")
        sv.setObjectName("Primary")
        sv.clicked.connect(self.save)
        v.addWidget(sv, 0, Qt.AlignLeft)
        v.addStretch()

    def values(self) -> dict:
        return {"enabled": self.on.isChecked(), "volume": self.vol.value(),
                **{k: cb.isChecked() for k, cb in self.kinds.items()}, "reminder_min": self.mins.value()}

    def _test(self, k):
        self.S.save(self.db, self.values())
        if not self.S.play(k, self.db, force=True):
            info(self, "تشغيل الصوت متاح على Windows فقط.")

    def save(self):
        self.S.save(self.db, self.values())
        info(self, "تم حفظ إعدادات الأصوات.")


# ====================================================================== البرمجة والتعارضات
class SchedulingSettings(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        inner = QWidget()
        v = QVBoxLayout(inner)
        g = QGroupBox("البرمجة الآلية")
        f = QFormLayout(g)
        self.limit = QSpinBox()
        self.limit.setRange(5, 600)
        self.limit.setSuffix(" ثانية")
        self.limit.setValue(int(self.db.get_setting("engine_time_limit", "30") or 30))
        f.addRow("المهلة الافتراضية لكل أسبوع", self.limit)
        self.weights = {}
        for k, lab in (("w_spread", "توزيع المادة على أيام الأسبوع"), ("w_compact", "تجميع حصص القسم بلا فراغات"),
                       ("w_teacher_pref", "احترام تفضيلات الأستاذ")):
            s = QSpinBox()
            s.setRange(0, 20)
            s.setValue(self.db.get_int(k))
            self.weights[k] = s
            f.addRow(f"وزن: {lab}", s)
        v.addWidget(g)
        g2 = QGroupBox("بطاقات المواد والتعويض")
        f2 = QFormLayout(g2)
        self.dur = QComboBox()
        for m in (60, 90, 120, 150, 180, 240):
            self.dur.addItem(f"{m / 60:g} سا", m)
        self.dur.setCurrentIndex(max(0, self.dur.findData(int(self.db.get_setting("default_minutes", "120") or 120))))
        f2.addRow("المدة الافتراضية لبطاقة مادة جديدة", self.dur)
        self.sub_limit = QSpinBox()
        self.sub_limit.setRange(3, 100)
        self.sub_limit.setValue(int(self.db.get_setting("sub_limit", "25") or 25))
        f2.addRow("عدد المعوّضين المقترحين لكل حصة", self.sub_limit)
        self.lunch = QCheckBox("فترة الغداء خاصة بكل قسم (حسب طوره أو إعداد القسم)")
        self.lunch.setChecked(self.db.get_setting("per_section_lunch", "1") != "0")
        f2.addRow("", self.lunch)
        v.addWidget(g2)
        g3 = QGroupBox("المواد المشتركة — نفس الأستاذ مع عدة أقسام في نفس الوقت لا يُعدّ تعارضاً")
        l3 = QVBoxLayout(g3)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة…")
        self.search.textChanged.connect(self._filter)
        l3.addWidget(self.search)
        self.only = QCheckBox("المشتركة فقط")
        self.only.toggled.connect(self._filter)
        l3.addWidget(self.only)
        self.subj = QTableWidget(0, 2)
        self.subj.setHorizontalHeaderLabels(["المادة", "مشتركة"])
        self.subj.verticalHeader().setVisible(False)
        self.subj.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.subj.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.subj.setMinimumHeight(260)
        rows = self.db.q("SELECT id, name, shareable FROM subjects ORDER BY shareable DESC, name")
        self.subj.setRowCount(len(rows))
        for i, r in enumerate(rows):
            it = QTableWidgetItem(r["name"])
            it.setData(Qt.UserRole, r["id"])
            self.subj.setItem(i, 0, it)
            c = QTableWidgetItem()
            c.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            c.setCheckState(Qt.Checked if r["shareable"] else Qt.Unchecked)
            self.subj.setItem(i, 1, c)
        l3.addWidget(self.subj)
        v.addWidget(g3)
        sv = QPushButton(icon("mdi6.content-save"), "حفظ")
        sv.setObjectName("Primary")
        sv.clicked.connect(self.save)
        v.addWidget(sv, 0, Qt.AlignLeft)
        v.addStretch()
        outer.addWidget(_scroll(inner))

    def _filter(self):
        t = self.search.text().strip()
        for i in range(self.subj.rowCount()):
            name = self.subj.item(i, 0).text()
            sh = self.subj.item(i, 1).checkState() == Qt.Checked
            self.subj.setRowHidden(i, bool((t and t not in name) or (self.only.isChecked() and not sh)))

    def save(self):
        db = self.db
        db.set_setting("engine_time_limit", self.limit.value())
        for k, s in self.weights.items():
            db.set_setting(k, s.value())
        db.set_setting("default_minutes", self.dur.currentData())
        db.set_setting("sub_limit", self.sub_limit.value())
        db.set_setting("per_section_lunch", int(self.lunch.isChecked()))
        n = 0
        with db.tx():
            for i in range(self.subj.rowCount()):
                sid = self.subj.item(i, 0).data(Qt.UserRole)
                val = int(self.subj.item(i, 1).checkState() == Qt.Checked)
                cur = db.scalar("SELECT shareable FROM subjects WHERE id=?", (sid,))
                if cur != val:
                    db.execute("UPDATE subjects SET shareable=? WHERE id=?", (val, sid))
                    n += 1
            db.log("تعديل إعدادات البرمجة", "settings", None, {"shareable_changed": n})
        self.ctx.changed("subjects")
        info(self, "تم الحفظ." + (f"\nتغيّرت {n} مادة مشتركة." if n else ""))


# ====================================================================== الجدول العام
class GridSettings(QWidget):
    CHECKS = [("show_teacher", "إظهار الأستاذ على البطاقة"), ("show_room", "إظهار القاعة على البطاقة"),
              ("show_time", "إظهار الوقت على البطاقة"), ("show_nonteach", "إظهار الحصص غير الدراسية"),
              ("show_fri", "إظهار الجمعة"), ("show_sat", "إظهار السبت"), ("show_night", "إظهار الفترة الليلية"),
              ("show_conflicts", "تمييز التعارضات بالأحمر"), ("show_tray", "إظهار الشريط السفلي"),
              ("show_done_mark", "علامة على الحصص المنجزة"), ("level_stripe", "شريط لون الطور بجانب القسم"),
              ("tray_only_section", "الشريط: مواد القسم فقط"), ("tray_history_first", "الشريط: السابقة أولاً"),
              ("ask_duration", "السؤال عن المدة عند وضع بطاقة من الشريط")]

    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        from .master import load_options
        o = load_options(self.db)
        v = QVBoxLayout(self)
        g = QGroupBox("الجدول العام — ما يظهر عند الفتح")
        grid = QGridLayout(g)
        self.chk = {}
        for i, (k, lab) in enumerate(self.CHECKS):
            c = QCheckBox(lab)
            c.setChecked(bool(o.get(k)))
            self.chk[k] = c
            grid.addWidget(c, i // 2, i % 2)
        v.addWidget(g)
        g2 = QGroupBox("الشكل")
        f = QFormLayout(g2)
        self.layout_cb = QComboBox()
        self.layout_cb.addItem("حسب الحصص (مثل aSc)", "periods")
        self.layout_cb.addItem("بالساعات (خانة لكل ساعة)", "hours")
        self.layout_cb.addItem("مقياس زمني كل 30 دقيقة", "time")
        self.layout_cb.setCurrentIndex(max(0, self.layout_cb.findData(o.get("layout", "periods"))))
        f.addRow("شكل الجدول", self.layout_cb)
        self.card = QComboBox()
        self.card.addItem("مملوءة باللون", "filled")
        self.card.addItem("إطار ملوّن", "outline")
        self.card.setCurrentIndex(max(0, self.card.findData(o.get("card_style", "filled"))))
        f.addRow("شكل البطاقة", self.card)
        self.font = QDoubleSpinBox()
        self.font.setRange(6, 15)
        self.font.setSingleStep(0.5)
        self.font.setValue(float(o.get("font_pt", 8.5)))
        f.addRow("حجم خط البطاقات", self.font)
        v.addWidget(g2)
        self.colors = CardColors(self.db)
        v.addWidget(self.colors)
        bar = QHBoxLayout()
        sv = QPushButton(icon("mdi6.content-save"), "حفظ")
        sv.setObjectName("Primary")
        sv.clicked.connect(self.save)
        rs = QPushButton(icon("mdi6.restore"), "الإعدادات الأصلية")
        rs.clicked.connect(self.reset)
        bar.addWidget(sv)
        bar.addWidget(rs)
        bar.addStretch()
        v.addLayout(bar)
        v.addStretch()

    def save(self):
        from .master import load_options, save_options
        o = load_options(self.db)
        for k, c in self.chk.items():
            o[k] = c.isChecked()
        o["layout"] = self.layout_cb.currentData()
        o["card_style"] = self.card.currentData()
        o["font_pt"] = self.font.value()
        save_options(self.db, o)
        self.colors.save()
        self.ctx.changed("grid_options")
        info(self, "تم الحفظ.")

    def reset(self):
        if confirm(self, "إرجاع إعدادات الجدول العام إلى الأصل؟"):
            self.db.set_setting("grid_options", "{}")
            self.ctx.changed("grid_options")
            from .master import load_options
            o = load_options(self.db)
            for k, c in self.chk.items():
                c.setChecked(bool(o.get(k)))
            self.layout_cb.setCurrentIndex(max(0, self.layout_cb.findData(o.get("layout", "periods"))))
            self.card.setCurrentIndex(max(0, self.card.findData(o.get("card_style", "filled"))))
            self.font.setValue(float(o.get("font_pt", 8.5)))
            from ..colors import DEFAULT_CONFIG, save_config
            save_config(self.db, dict(DEFAULT_CONFIG))
            self.colors.load()


# ====================================================================== ألوان البطاقات
class _Preview(QWidget):
    """معاينة حية: بطاقات نموذجية لكل عائلة بثلاث مواد، كما تظهر في الجدول العام."""

    SAMPLES = [("military", "رماية", 3), ("military", "طبوغرافيا", 8), ("military", "تربية بدنية", 13),
               ("specialty", "إعلام آلي", 4), ("specialty", "محاسبة", 9), ("specialty", "تموين", 14),
               ("general", "لغة فرنسية", 5), ("general", "تاريخ", 10), ("general", "قانون", 15),
               ("nonteach", "وجبة الغداء", 6)]

    def __init__(self):
        super().__init__()
        self.cfg = {}
        self.setMinimumHeight(150)

    def paintEvent(self, _):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter, QPen
        from .. import colors as C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cols = 5
        w = (self.width() - 12) / cols
        h = 52
        for i, (fam, name, sid) in enumerate(self.SAMPLES):
            r, c = divmod(i, cols)
            rect = QRectF(self.width() - 6 - (c + 1) * w + 3, 6 + r * (h + 8), w - 6, h)
            bg = C.subject_shade(fam, sid, self.cfg)
            p.setPen(QPen(bg.darker(118), 1))
            p.setBrush(bg)
            p.drawRoundedRect(rect, 6, 6)
            p.setPen(C.text_for(bg, self.cfg))
            p.drawText(rect, Qt.AlignCenter, f"{name}\n{C.FAMILY_LABELS[fam]}")
        p.end()


class CardColors(QGroupBox):
    """ألوان بطاقات الجدول العام (وضع التلوين «نوع المادة»): لوحة جاهزة، الشدة، لون لكل عائلة، لون الكتابة."""

    def __init__(self, db):
        super().__init__("ألوان البطاقات (التلوين حسب نوع المادة)")
        from PySide6.QtWidgets import QSlider
        from .. import colors as C
        self.db, self.C = db, C
        lay = QHBoxLayout(self)
        f = QFormLayout()
        self.preset = QComboBox()
        for k, pr in C.PRESETS.items():
            self.preset.addItem(pr["label"], k)
        f.addRow("اللوحة", self.preset)
        self.intensity = QSlider(Qt.Horizontal)
        self.intensity.setRange(0, 100)
        self.intensity.setToolTip("50 = اللوحة كما هي؛ أكثر = ألوان أقوى وأغمق، أقل = أهدأ وأفتح")
        f.addRow("الشدة", self.intensity)
        self.fam_btns = {}
        for fam in ("military", "specialty", "general"):
            row = QHBoxLayout()
            b = QPushButton()
            b.setMinimumWidth(110)
            b.clicked.connect(lambda _=False, fam=fam: self._pick(fam))
            x = QPushButton(icon("mdi6.close"), "")
            x.setToolTip("الرجوع إلى لون اللوحة")
            x.setFixedWidth(30)
            x.clicked.connect(lambda _=False, fam=fam: self._clear(fam))
            row.addWidget(b)
            row.addWidget(x)
            row.addStretch()
            w = QWidget()
            w.setLayout(row)
            self.fam_btns[fam] = b
            f.addRow(f"لون {C.FAMILY_LABELS[fam]}", w)
        self.text = QComboBox()
        self.text.addItem("تلقائي (حسب البطاقة)", "auto")
        self.text.addItem("أسود", "black")
        self.text.addItem("أبيض", "white")
        f.addRow("لون الكتابة", self.text)
        fw = QWidget()
        fw.setLayout(f)
        lay.addWidget(fw)
        self.preview = _Preview()
        self.preview.setMinimumWidth(420)
        lay.addWidget(self.preview, 1)
        self.families = {}
        self.load()
        self.preset.currentIndexChanged.connect(self._changed)
        self.intensity.valueChanged.connect(self._changed)
        self.text.currentIndexChanged.connect(self._changed)

    def load(self):
        o = self.C.load_config(self.db)
        for w in (self.preset, self.intensity, self.text):
            w.blockSignals(True)
        self.preset.setCurrentIndex(max(0, self.preset.findData(o.get("preset", "default"))))
        self.intensity.setValue(int(o.get("intensity", 50)))
        self.text.setCurrentIndex(max(0, self.text.findData(o.get("text", "auto"))))
        for w in (self.preset, self.intensity, self.text):
            w.blockSignals(False)
        self.families = dict(o.get("families") or {})
        self._changed()

    def values(self) -> dict:
        return {"preset": self.preset.currentData(), "intensity": self.intensity.value(),
                "families": dict(self.families), "text": self.text.currentData()}

    def _changed(self, *_):
        cfg = self.values()
        for fam, b in self.fam_btns.items():
            col = self.C.subject_shade(fam, 0, {**cfg, "intensity": 50}) if fam not in self.families \
                else self.C.QColor(self.families[fam])
            b.setText("مختار" if fam in self.families else "من اللوحة")
            b.setStyleSheet(f"background: {col.name()}; color: {self.C.text_for(col, cfg).name()};"
                            "border-radius: 6px; padding: 4px 10px;")
        self.preview.cfg = cfg
        self.preview.update()

    def _pick(self, fam):
        from PySide6.QtWidgets import QColorDialog
        cur = self.C.QColor(self.families.get(fam) or self.C.FAMILY_BASE[fam])
        col = QColorDialog.getColor(cur, self, f"لون {self.C.FAMILY_LABELS[fam]}")
        if col.isValid():
            self.families[fam] = col.name()
            self._changed()

    def _clear(self, fam):
        self.families.pop(fam, None)
        self._changed()

    def save(self):
        self.C.save_config(self.db, self.values())


# ====================================================================== قوالب Word
class WordTemplates(QGroupBox):
    """قوالب Word لأوراق الأقسام: قالب لكل طور، وقالب خاص لقسم يرث من طوره."""

    def __init__(self, ctx):
        super().__init__("قوالب Word لأوراق الأقسام (النظام الأساسي لإخراج الأقسام)")
        from ...exporters import word_tpl as W
        self.ctx, self.db, self.W = ctx, ctx.db, W
        v = QVBoxLayout(self)
        hint = QLabel("لكل طور ملف Word تعدّله في Word كما تريد (النصوص، الخطوط، الحدود، الشعار…). "
                      "اضغط «تعديل في Word»، عدّل واحفظ: يستورده البرنامج تلقائياً بعد فحصه. "
                      "الحقول بين قوسين تُملأ عند الإخراج، مثل {القسم} {الأسبوع} {من} {إلى}. "
                      "جدول الحصص يُعرف بعموده الأول (أسماء الأيام)، والبرنامج يملؤه ويضبط أعمدة الحصص.")
        hint.setWordWrap(True)
        hint.setObjectName("Muted")
        v.addWidget(hint)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["القالب", "الحالة", "آخر استيراد"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setMinimumHeight(170)
        self.table.doubleClicked.connect(lambda *_: self.edit())
        v.addWidget(self.table)
        row = QHBoxLayout()
        for text, ic, fn, tip in (
                ("تعديل في Word", "mdi6.microsoft-word", self.edit, "يفتح القالب المحدد في Word؛ الحفظ يُستورد تلقائياً"),
                ("قالب خاص لقسم…", "mdi6.google-classroom", self.section_tpl,
                 "قالب لقسم واحد يبدأ نسخةً من قالب طوره"),
                ("تجربة على قسم", "mdi6.file-eye-outline", self.try_it, "يملأ القالب بأسبوع حالي لأول قسم ويفتحه"),
                ("إرجاع إلى الافتراضي", "mdi6.restore", self.reset, "يحذف القالب المحدد فيعود إلى ما يرثه"),
                ("فتح مجلد القوالب", "mdi6.folder-open-outline", self.open_dir, "")):
            b = QPushButton(icon(ic), text)
            b.setToolTip(tip or text)
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        v.addLayout(row)
        from ..word_ui import watcher
        watcher(ctx).imported.connect(lambda *_: self.fill())
        self.fill()

    def scopes(self) -> list[tuple[str, str]]:
        out = []
        for r in self.db.q("SELECT id, code, name FROM levels ORDER BY COALESCE(sort, 99), id"):
            out.append((f"L{r['id']}", f"الطور {r['code'] or r['name']}"))
            for s in self.db.q("SELECT id, short, name FROM sections WHERE level_id=? ORDER BY sort, id", (r["id"],)):
                if self.W.stored(self.db, f"S{s['id']}"):
                    out.append((f"S{s['id']}", f"    └ القسم {s['short'] or s['name']}"))
        return out

    def fill(self):
        m = self.W.meta(self.db)
        sc = self.scopes()
        self.table.setRowCount(len(sc))
        for i, (scope, lab) in enumerate(sc):
            own = self.W.stored(self.db, scope) is not None
            st = "مخصص (معدَّل في Word)" if own else ("مولَّد من التصميم الحالي" if scope.startswith("L") else "يرث الطور")
            it = QTableWidgetItem(lab)
            it.setData(Qt.UserRole, scope)
            self.table.setItem(i, 0, it)
            self.table.setItem(i, 1, QTableWidgetItem(st))
            mm = m.get(scope) or {}
            self.table.setItem(i, 2, QTableWidgetItem(f"{mm.get('updated', '')} {mm.get('by', '')}".strip()))
        if sc and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def current(self) -> str | None:
        r = self.table.currentRow()
        it = self.table.item(r, 0) if r >= 0 else None
        return it.data(Qt.UserRole) if it else None

    def edit(self, scope: str | None = None):
        from ..word_ui import watcher
        scope = scope or self.current()
        if not scope:
            return
        try:
            p = watcher(self.ctx).open_for_edit(scope)
        except Exception as e:
            from ..widgets import error
            error(self, f"تعذر فتح القالب: {e}")
            return
        info(self, f"فُتح القالب في Word:\n{p}\n\nعدّل واحفظ (Ctrl+S)؛ يستورده البرنامج تلقائياً بعد كل حفظ "
                   "ما دام البرنامج مفتوحاً.", "قالب Word")

    def section_tpl(self):
        from PySide6.QtWidgets import QInputDialog
        rows = self.db.q("""SELECT s.id, s.short, s.name, l.code FROM sections s LEFT JOIN levels l ON l.id=s.level_id
                            JOIN formations f ON f.id=s.formation_id WHERE f.archived=0
                            ORDER BY COALESCE(l.sort, 99), s.sort, s.id""")
        if not rows:
            return
        labels = [f"{r['short'] or r['name']} — {r['code'] or ''}" for r in rows]
        lab, ok = QInputDialog.getItem(self, "قالب خاص لقسم", "القسم:", labels, 0, False)
        if not ok:
            return
        sid = rows[labels.index(lab)]["id"]
        scope = f"S{sid}"
        if not self.W.stored(self.db, scope):
            self.W.store(self.db, scope, self.W.scope_bytes(self.db, scope), "copy")
        self.fill()
        self.edit(scope)

    def try_it(self):
        import tempfile
        from datetime import date
        from pathlib import Path
        from ...exporters import official as O
        from ...exporters import week_export as WE
        scope = self.current()
        if not scope:
            return
        ws = date.today()
        if scope.startswith("S"):
            sid = int(scope[1:])
        else:
            secs = [s for s in WE.week_sections(self.db, ws)
                    if self.db.scalar("SELECT level_id FROM sections WHERE id=?", (s,)) == int(scope[1:])]
            sid = secs[0] if secs else self.db.scalar("SELECT id FROM sections WHERE level_id=? ORDER BY sort, id LIMIT 1",
                                                      (int(scope[1:]),))
        if not sid:
            info(self, "لا يوجد قسم في هذا الطور.")
            return
        sh = O.build_section_sheet(self.db, sid, ws)
        out = Path(tempfile.gettempdir()) / f"تجربة {self.W._safe(sh.name)}.docx"
        try:
            self.W.fill_to(self.db, sh, out)
        except Exception as e:
            from ..widgets import error
            error(self, f"تعذر ملء القالب: {e}")
            return
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out)))

    def reset(self):
        scope = self.current()
        if not scope or not self.W.stored(self.db, scope):
            info(self, "هذا القالب غير مخصص أصلاً.")
            return
        what = "يعود إلى قالب الطور" if scope.startswith("S") else "يُولَّد من جديد من التصميم الحالي"
        if confirm(self, f"حذف {self.W.scope_label(self.db, scope)}؟ {what}."):
            self.W.remove(self.db, scope)
            self.fill()

    def open_dir(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.W.templates_dir())))
