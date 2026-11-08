"""لوحة «أولويات الأسبوع» للبرمجة الآلية: المواد المتأخرة أولاً، مواد بساعات محددة، إنهاء مادة بتاريخ،
وقواعد اليوم — مع معاينة الخطة قبل التشغيل."""
from __future__ import annotations

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QCompleter, QDateEdit, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTimeEdit, QVBoxLayout, QWidget)

from ...services import priorities as PRI
from ..widgets import error, icon, info


def _table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    t.setMinimumHeight(110)
    return t


def subject_combo(db, kinds_teach=True) -> QComboBox:
    cb = QComboBox()
    cb.setEditable(True)
    cb.setInsertPolicy(QComboBox.NoInsert)
    for r in db.q("SELECT id, name FROM subjects WHERE COALESCE(kind,'teach')<>'nonteach' ORDER BY name"):
        cb.addItem(r["name"], r["id"])
    comp = QCompleter([cb.itemText(i) for i in range(cb.count())], cb)
    comp.setFilterMode(Qt.MatchContains)
    cb.setCompleter(comp)
    return cb


class ScopeRowDialog(QDialog):
    """سطر هدف: النطاق (قسم/طور/اختصاص) + المادة + الساعات أو تاريخ الإنهاء."""

    def __init__(self, parent, db, formation_ids, with_date=False):
        super().__init__(parent)
        self.db = db
        self.setWindowTitle("إنهاء مادة بتاريخ" if with_date else "مادة بساعات محددة")
        f = QFormLayout(self)
        self.scope = QComboBox()
        for k, lab in PRI.SCOPE_LABELS.items():
            self.scope.addItem(lab, k)
        self.ref = QComboBox()
        self.scope.currentIndexChanged.connect(self._fill)
        self.fids = formation_ids
        f.addRow("النطاق", self.scope)
        f.addRow("", self.ref)
        self.sub = subject_combo(db)
        f.addRow("المادة", self.sub)
        if with_date:
            self.val = QDateEdit(QDate.currentDate().addDays(28))
            self.val.setCalendarPopup(True)
            self.val.setDisplayFormat("dd/MM/yyyy")
            f.addRow("تنتهي قبل", self.val)
        else:
            self.val = QDoubleSpinBox()
            self.val.setRange(0, 60)
            self.val.setSingleStep(1)
            self.val.setValue(6)
            self.val.setSuffix(" سا هذا الأسبوع")
            f.addRow("الساعات", self.val)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self._fill()

    def _fill(self, *_):
        self.ref.clear()
        k = self.scope.currentData()
        marks = ",".join("?" * len(self.fids)) or "NULL"
        if k == "section":
            rows = self.db.q(f"SELECT id, short || ' — ' || name n FROM sections WHERE formation_id IN ({marks}) "
                             "ORDER BY sort, id", self.fids)
        elif k == "level":
            rows = self.db.q("SELECT id, COALESCE(code, name) n FROM levels ORDER BY sort, id")
        else:
            rows = self.db.q("""SELECT sp.id, COALESCE(l.code,'') || ' — ' || sp.name n FROM specialties sp
                                LEFT JOIN levels l ON l.id=sp.level_id ORDER BY l.sort, sp.name""")
        for r in rows:
            self.ref.addItem(r["n"], r["id"])

    def value(self) -> dict:
        d = {"scope": self.scope.currentData(), "ref": self.ref.currentData(), "subject": self.sub.currentData()}
        if isinstance(self.val, QDateEdit):
            d["date"] = self.val.date().toPython().isoformat()
        else:
            d["hours"] = self.val.value()
        return d


