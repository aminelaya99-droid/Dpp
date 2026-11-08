"""استيراد ملفات aSc Timetables (.roz) وملفات Excel مع المعاينة والمطابقة."""
from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget,
                               QTextEdit, QVBoxLayout, QWidget)

from ...importers import excel as X
from ...importers.roz import RozError, parse_roz_file
from ...importers.roz_import import ImportOptions, import_roz, preview
from ..context import AppContext
from ..widgets import confirm, error, icon, info, page_title


class ImportPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        self.roz = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("الاستيراد", "استيراد البيانات من aSc Timetables (.roz) أو من Excel. "
                                              "تُعرض معاينة كاملة قبل أي تغيير في قاعدة البيانات."))
        tabs = QTabWidget()
        tabs.addTab(self._history_tab(), icon("mdi6.calendar-import"), "الأسابيع السابقة (aSc) + المخطط الزمني")
        tabs.addTab(self._roz_tab(), icon("mdi6.file-table-outline"), "ملف aSc Timetables (.roz)")
        tabs.addTab(self._excel_tab(), icon("mdi6.file-excel-outline"), "ملف Excel")
        lay.addWidget(tabs, 1)

    # ------------------------------------------------------------------ الأسابيع السابقة
    def _history_tab(self):
        from PySide6.QtWidgets import QDateEdit
        from PySide6.QtCore import QDate
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel("اختر ملفات الأسابيع (.roz) — رقم الأسبوع يُقرأ من اسم الملف (مثل 7.roz) ويمكن تعديله في الجدول. "
                           "تُستورد الحصص بتواريخها الفعلية، قابلة للتعديل، مع نسخة «الأصل المستورد» للرجوع إليها، "
                           "وتُتجاهل التعارضات الموجودة أصلاً في الملفات."))
        row = QHBoxLayout()
        pick = QPushButton(icon("mdi6.folder-open-outline"), "اختيار ملفات الأسابيع…")
        pick.setObjectName("Primary")
        pick.clicked.connect(self.pick_weeks)
        row.addWidget(pick)
        row.addWidget(QLabel("بداية الأسبوع الأول (الأحد):"))
        self.week1 = QDateEdit()
        self.week1.setCalendarPopup(True)
        self.week1.setDisplayFormat("dd/MM/yyyy")
        w1 = self.ctx.db.get_setting("week1_start", "2026-09-13") or "2026-09-13"
        self.week1.setDate(QDate.fromString(w1, "yyyy-MM-dd"))
        row.addWidget(self.week1)
        row.addStretch()
        v.addLayout(row)
        self.weeks_tbl = QTableWidget(0, 3)
        self.weeks_tbl.setHorizontalHeaderLabels(["الملف", "رقم الأسبوع", "الحصص (البطاقات)"])
        self.weeks_tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        v.addWidget(self.weeks_tbl, 1)
        self.hist_btn = QPushButton(icon("mdi6.database-import-outline"), "استيراد الأسابيع")
        self.hist_btn.setEnabled(False)
        self.hist_btn.clicked.connect(self.do_history)
        v.addWidget(self.hist_btn)
        box = QGroupBox("المخطط الزمني (Excel)")
        bl = QHBoxLayout(box)
        tl = QPushButton(icon("mdi6.chart-timeline"), "استيراد المخطط الزمني…")
        tl.clicked.connect(self.do_timeline)
        bl.addWidget(tl)
        bl.addWidget(QLabel("ورقة «مخطط زمني 2026-2027»: ألوان الخلايا ← استقبال، قاعدي مشترك، تخصصي، إجازة، امتحانات."))
        bl.addStretch()
        v.addWidget(box)
        self.hist_log = QTextEdit()
        self.hist_log.setReadOnly(True)
        self.hist_log.setMaximumHeight(170)
        v.addWidget(self.hist_log)
        return w

    def pick_weeks(self):
        import re
        from pathlib import Path
        paths, _ = QFileDialog.getOpenFileNames(self, "ملفات الأسابيع", "", "aSc Timetables (*.roz)")
        if not paths:
            return
        self.weeks_tbl.setRowCount(0)
        for i, pth in enumerate(sorted(paths, key=lambda x: int((re.findall(r"\d+", Path(x).stem) or [0])[-1]))):
            num = int((re.findall(r"\d+", Path(pth).stem) or [i + 1])[-1])
            try:
                n = len(parse_roz_file(pth).cards)
            except Exception as e:
                n = f"خطأ: {e}"
            r = self.weeks_tbl.rowCount()
            self.weeks_tbl.insertRow(r)
            it = QTableWidgetItem(Path(pth).name)
            it.setData(256, pth)
            self.weeks_tbl.setItem(r, 0, it)
            sp = QSpinBox()
            sp.setRange(1, 60)
            sp.setValue(num)
            self.weeks_tbl.setCellWidget(r, 1, sp)
            self.weeks_tbl.setItem(r, 2, QTableWidgetItem(str(n)))
        self.hist_btn.setEnabled(True)

    def do_history(self):
        from datetime import date as _d

        from PySide6.QtWidgets import QApplication

        from ...importers.history import import_history
        files = {}
        for r in range(self.weeks_tbl.rowCount()):
            files[self.weeks_tbl.cellWidget(r, 1).value()] = self.weeks_tbl.item(r, 0).data(256)
        if not files:
            return
        qd = self.week1.date()
        w1 = _d(qd.year(), qd.month(), qd.day())
        if w1.weekday() != 6:
            error(self, "بداية الأسبوع الأول يجب أن تكون يوم أحد.")
            return
        if not confirm(self, f"استيراد {len(files)} أسبوعاً؟ تُستبدل الحصص المستوردة سابقاً لنفس الأسابيع."):
            return
        self.hist_log.clear()

        def prog(msg):
            self.hist_log.append(msg)
            QApplication.processEvents()
        try:
            rep = import_history(self.ctx.db, files, week1=w1, progress=prog)
        except Exception as e:
            error(self, f"تعذر الاستيراد: {e}")
            return
        self.hist_log.append("\n" + rep.text())
        self.ctx.changed("*")
        info(self, "تم استيراد الأسابيع. افتح «الجدول العام» لمراجعتها وتعديلها.")

    def do_timeline(self):
        from ...importers.timeline import import_timeline
        path, _ = QFileDialog.getOpenFileName(self, "المخطط الزمني", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            r = import_timeline(self.ctx.db, path)
        except Exception as e:
            error(self, f"تعذر قراءة المخطط الزمني: {e}")
            return
        self.hist_log.append(f"المخطط الزمني: {r['rows']} صفاً، {r['weeks']} أسبوعاً.")
        self.ctx.changed("timeline")

    # ------------------------------------------------------------------ roz
    def _roz_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        pick = QPushButton(icon("mdi6.folder-open-outline"), "اختيار ملف .roz…")
        pick.setObjectName("Primary")
        pick.clicked.connect(self.pick_roz)
        self.roz_path = QLabel("لم يُختر ملف.")
        self.roz_path.setObjectName("Muted")
        row.addWidget(pick)
        row.addWidget(self.roz_path, 1)
        v.addLayout(row)
        self.roz_preview = QTextEdit()
        self.roz_preview.setReadOnly(True)
        v.addWidget(self.roz_preview, 1)
        box = QGroupBox("خيارات الاستيراد")
        f = QFormLayout(box)
        self.on_existing = QComboBox()
        self.on_existing.addItem("تجاهل العناصر الموجودة مسبقاً", "skip")
        self.on_existing.addItem("تحديث العناصر الموجودة", "update")
        f.addRow("العناصر الموجودة", self.on_existing)
        hl = QHBoxLayout()
        self.chk = {}
        for k, lab in [("subjects", "المواد"), ("teachers", "الأساتذة"), ("rooms", "القاعات"), ("classes", "الأقسام والأفواج"),
                       ("lessons", "الدروس ← متطلبات + أهلية")]:
            cb = QCheckBox(lab)
            cb.setChecked(True)
            self.chk[k] = cb
            hl.addWidget(cb)
        hw = QWidget()
        hw.setLayout(hl)
        f.addRow("ما يُستورد", hw)
        self.def_min = QComboBox()
        for m in (60, 90, 120, 180, 240):
            self.def_min.addItem(f"{m / 60:g} سا", m)
        self.def_min.setCurrentIndex(2)
        f.addRow("مدة الحصة الافتراضية للمتطلبات", self.def_min)
        self.target_lbl = QLabel()
        f.addRow("التكوين الهدف", self.target_lbl)
        v.addWidget(box)
        self.roz_btn = QPushButton(icon("mdi6.database-import-outline"), "استيراد إلى التكوين الحالي")
        self.roz_btn.setEnabled(False)
        self.roz_btn.clicked.connect(self.do_roz)
        v.addWidget(self.roz_btn)
        self.ctx.formation_changed.connect(lambda _: self._target())
        self._target()
        return w

    def _target(self):
        f = self.ctx.db.one("SELECT name FROM formations WHERE id=?", (self.ctx.formation_id or -1,))
        if self.ctx.all_formations and f:
            self.target_lbl.setText(f"{f['name']}  (وضع «كل التكوينات»: اختر تكويناً محدداً من الأعلى لتغيير الهدف)")
        else:
            self.target_lbl.setText(f["name"] if f else "⚠ لا يوجد تكوين — أنشئ تكويناً أولاً")

    def pick_roz(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختيار ملف aSc Timetables", "", "aSc Timetables (*.roz);;كل الملفات (*)")
        if path:
            self.load_roz(path)

    def load_roz(self, path):
        self.roz_path.setText(path)
        try:
            self.roz = parse_roz_file(path)
        except RozError as e:
            self.roz = None
            self.roz_preview.setPlainText(str(e))
            self.roz_btn.setEnabled(False)
            return
        except Exception as e:
            self.roz = None
            self.roz_preview.setPlainText(f"تعذرت قراءة الملف: {e}\nقد يكون إصداراً غير مدعوم من aSc.")
            self.roz_btn.setEnabled(False)
            return
        p = preview(self.roz)
        lines = ["<h3>ملخص الملف</h3><ul>"] + [f"<li>{k}: <b>{v}</b></li>" for k, v in p["summary"].items()] + ["</ul>"]
        for k, ex in p["examples"].items():
            lines.append(f"<p><b>{k}</b> (أمثلة): " + "، ".join(ex) + "</p>")
        for k, d in p["duplicates"].items():
            if d:
                lines.append(f"<p style='color:#B7791F'>مكررات في {k}: " + "، ".join(d[:10]) + "</p>")
        lines.append(f"<p>أساتذة غير مستعملين في أي درس: {p['unused_teachers']}</p>")
        lines.append(f"<p>دروس بلا أستاذ: {p['lessons_without_teacher']}</p>")
        if p["generic_teachers"]:
            lines.append(f"<p>سجلات «أساتذة» تبدو جهات/مسؤوليات وليست أشخاصاً ({len(p['generic_teachers'])}): "
                         + "، ".join(p["generic_teachers"][:5]) + "…</p>")
        lines.append("<h3>تحذيرات</h3><ul>" + "".join(f"<li>{w}</li>" for w in p["warnings"]) + "</ul>")
        lines.append("<p>تُفصل الرتبة عن الاسم تلقائياً (صيغة «الرتبة: الاسم») ويُقترح التصنيف (م م م، م م ش، أ ت ج، عسكري…).</p>")
        self.roz_preview.setHtml("".join(lines))
        self.roz_btn.setEnabled(bool(self.ctx.formation_id))

    def do_roz(self):
        if not self.roz or not self.ctx.formation_id:
            return
        if not confirm(self, "بدء الاستيراد؟ تُنفذ العملية داخل معاملة واحدة: إما تنجح كلها أو لا يتغير شيء."):
            return
        opt = ImportOptions(formation_id=self.ctx.formation_id, on_existing=self.on_existing.currentData(),
                            import_subjects=self.chk["subjects"].isChecked(), import_teachers=self.chk["teachers"].isChecked(),
                            import_rooms=self.chk["rooms"].isChecked(), import_classes=self.chk["classes"].isChecked(),
                            import_lessons=self.chk["lessons"].isChecked(), default_session_minutes=self.def_min.currentData())
        try:
            rep = import_roz(self.ctx.db, self.roz, opt)
        except Exception as e:
            error(self, f"فشل الاستيراد ولم يتغير شيء:\n{e}")
            return
        self.ctx.changed("*")
        info(self, "اكتمل الاستيراد:\n\n" + rep.text())

    # ------------------------------------------------------------------ Excel
    def _excel_tab(self):
        w = QWidget()
        v = QVBoxLayout(w)
        row = QHBoxLayout()
        self.entity = QComboBox()
        for k, d in X.ENTITIES.items():
            self.entity.addItem(d["label"], k)
        self.entity.currentIndexChanged.connect(self._rebuild_mapping)
        pick = QPushButton(icon("mdi6.folder-open-outline"), "اختيار ملف Excel…")
        pick.clicked.connect(self.pick_excel)
        self.x_path = QLabel()
        self.x_path.setObjectName("Muted")
        row.addWidget(QLabel("نوع البيانات:"))
        row.addWidget(self.entity)
        row.addWidget(pick)
        row.addWidget(self.x_path, 1)
        v.addLayout(row)
        self.map_box = QGroupBox("مطابقة الأعمدة")
        self.map_form = QFormLayout(self.map_box)
        v.addWidget(self.map_box)
        self.x_table = QTableWidget()
        self.x_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.x_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        v.addWidget(self.x_table, 1)
        self.x_issues = QLabel()
        self.x_issues.setWordWrap(True)
        v.addWidget(self.x_issues)
        hb = QHBoxLayout()
        val = QPushButton(icon("mdi6.check-decagram-outline"), "التحقق")
        val.clicked.connect(self.validate_excel)
        imp = QPushButton(icon("mdi6.database-import-outline"), "استيراد")
        imp.setObjectName("Primary")
        imp.clicked.connect(self.do_excel)
        hb.addWidget(val)
        hb.addWidget(imp)
        hb.addStretch()
        v.addLayout(hb)
        self.headers, self.rows, self.map_combos = [], [], {}
        return w

    def pick_excel(self):
        path, _ = QFileDialog.getOpenFileName(self, "اختيار ملف Excel", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            self.headers, self.rows = X.read_sheet(path)
        except Exception as e:
            error(self, f"تعذرت قراءة الملف: {e}")
            return
        self.x_path.setText(path)
        self.x_table.setColumnCount(len(self.headers))
        self.x_table.setHorizontalHeaderLabels(self.headers)
        self.x_table.setRowCount(min(200, len(self.rows)))
        for i, r in enumerate(self.rows[:200]):
            for j, val in enumerate(r):
                self.x_table.setItem(i, j, QTableWidgetItem("" if val is None else str(val)))
        self._rebuild_mapping()

    def _rebuild_mapping(self):
        while self.map_form.rowCount():
            self.map_form.removeRow(0)
        ent = self.entity.currentData()
        guess = X.guess_mapping(ent, self.headers) if self.headers else {}
        self.map_combos = {}
        for key, label in X.ENTITIES[ent]["fields"].items():
            cb = QComboBox()
            cb.addItem("— غير مطابق —", None)
            for i, h in enumerate(self.headers):
                cb.addItem(h, i)
            if guess.get(key) is not None:
                cb.setCurrentIndex(cb.findData(guess[key]))
            self.map_combos[key] = cb
            self.map_form.addRow(label, cb)

    def _mapping(self):
        return {k: cb.currentData() for k, cb in self.map_combos.items()}

    def validate_excel(self):
        if not self.rows:
            info(self, "اختر ملفاً أولاً.")
            return []
        issues = X.validate(self.entity.currentData(), self._mapping(), self.rows)
        self.x_issues.setText("✓ لا توجد أخطاء." if not issues else
                              "\n".join(f"سطر {i.row}: {i.message}" if i.row else i.message for i in issues[:30]))
        return issues

    def do_excel(self):
        issues = self.validate_excel()
        if any(i.row == 0 for i in issues):
            return
        if issues and not confirm(self, f"توجد {len(issues)} مشكلة؛ السطور الخاطئة ستُتجاهل. متابعة؟"):
            return
        try:
            res = X.import_rows(self.ctx.db, self.entity.currentData(), self._mapping(), self.rows, self.ctx.formation_id)
        except ValueError as e:
            error(self, str(e))
            return
        self.ctx.changed("*")
        info(self, f"أضيف {res.added} سجل، وتُجوهل {res.skipped} (موجود مسبقاً أو خاطئ).")
