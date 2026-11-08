"""صفحة المقرر: الحجم الساعي المقرر لكل مادة (حسب الطور والاختصاص)، استيراده من Excel، ومراجعة ما لم يُعرف."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QStyledItemDelegate, QCheckBox, QComboBox, QCompleter, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFileDialog, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from ...importers import curriculum as CI
from ...services import progress as P
from .. import theme
from ..widgets import confirm, error, icon, info, page_title


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.verticalHeader().setVisible(False)
    t.setAlternatingRowColors(True)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    t.horizontalHeader().setStretchLastSection(True)
    return t


_MODEL_CACHE: dict = {}


def _subject_model(db):
    """نموذج مشترك لقوائم المواد (بناء قائمة لكل سطر بطيء جداً)."""
    from PySide6.QtGui import QStandardItem, QStandardItemModel
    key = (id(db), db.scalar("SELECT COUNT(*) || '-' || COALESCE(MAX(id),0) FROM subjects"))
    if _MODEL_CACHE.get("key") != key:
        m = QStandardItemModel()
        it = QStandardItem("— اختر مادة —")
        it.setData(None, Qt.UserRole)
        m.appendRow(it)
        for r in db.q("SELECT id, name FROM subjects WHERE COALESCE(kind,'teach')<>'nonteach' ORDER BY name"):
            it = QStandardItem(r["name"])
            it.setData(r["id"], Qt.UserRole)
            m.appendRow(it)
        _MODEL_CACHE.update(key=key, model=m)
    return _MODEL_CACHE["model"]


def _subject_combo(db, current=None) -> QComboBox:
    cb = QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    cb.setModel(_subject_model(db))
    comp = cb.completer()
    comp.setFilterMode(Qt.MatchContains)
    comp.setCompletionMode(QCompleter.PopupCompletion)
    i = cb.findData(current) if current else 0
    cb.setCurrentIndex(max(0, i))
    cb.setMinimumWidth(300)
    return cb


def _spec_combo(db, level_id, current) -> QComboBox:
    cb = QComboBox()
    cb.addItem("كل اختصاصات الطور", None)
    for r in db.q("SELECT id, name FROM specialties WHERE level_id=? ORDER BY name", (level_id or -1,)):
        cb.addItem(r["name"], r["id"])
    i = cb.findData(current)
    cb.setCurrentIndex(max(0, i))
    return cb


class _Ref:
    """يقرأ قيمة الخانة بنفس واجهة QDoubleSpinBox/QComboBox (value / currentData)."""

    def __init__(self, item, role):
        self.item, self.role = item, role

    def value(self):
        return float(self.item.data(self.role) or 0)

    def currentData(self):
        return self.item.data(self.role)


class SubjectDelegate(QStyledItemDelegate):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

    def createEditor(self, parent, option, index):
        cb = _subject_combo(self.db, index.data(Qt.UserRole))
        cb.setParent(parent)
        return cb

    def setEditorData(self, editor, index):
        i = editor.findData(index.data(Qt.UserRole))
        editor.setCurrentIndex(max(0, i))

    def setModelData(self, editor, model, index):
        sid = editor.currentData()
        model.setData(index, editor.currentText() if sid else "— اختر مادة (نقر مزدوج) —", Qt.DisplayRole)
        model.setData(index, sid, Qt.UserRole)


# ====================================================================== مراجعة الاستيراد
class ImportReview(QDialog):
    """كل كتلة في الملف ← طور واختصاص (تخمين آلي يمكن تغييره)."""

    def __init__(self, db, blocks: list, parent=None):
        super().__init__(parent)
        self.db, self.blocks = db, blocks
        self.setWindowTitle(f"مراجعة استيراد المقرر — {len(blocks)} كتلة")
        self.resize(1150, 640)
        v = QVBoxLayout(self)
        v.addWidget(QLabel("تحقق من الطور والاختصاص لكل كتلة في الملف. نأخذ عمود «المقرر» فقط. المواد غير المعروفة "
                           "والقيم المتعارضة تذهب إلى «مواد تحتاج مراجعة» لتعدّلها وتدخلها بنفسك."))
        self.t = _table(["إدخال", "السطر", "الكتلة في الملف", "الطور", "الاختصاص", "مواد معروفة", "تحتاج مراجعة",
                         "المجموع"])
        v.addWidget(self.t, 1)
        self.levels = [(r["id"], f"{r['code'] or ''} — {r['name']}") for r in db.q("SELECT * FROM levels ORDER BY sort, id")]
        self.t.setRowCount(len(blocks))
        self.w = []
        for i, b in enumerate(blocks):
            chk = QCheckBox()
            chk.setChecked(bool(b.level_id) and not b.skip)
            lv = QComboBox()
            lv.addItem("— غير معروف —", None)
            for lid, lab in self.levels:
                lv.addItem(lab, lid)
            lv.setCurrentIndex(max(0, lv.findData(b.level_id)))
            sp = _spec_combo(db, b.level_id, b.specialty_id)
            lv.currentIndexChanged.connect(lambda _=0, i=i: self._level_changed(i))
            ok = sum(1 for r in b.rows if r.status == "ok")
            bad = sum(1 for r in b.rows if r.status == "unmatched")
            self.t.setCellWidget(i, 0, chk)
            self.t.setItem(i, 1, QTableWidgetItem(str(b.excel_row)))
            it = QTableWidgetItem(b.header)
            it.setToolTip(b.header + (f"\n{b.note}" if b.note else ""))
            if b.note:
                it.setForeground(QColor(theme.CURRENT["warn"]))
            self.t.setItem(i, 2, it)
            self.t.setCellWidget(i, 3, lv)
            self.t.setCellWidget(i, 4, sp)
            self.t.setItem(i, 5, QTableWidgetItem(str(ok)))
            bi = QTableWidgetItem(str(bad))
            if bad:
                bi.setForeground(QColor(theme.CURRENT["warn"]))
            self.t.setItem(i, 6, bi)
            self.t.setItem(i, 7, QTableWidgetItem(f"{b.total:g}" if b.total else "—"))
            self.w.append((chk, lv, sp))
        self.t.resizeColumnsToContents()
        self.t.setColumnWidth(2, 420)
        self.replace = QCheckBox("استبدال المقرر المستورد سابقاً (ما أدخلته يدوياً لا يُمس)")
        self.replace.setChecked(True)
        v.addWidget(self.replace)
        bb = QDialogButtonBox()
        ok = bb.addButton("إدخال المقرر", QDialogButtonBox.AcceptRole)
        ok.setObjectName("Primary")
        bb.addButton("إلغاء", QDialogButtonBox.RejectRole)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _level_changed(self, i):
        chk, lv, sp = self.w[i]
        new = _spec_combo(self.db, lv.currentData(), None)
        self.t.setCellWidget(i, 4, new)
        self.w[i] = (chk, lv, new)
        chk.setChecked(bool(lv.currentData()))

    def result_blocks(self):
        for b, (chk, lv, sp) in zip(self.blocks, self.w):
            b.skip = not chk.isChecked()
            b.level_id = lv.currentData()
            b.specialty_id = sp.currentData()
        return self.blocks


# ====================================================================== الصفحة
class CurriculumPage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("المقرر",
                                 "الحجم الساعي المقرر لكل مادة حسب الطور والاختصاص — منه تُحسب نسبة الإنجاز ونسبة "
                                 "التنفيذ. استورد التقرير الشهري (Excel) ثم راجع المواد التي لم تُعرف."))
        bar = QHBoxLayout()
        b_imp = QPushButton(icon("mdi6.file-excel-outline"), "استيراد من Excel…")
        b_imp.setObjectName("Primary")
        b_imp.clicked.connect(self.import_file)
        bar.addWidget(b_imp)
        b_add = QPushButton(icon("mdi6.plus"), "إضافة مادة للمقرر")
        b_add.clicked.connect(self.add_row)
        bar.addWidget(b_add)
        b_del = QPushButton(icon("mdi6.delete-outline"), "حذف")
        b_del.clicked.connect(self.delete_rows)
        bar.addWidget(b_del)
        bar.addSpacing(12)
        self.level = QComboBox()
        self.level.addItem("كل الأطوار", None)
        for r in self.db.q("SELECT * FROM levels ORDER BY sort, id"):
            self.level.addItem(f"{r['code'] or ''} — {r['name']}", r["id"])
        self.level.currentIndexChanged.connect(self._level_filter)
        bar.addWidget(self.level)
        self.spec = QComboBox()
        self.spec.addItem("كل الاختصاصات", "all")
        self.spec.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.spec)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search, 1)
        lay.addLayout(bar)
        self.tabs = QTabWidget()
        self.t = _table(["الطور", "الاختصاص", "المادة", "المقرر (سا)", "المصدر"])
        self.t.setSortingEnabled(True)
        self.t.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.t.cellDoubleClicked.connect(self._edit_hours)
        self.tabs.addTab(self.t, icon("mdi6.book-clock-outline"), "المقرر")
        w = QWidget()
        wl = QVBoxLayout(w)
        wl.setContentsMargins(0, 6, 0, 0)
        ib = QHBoxLayout()
        self.show_done = QCheckBox("إظهار ما عولج")
        self.show_done.toggled.connect(self.refresh_issues)
        ib.addWidget(self.show_done)
        ib.addStretch()
        for text, ic, fn in (("إدخال المحدد", "mdi6.check", self.resolve_selected),
                             ("مادة جديدة بنفس الاسم", "mdi6.book-plus-outline", self.new_subject),
                             ("تجاهل", "mdi6.close", self.dismiss_selected)):
            b = QPushButton(icon(ic), text)
            b.clicked.connect(fn)
            ib.addWidget(b)
        wl.addLayout(ib)
        self.ti = _table(["الطور", "الاختصاص", "المادة في الملف", "المقرر", "مادة البرنامج", "السبب", "الكتلة"])
        self.ti.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed)
        self.ti.setItemDelegateForColumn(4, SubjectDelegate(self.db, self.ti))
        self.ti.setSelectionMode(QAbstractItemView.ExtendedSelection)
        wl.addWidget(self.ti, 1)
        hint = QLabel("اختر «مادة البرنامج» المناسبة وصحّح الساعات إن لزم، ثم «إدخال المحدد». "
                      "القيمتان المتعارضتان: أدخل الصحيحة فتُغلق الأخرى تلقائياً.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        wl.addWidget(hint)
        self.tabs.addTab(w, icon("mdi6.alert-circle-outline"), "مواد تحتاج مراجعة")
        lay.addWidget(self.tabs, 1)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        lay.addWidget(self.count)
        ctx.data_changed.connect(lambda wh: self.refresh() if wh in ("*", "curriculum", "subjects") else None)
        self.refresh()

    # ------------------------------------------------------------------
    def _level_filter(self):
        self.spec.blockSignals(True)
        self.spec.clear()
        self.spec.addItem("كل الاختصاصات", "all")
        self.spec.addItem("مشترك للطور", 0)
        for r in self.db.q("SELECT id, name FROM specialties WHERE level_id=? ORDER BY name",
                           (self.level.currentData() or -1,)):
            self.spec.addItem(r["name"], r["id"])
        self.spec.blockSignals(False)
        self.refresh()

    def refresh(self):
        lv, sp = self.level.currentData(), self.spec.currentData()
        sql = """SELECT c.*, l.code lcode, l.name lname, sp.name spname, s.name sname FROM curriculum c
                 JOIN levels l ON l.id=c.level_id JOIN subjects s ON s.id=c.subject_id
                 LEFT JOIN specialties sp ON sp.id=c.specialty_id WHERE 1=1"""
        p = []
        if lv:
            sql += " AND c.level_id=?"
            p.append(lv)
        if sp != "all" and sp is not None:
            sql += " AND c.specialty_id=?"
            p.append(sp)
        sql += " ORDER BY l.sort, l.id, spname, s.name"
        rows = self.db.q(sql, p)
        self.rows = [dict(r) for r in rows]
        t = self.t
        t.setSortingEnabled(False)
        t.setRowCount(len(rows))
        for i, r in enumerate(self.rows):
            vals = [r["lcode"] or r["lname"], r["spname"] or "كل الاختصاصات", r["sname"], f"{r['hours']:g}",
                    {"import": "مستورد", "manual": "يدوي"}.get(r["source"], r["source"] or "")]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 0:
                    it.setData(Qt.UserRole, i)
                if j == 3:
                    it.setTextAlignment(Qt.AlignCenter)
                    it.setToolTip("نقر مزدوج للتعديل")
                t.setItem(i, j, it)
        t.resizeColumnsToContents()
        t.setSortingEnabled(True)
        self._filter()
        self.refresh_issues()

    def _filter(self):
        txt = self.search.text().strip()
        for i in range(self.t.rowCount()):
            it = self.t.item(i, 2)
            self.t.setRowHidden(i, bool(txt) and (it is None or txt not in it.text()))
        for i in range(self.ti.rowCount()):
            it = self.ti.item(i, 2)
            self.ti.setRowHidden(i, bool(txt) and (it is None or txt not in it.text()))

    def refresh_issues(self):
        cond = "" if self.show_done.isChecked() else "AND ci.resolved=0"
        lv = self.level.currentData()
        rows = self.db.q(f"""SELECT ci.*, l.code lcode, sp.name spname FROM curriculum_issues ci
                             LEFT JOIN levels l ON l.id=ci.level_id LEFT JOIN specialties sp ON sp.id=ci.specialty_id
                             WHERE 1=1 {cond} {'AND ci.level_id=' + str(int(lv)) if lv else ''}
                             ORDER BY l.sort, l.id, spname, ci.name""")
        self.issues = [dict(r) for r in rows]
        t = self.ti
        t.setUpdatesEnabled(False)
        t.setRowCount(len(self.issues))
        self.issue_w = []
        names = {r[0]: r[1] for r in self.db.q("SELECT id, name FROM subjects")}
        ro = Qt.ItemIsSelectable | Qt.ItemIsEnabled
        for i, r in enumerate(self.issues):
            cells = [QTableWidgetItem(r["lcode"] or "—"), QTableWidgetItem(r["spname"] or "كل الاختصاصات"),
                     QTableWidgetItem(r["name"])]
            cells[2].setData(Qt.UserRole, i)
            if r["resolved"]:
                cells[2].setForeground(QColor(theme.CURRENT["muted"]))
            for j, it in enumerate(cells):
                it.setFlags(ro)
                t.setItem(i, j, it)
            hs = QTableWidgetItem()
            hs.setData(Qt.EditRole, float(r["hours"] or 0))
            hs.setTextAlignment(Qt.AlignCenter)
            hs.setToolTip("نقر مزدوج لتصحيح الساعات")
            t.setItem(i, 3, hs)
            cb = QTableWidgetItem(names.get(r["guess_subject_id"], "— اختر مادة (نقر مزدوج) —"))
            cb.setData(Qt.UserRole, r["guess_subject_id"])
            cb.setToolTip("نقر مزدوج لاختيار مادة البرنامج (اكتب للبحث)")
            if not r["guess_subject_id"]:
                cb.setForeground(QColor(theme.CURRENT["warn"]))
            t.setItem(i, 4, cb)
            rs = QTableWidgetItem(r["reason"] or "" if not r["resolved"] else ("أُدخلت" if r["resolved"] == 1 else "تُجوهلت"))
            if not r["resolved"]:
                rs.setForeground(QColor(theme.CURRENT["warn"]))
            rs.setFlags(ro)
            t.setItem(i, 5, rs)
            bl = QTableWidgetItem(r["block"] or "")
            bl.setFlags(ro)
            t.setItem(i, 6, bl)
            self.issue_w.append((_Ref(hs, Qt.EditRole), _Ref(cb, Qt.UserRole)))
        t.resizeColumnsToContents()
        t.setColumnWidth(4, 320)
        t.setUpdatesEnabled(True)
        open_n = sum(1 for r in self.issues if not r["resolved"])
        self.tabs.setTabText(1, f"مواد تحتاج مراجعة ({open_n})")
        self.count.setText(f"{len(self.rows)} مادة في المقرر · {open_n} تحتاج مراجعة")
        self._filter()

    # ------------------------------------------------------------------ أوامر
    def import_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "ملف المقرر (نسبة تنفيذ برامج التكوين)", "", "Excel (*.xlsx *.xlsm)")
        if not path:
            return
        try:
            blocks = CI.analyze(self.db, path)
        except Exception as e:
            error(self, f"تعذرت قراءة الملف: {e}")
            return
        if not blocks:
            error(self, "لم أجد في الملف كتلاً تبدأ بـ «الفئة : … الإختصاص : …».")
            return
        d = ImportReview(self.db, blocks, self)
        if d.exec() != QDialog.Accepted:
            return
        try:
            res = CI.apply(self.db, d.result_blocks(), d.replace.isChecked())
        except Exception as e:
            error(self, f"تعذر الإدخال: {e}")
            return
        self.ctx.changed("curriculum")
        info(self, f"أُدخل المقرر لـ {res['imported']} مادة.\n"
                   f"{res['issues']} مادة تحتاج مراجعة (غير معروفة أو بقيم متعارضة) — في تبويب «مواد تحتاج مراجعة».")
        if res["issues"]:
            self.tabs.setCurrentIndex(1)

    def _edit_hours(self, row, col):
        it = self.t.item(row, 0)
        if it is None:
            return
        r = self.rows[it.data(Qt.UserRole)]
        v, ok = QInputDialog.getDouble(self, "المقرر", f"الحجم الساعي المقرر لمادة «{r['sname']}»", r["hours"], 0, 5000, 1)
        if ok:
            P.set_hours(self.db, r["level_id"], r["specialty_id"] or None, r["subject_id"], r["phase"], v)
            self.ctx.changed("curriculum")

    def add_row(self):
        lv = self.level.currentData()
        if not lv:
            info(self, "اختر الطور أولاً من القائمة.")
            return
        d = QDialog(self)
        d.setWindowTitle("إضافة مادة للمقرر")
        v = QVBoxLayout(d)
        sp = _spec_combo(self.db, lv, self.spec.currentData() if self.spec.currentData() not in ("all", 0) else None)
        cb = _subject_combo(self.db)
        hs = QDoubleSpinBox()
        hs.setRange(0, 5000)
        hs.setDecimals(1)
        for lab, w in (("الاختصاص", sp), ("المادة", cb), ("المقرر (سا)", hs)):
            row = QHBoxLayout()
            row.addWidget(QLabel(lab))
            row.addWidget(w, 1)
            v.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        v.addWidget(bb)
        if d.exec() == QDialog.Accepted and cb.currentData():
            P.set_hours(self.db, lv, sp.currentData(), cb.currentData(), "all", hs.value())
            self.ctx.changed("curriculum")

    def delete_rows(self):
        idx = sorted({self.t.item(i.row(), 0).data(Qt.UserRole) for i in self.t.selectedIndexes()})
        if not idx or not confirm(self, f"حذف {len(idx)} سطر من المقرر؟", danger=True):
            return
        with self.db.tx():
            for i in idx:
                self.db.execute("DELETE FROM curriculum WHERE id=?", (self.rows[i]["id"],))
            self.db.log("حذف من المقرر", "curriculum", None, {"n": len(idx)})
        self.ctx.changed("curriculum")

    def _selected_issues(self):
        out = []
        for row in sorted({i.row() for i in self.ti.selectedIndexes()}):
            it = self.ti.item(row, 2)
            if it is not None:
                k = it.data(Qt.UserRole)
                out.append((self.issues[k], self.issue_w[k]))
        return out

    def resolve_selected(self):
        sel = self._selected_issues()
        if not sel:
            info(self, "حدد سطراً أو أكثر.")
            return
        n, miss = 0, 0
        for r, (hs, cb) in sel:
            if not r["level_id"] or not cb.currentData():
                miss += 1
                continue
            CI.resolve_issue(self.db, r["id"], r["level_id"], r["specialty_id"], cb.currentData(), hs.value())
            n += 1
        self.ctx.changed("curriculum")
        info(self, f"أُدخلت {n} مادة." + (f"\n{miss} بلا مادة أو بلا طور: اخترها أولاً." if miss else ""))

    def new_subject(self):
        sel = self._selected_issues()
        if not sel:
            info(self, "حدد سطراً.")
            return
        from ...services.structure import arabic_short, subject_category
        from ...utils import unique_abbrev
        shorts = {r[0] for r in self.db.q("SELECT short FROM subjects WHERE short IS NOT NULL")}
        n = 0
        for r, (hs, cb) in sel:
            if not r["level_id"]:
                continue
            name = " ".join(r["name"].split())
            sid = self.db.scalar("SELECT id FROM subjects WHERE name=?", (name,))
            if not sid:
                ab = unique_abbrev(arabic_short(name), shorts)
                shorts.add(ab)
                sid = self.db.insert("subjects", name=name, short=ab, category=subject_category(name), kind="teach")
            CI.resolve_issue(self.db, r["id"], r["level_id"], r["specialty_id"], sid, hs.value())
            n += 1
        self.ctx.changed("subjects")
        info(self, f"أُضيفت {n} مادة جديدة إلى المواد وإلى المقرر.")

    def dismiss_selected(self):
        sel = self._selected_issues()
        if sel and confirm(self, f"تجاهل {len(sel)} سطر؟"):
            for r, _w in sel:
                CI.dismiss_issue(self.db, r["id"])
            self.refresh_issues()