class PrioritiesPanel(QWidget):
    def __init__(self, ctx, week_fn, groups_fn):
        super().__init__()
        self.ctx, self.db = ctx, ctx.db
        self.week_fn, self.groups_fn = week_fn, groups_fn
        self.cfg = PRI.load(self.db)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        v = QVBoxLayout(inner)
        self.enabled = QCheckBox("تطبيق أولويات الأسبوع عند تشغيل المحرك")
        self.enabled.setChecked(bool(self.cfg.get("enabled")))
        v.addWidget(self.enabled)
        g1 = QGroupBox("المواد المتأخرة أولاً")
        f1 = QFormLayout(g1)
        self.late = QCheckBox("المادة الأقل إنجازاً في قسمها تأخذ ساعات أكثر (ومجموع القسم ثابت)")
        self.late.setChecked(bool(self.cfg.get("late_first")))
        f1.addRow(self.late)
        self.strength = QSpinBox()
        self.strength.setRange(0, 100)
        self.strength.setSuffix(" %")
        self.strength.setValue(int(self.cfg.get("late_strength", 50)))
        f1.addRow("قوة الأولوية", self.strength)
        v.addWidget(g1)
        g2 = QGroupBox("مواد محددة بساعات محددة هذا الأسبوع")
        l2 = QVBoxLayout(g2)
        self.t_targets = _table(["النطاق", "المادة", "الساعات"])
        l2.addWidget(self.t_targets)
        r2 = QHBoxLayout()
        b = QPushButton(icon("mdi6.plus"), "إضافة")
        b.clicked.connect(lambda: self._add("targets"))
        r2.addWidget(b)
        b = QPushButton(icon("mdi6.delete-outline"), "حذف المحدد")
        b.clicked.connect(lambda: self._remove("targets", self.t_targets))
        r2.addWidget(b)
        r2.addStretch()
        l2.addLayout(r2)
        v.addWidget(g2)
        g3 = QGroupBox("إنهاء مادة قبل تاريخ")
        l3 = QVBoxLayout(g3)
        self.t_dead = _table(["النطاق", "المادة", "قبل"])
        l3.addWidget(self.t_dead)
        r3 = QHBoxLayout()
        b = QPushButton(icon("mdi6.plus"), "إضافة")
        b.clicked.connect(lambda: self._add("deadlines"))
        r3.addWidget(b)
        b = QPushButton(icon("mdi6.delete-outline"), "حذف المحدد")
        b.clicked.connect(lambda: self._remove("deadlines", self.t_dead))
        r3.addWidget(b)
        r3.addStretch()
        l3.addLayout(r3)
        v.addWidget(g3)
        g4 = QGroupBox("قواعد اليوم")
        f4 = QFormLayout(g4)
        ru = self.cfg["rules"]
        self.day_hours = QDoubleSpinBox()
        self.day_hours.setRange(0, 12)
        self.day_hours.setSuffix(" سا (0 = بلا حد)")
        self.day_hours.setValue(float(ru.get("day_hours") or 0))
        f4.addRow("ساعات الدراسة القصوى في اليوم", self.day_hours)
        self.max_day = QSpinBox()
        self.max_day.setRange(0, 6)
        self.max_day.setSuffix(" (0 = بلا حد)")
        self.max_day.setValue(int(ru.get("max_per_day") or 0))
        f4.addRow("حصص نفس المادة في اليوم، حتى", self.max_day)
        self.morning = QListWidget()
        self.morning.setMaximumHeight(120)
        f4.addRow("مواد في الصباح فقط", self.morning)
        mr = QHBoxLayout()
        self.m_sub = subject_combo(self.db)
        mr.addWidget(self.m_sub, 1)
        b = QPushButton(icon("mdi6.plus"), "")
        b.clicked.connect(self._add_morning)
        mr.addWidget(b)
        b = QPushButton(icon("mdi6.minus"), "")
        b.clicked.connect(lambda: self.morning.takeItem(self.morning.currentRow()))
        mr.addWidget(b)
        w = QWidget()
        w.setLayout(mr)
        f4.addRow("", w)
        self.m_end = QTimeEdit(QTime(int(ru.get("morning_end", 720)) // 60, int(ru.get("morning_end", 720)) % 60))
        self.m_end.setDisplayFormat("HH:mm")
        f4.addRow("الصباح ينتهي عند", self.m_end)
        v.addWidget(g4)
        bar = QHBoxLayout()
        b = QPushButton(icon("mdi6.content-save-outline"), "حفظ الأولويات")
        b.clicked.connect(self.save)
        bar.addWidget(b)
        b = QPushButton(icon("mdi6.table-eye"), "معاينة خطة الأسبوع")
        b.setObjectName("Primary")
        b.clicked.connect(self.preview)
        bar.addWidget(b)
        bar.addStretch()
        v.addLayout(bar)
        v.addStretch()
        sc.setWidget(inner)
        outer.addWidget(sc)
        self._fill()

    # ------------------------------------------------------------------
    def _ref_label(self, scope, ref) -> str:
        if scope == "section":
            n = self.db.scalar("SELECT short FROM sections WHERE id=?", (ref,))
        elif scope == "level":
            n = self.db.scalar("SELECT COALESCE(code, name) FROM levels WHERE id=?", (ref,))
        else:
            n = self.db.scalar("SELECT name FROM specialties WHERE id=?", (ref,))
        return f"{PRI.SCOPE_LABELS.get(scope, scope)}: {n or ref}"

    def _fill(self):
        sub = {r[0]: r[1] for r in self.db.q("SELECT id, name FROM subjects")}
        for key, t, last in (("targets", self.t_targets, lambda d: f"{float(d.get('hours') or 0):g} سا"),
                             ("deadlines", self.t_dead, lambda d: d.get("date", ""))):
            items = self.cfg.get(key) or []
            t.setRowCount(len(items))
            for i, d in enumerate(items):
                for j, txt in enumerate((self._ref_label(d.get("scope"), d.get("ref")), sub.get(d.get("subject"), "?"),
                                         last(d))):
                    t.setItem(i, j, QTableWidgetItem(txt))
        self.morning.clear()
        for sid in self.cfg["rules"].get("morning") or []:
            it = QListWidgetItem(sub.get(sid, str(sid)))
            it.setData(Qt.UserRole, sid)
            self.morning.addItem(it)

    def _add(self, key):
        d = ScopeRowDialog(self, self.db, self.ctx.formation_ids() or [self.ctx.formation_id], key == "deadlines")
        if d.exec() == QDialog.Accepted:
            val = d.value()
            if not val["ref"] or not val["subject"]:
                error(self, "اختر النطاق والمادة.")
                return
            self.cfg.setdefault(key, []).append(val)
            self._fill()

    def _remove(self, key, t):
        i = t.currentRow()
        if i >= 0:
            self.cfg[key].pop(i)
            self._fill()

    def _add_morning(self):
        sid = self.m_sub.currentData()
        if sid and sid not in (self.cfg["rules"].get("morning") or []):
            self.cfg["rules"].setdefault("morning", []).append(sid)
            self._fill()

    def values(self) -> dict:
        c = dict(self.cfg)
        c["enabled"] = self.enabled.isChecked()
        c["late_first"] = self.late.isChecked()
        c["late_strength"] = self.strength.value()
        t = self.m_end.time()
        c["rules"] = dict(c["rules"], day_hours=self.day_hours.value(), max_per_day=self.max_day.value(),
                          morning=[self.morning.item(i).data(Qt.UserRole) for i in range(self.morning.count())],
                          morning_end=t.hour() * 60 + t.minute())
        return c

    def save(self):
        PRI.save(self.db, self.values())
        self.cfg = PRI.load(self.db)
        info(self, "حُفظت أولويات الأسبوع.")

    def preview(self):
        cfg = self.values()
        fid = self.ctx.formation_id
        hours, rows = PRI.week_plan(self.db, fid, self.week_fn(), self.groups_fn(), cfg, create_missing=False)
        show_plan(self, rows, "خطة الأسبوع قبل التشغيل")


def show_plan(parent, rows, title, result=False):
    d = QDialog(parent)
    d.setWindowTitle(title)
    d.resize(860, 560)
    v = QVBoxLayout(d)
    changed = [r for r in rows if abs(r["hours"] - r["base"]) > 0.01 or (result and r.get("short"))]
    head = QLabel(f"{len(rows)} سطر · {len(changed)} تغيّر عن الحجم الساعي العادي" +
                  (f" · {sum(1 for r in rows if r.get('short'))} سطر لم يُوضع كاملاً" if result else ""))
    v.addWidget(head)
    only = QCheckBox("ما تغيّر فقط")
    only.setChecked(bool(changed))
    v.addWidget(only)
    cols = ["القسم", "المادة", "الأساس", "المطلوب", "السبب"] + (["الموضوع", "النقص", "سبب النقص"] if result else [])
    t = _table(cols)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

    def fill():
        lst = changed if only.isChecked() else rows
        t.setRowCount(len(lst))
        for i, r in enumerate(lst):
            vals = [r["section"], r["subject"], f"{r['base']:g}", f"{r['hours']:g}", r["reason"]]
            if result:
                vals += [f"{r['placed']:g}", f"{r['short']:g}" if r["short"] else "", r.get("why", "")]
            for j, x in enumerate(vals):
                t.setItem(i, j, QTableWidgetItem(str(x)))
        t.resizeColumnsToContents()
    only.toggled.connect(lambda _: fill())
    fill()
    v.addWidget(t, 1)
    bb = QDialogButtonBox(QDialogButtonBox.Close)
    bb.rejected.connect(d.reject)
    v.addWidget(bb)
    d.exec()
