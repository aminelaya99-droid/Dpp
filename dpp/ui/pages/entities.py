"""صفحات إدارة البيانات الأساسية (جدول + بحث + إضافة/تعديل/حذف)."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ...utils import ALLOWED_DURATIONS, DAY_NAMES, FULL_DAY, hm, make_abbrev, unique_abbrev
from ..context import AppContext
from ..widgets import FormDialog, confirm, error, icon, info, page_title


@dataclass
class EntitySpec:
    key: str
    title: str
    subtitle: str
    table: str
    query: str                                  # يُرجع id + الأعمدة
    columns: list[tuple[str, str]]              # (اسم العمود في النتيجة، العنوان)
    fields: Callable[[AppContext], list[tuple]]  # حقول النموذج
    required: tuple = ()
    formation_scoped: bool = False
    has_formation_col: bool = True
    defaults: Callable[[AppContext], dict] | None = None
    before_save: Callable[[AppContext, dict, int | None], dict] | None = None
    after_insert: Callable[[AppContext, int, dict], None] | None = None
    extra_actions: list[tuple[str, str, Callable]] = field(default_factory=list)  # (نص، أيقونة، دالة(page, id))
    color_col: str | None = None
    load: Callable[[dict], dict] | None = None
    open_action: Callable | None = None         # نقر مزدوج: دالة(page, id) بدل التعديل


class EntityPage(QWidget):
    def __init__(self, ctx: AppContext, spec: EntitySpec):
        super().__init__()
        self.ctx, self.spec = ctx, spec
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title(spec.title, spec.subtitle))
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث…")
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search, 1)
        for text, ic, fn in [("إضافة", "mdi6.plus", self.add), ("تعديل", "mdi6.pencil", self.edit),
                             ("حذف", "mdi6.delete-outline", self.delete)]:
            b = QPushButton(icon(ic), text)
            if text == "إضافة":
                b.setObjectName("Primary")
            b.clicked.connect(fn)
            bar.addWidget(b)
        for text, ic, fn in spec.extra_actions:
            b = QPushButton(icon(ic), text)
            b.clicked.connect(lambda _=False, f=fn: f(self, self.current_id()))
            bar.addWidget(b)
        lay.addLayout(bar)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.doubleClicked.connect(
            lambda *_: spec.open_action(self, self.current_id()) if spec.open_action and self.current_id()
            else self.edit())
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.setSortingEnabled(True)
        lay.addWidget(self.table, 1)
        self.count = QLabel()
        self.count.setObjectName("Muted")
        lay.addWidget(self.count)
        ctx.data_changed.connect(lambda w: self.refresh() if w in ("*", spec.table) else None)
        ctx.formation_changed.connect(lambda _: self.refresh())
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        params = (self.ctx.formation_id or -1,) if self.spec.formation_scoped else ()
        rows = self.ctx.q(self.spec.query, params) if self.spec.formation_scoped else self.ctx.db.q(self.spec.query, params)
        self.table.setSortingEnabled(False)
        self.table.clear()
        self.table.setColumnCount(len(self.spec.columns))
        self.table.setHorizontalHeaderLabels([c[1] for c in self.spec.columns])
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            for j, (col, _h) in enumerate(self.spec.columns):
                v = r[col]
                if isinstance(v, float) and v.is_integer():
                    v = int(v)
                it = QTableWidgetItem("" if v is None else str(v))
                if j == 0:
                    it.setData(Qt.UserRole, r["id"])
                if self.spec.color_col and col == self.spec.color_col and v:
                    it.setBackground(QColor(str(v)))
                    it.setForeground(QColor("white"))
                self.table.setItem(i, j, it)
        self.table.resizeColumnsToContents()
        for j in range(len(self.spec.columns)):
            if self.table.columnWidth(j) > 380:
                self.table.setColumnWidth(j, 380)
        self.table.setSortingEnabled(True)
        self.count.setText(f"{len(rows)} سجل")
        self._filter(self.search.text())

    def _filter(self, text):
        text = text.strip()
        for i in range(self.table.rowCount()):
            show = not text or any(text in (self.table.item(i, j).text() if self.table.item(i, j) else "")
                                   for j in range(self.table.columnCount()))
            self.table.setRowHidden(i, not show)

    def current_id(self) -> int | None:
        r = self.table.currentRow()
        if r < 0 or self.table.item(r, 0) is None:
            return None
        return self.table.item(r, 0).data(Qt.UserRole)

    def _menu(self, pos):
        m = QMenu(self)
        m.addAction(icon("mdi6.pencil"), "تعديل", self.edit)
        m.addAction(icon("mdi6.delete-outline"), "حذف", self.delete)
        for text, ic, fn in self.spec.extra_actions:
            m.addAction(icon(ic), text, lambda f=fn: f(self, self.current_id()))
        m.exec(self.table.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------
    def _save(self, values: dict, row_id: int | None):
        db = self.ctx.db
        if self.spec.before_save:
            try:
                values = self.spec.before_save(self.ctx, values, row_id)
            except ValueError as e:
                error(self, str(e))
                return False
        if self.spec.formation_scoped and self.spec.has_formation_col and "formation_id" not in values and row_id is None:
            values["formation_id"] = self.ctx.formation_id
        try:
            with db.tx():
                if row_id:
                    db.update(self.spec.table, row_id, **values)
                    db.log("تعديل", self.spec.table, row_id, values)
                else:
                    row_id = db.insert(self.spec.table, **values)
                    db.log("إضافة", self.spec.table, row_id, values)
                    if self.spec.after_insert:
                        self.spec.after_insert(self.ctx, row_id, values)
        except sqlite3.IntegrityError as e:
            msg = str(e)
            if "UNIQUE" in msg:
                msg = "قيمة مكررة (غالباً الاختصار). اختر قيمة أخرى."
            error(self, f"تعذر الحفظ: {msg}")
            return False
        self.ctx.changed(self.spec.table)
        self.ctx.status.emit("تم الحفظ بنجاح.")
        return True

    def add(self):
        if self.spec.formation_scoped and not self.ctx.formation_id:
            error(self, "أنشئ تكويناً أولاً من صفحة التكوينات.")
            return
        fields = list(self.spec.fields(self.ctx))
        defaults = dict(self.spec.defaults(self.ctx) if self.spec.defaults else {})
        req = tuple(self.spec.required)
        if self.spec.formation_scoped and self.spec.has_formation_col and self.ctx.all_formations:
            # في وضع «كل التكوينات» نسأل عن التكوين صراحة
            fields.insert(0, ("formation_id", "التكوين", "combo",
                              [(r["id"], r["name"]) for r in self.ctx.formations()]))
            defaults.setdefault("formation_id", self.ctx.formation_id)
            req = req + ("formation_id",)
        d = FormDialog(self, f"إضافة — {self.spec.title}", fields, defaults, req)
        while d.exec() == QDialog.Accepted:
            if self._save(d.values(), None):
                break

    def edit(self):
        rid = self.current_id()
        if rid is None:
            info(self, "اختر سجلاً أولاً.")
            return
        row = dict(self.ctx.db.one(f"SELECT * FROM {self.spec.table} WHERE id=?", (rid,)))
        if self.spec.load:
            row = self.spec.load(row)
        d = FormDialog(self, f"تعديل — {self.spec.title}", self.spec.fields(self.ctx), row, self.spec.required)
        while d.exec() == QDialog.Accepted:
            if self._save(d.values(), rid):
                break

    def delete(self):
        rid = self.current_id()
        if rid is None:
            info(self, "اختر سجلاً أولاً.")
            return
        if not confirm(self, "هل تريد حذف هذا السجل نهائياً؟ قد تُحذف معه البيانات المرتبطة به.", danger=True):
            return
        try:
            with self.ctx.db.tx():
                self.ctx.db.execute(f"DELETE FROM {self.spec.table} WHERE id=?", (rid,))
                self.ctx.db.log("حذف", self.spec.table, rid)
        except sqlite3.IntegrityError:
            error(self, "لا يمكن الحذف لوجود بيانات مرتبطة (حصص مثلاً).")
            return
        self.ctx.changed(self.spec.table)


# ===================================================================== المواصفات
def _opts(ctx, sql, params=(), empty: str | None = None):
    out = [(None, empty)] if empty is not None else []
    return out + [(r[0], r[1]) for r in ctx.q(sql, params)]


def _auto_short(table: str, scope_sql: str = "", scope_param=None):
    def hook(ctx, v, rid):
        if not v.get("short"):
            existing = {r[0] for r in ctx.db.q(f"SELECT short FROM {table} WHERE short IS NOT NULL AND id<>? {scope_sql}",
                                               (rid or -1,) + ((scope_param(ctx),) if scope_param else ()))}
            v["short"] = unique_abbrev(make_abbrev(v.get("name", "")), existing)
        return v
    return hook


def _duration_opts():
    return [(m, f"{m / 60:g} سا") for m in ALLOWED_DURATIONS] + [(FULL_DAY, "يوم كامل (مع الغداء)")]


def _teacher_profile(page, tid):
    if tid:
        from ..teacher_profile import open_profile
        open_profile(page.ctx, tid, page)


def _teacher_leave(page, tid):
    from ..teacher_profile import add_leave
    add_leave(page.ctx, page, tid)


def teacher_subjects_dialog(page: EntityPage, tid: int | None):
    if not tid:
        info(page, "اختر أستاذاً أولاً.")
        return
    db = page.ctx.db
    d = QDialog(page)
    d.setWindowTitle("المواد المؤهل لتدريسها")
    d.resize(420, 520)
    lay = QVBoxLayout(d)
    flt = QLineEdit()
    flt.setPlaceholderText("بحث في المواد…")
    lay.addWidget(flt)
    lst = QListWidget()
    have = {r[0] for r in db.q("SELECT subject_id FROM teacher_subjects WHERE teacher_id=?", (tid,))}
    for r in db.q("SELECT id, name, short FROM subjects ORDER BY name"):
        it = QListWidgetItem(f"{r['name']}  ({r['short'] or ''})")
        it.setData(Qt.UserRole, r["id"])
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if r["id"] in have else Qt.Unchecked)
        lst.addItem(it)
    flt.textChanged.connect(lambda t: [lst.item(i).setHidden(bool(t) and t not in lst.item(i).text())
                                       for i in range(lst.count())])
    lay.addWidget(lst)
    bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
    bb.accepted.connect(d.accept)
    bb.rejected.connect(d.reject)
    lay.addWidget(bb)
    if d.exec() == QDialog.Accepted:
        with db.tx():
            db.execute("DELETE FROM teacher_subjects WHERE teacher_id=?", (tid,))
            for i in range(lst.count()):
                if lst.item(i).checkState() == Qt.Checked:
                    db.execute("INSERT INTO teacher_subjects VALUES (?,?)", (tid, lst.item(i).data(Qt.UserRole)))
            db.log("تعديل أهلية الأستاذ", "teachers", tid)
        page.ctx.changed("teachers")


def archive_formation(page: EntityPage, fid: int | None):
    if not fid:
        return
    db = page.ctx.db
    cur = db.scalar("SELECT archived FROM formations WHERE id=?", (fid,))
    if confirm(page, "إلغاء أرشفة هذا التكوين؟" if cur else "أرشفة هذا التكوين؟ ستبقى جداوله وتقاريره متاحة للعرض."):
        with db.tx():
            db.execute("UPDATE formations SET archived=? WHERE id=?", (0 if cur else 1, fid))
            db.log("إلغاء الأرشفة" if cur else "أرشفة تكوين", "formations", fid)
        page.ctx.changed("formations")


def make_current(page: EntityPage, fid: int | None):
    if fid:
        page.ctx.set_formation(fid)
        page.ctx.status.emit("تم تعيين التكوين الحالي.")


def _section_after_insert(ctx, sid, v):
    ctx.db.insert("groups_", section_id=sid, name="الفوج الكامل", short="ALL", is_whole=1, size=v.get("size", 0))


def _unav_save(ctx, v, rid):
    kind, ref = str(v.pop("who")).split(":")
    if v.get("date"):
        from ...utils import to_date
        try:
            to_date(v["date"])
        except ValueError:
            raise ValueError("صيغة التاريخ يجب أن تكون YYYY-MM-DD")
    if v["end_min"] <= v["start_min"]:
        raise ValueError("وقت النهاية يجب أن يكون بعد البداية.")
    return v | {"kind": kind, "ref_id": int(ref), "date": v.get("date") or None}


SPECS: dict[str, EntitySpec] = {}


def _profiles(ctx):
    from ...db.migrations import PROFILE_LABELS
    names = [r[0] for r in ctx.db.q("SELECT DISTINCT profile FROM periods ORDER BY profile")]
    return [(n, PROFILE_LABELS.get(n, n)) for n in names]


def _subject_kind(ctx, v, rid):
    if "category" in v:
        v["kind"] = "nonteach" if v["category"] == "nonteach" else "teach"
    return v


def build_specs():
    SPECS.clear()
    SPECS["formations"] = EntitySpec(
        "formations", "التكوينات", "التكوينات ومددها وأيام الراحة الأسبوعية الخاصة بكل تكوين.", "formations",
        """SELECT id, name, short, start_date, end_date, rest_days,
                  CASE archived WHEN 1 THEN 'مؤرشف' ELSE 'نشط' END st,
                  (SELECT COUNT(*) FROM sections s WHERE s.formation_id=formations.id) nsec
           FROM formations ORDER BY archived, start_date DESC""",
        [("name", "التكوين"), ("short", "الاختصار"), ("start_date", "البداية"), ("end_date", "النهاية"),
         ("rest_days", "أيام الراحة"), ("nsec", "الأقسام"), ("st", "الحالة")],
        lambda ctx: [("name", "اسم التكوين", "text", None), ("short", "الاختصار", "text", "يُولد تلقائياً"),
                     ("start_date", "تاريخ البداية", "date", None), ("end_date", "تاريخ النهاية", "date", None),
                     ("rest_days", "أيام الراحة الأسبوعية", "days", None), ("notes", "ملاحظات", "multiline", None)],
        required=("name",), before_save=_auto_short("formations"),
        extra_actions=[("تعيين كتكوين حالي", "mdi6.check-circle-outline", make_current),
                       ("أرشفة / إلغاء", "mdi6.archive-outline", archive_formation)])
    SPECS["levels"] = EntitySpec(
        "levels", "الأطوار", "أطوار التكوين الحالي: الرمز، اللون، ملف الفترات وفترة الغداء.", "levels",
        """SELECT l.id, l.code, l.name, l.short, l.color, l.lunch_period, l.profile, l.sort,
                  (SELECT COUNT(*) FROM sections s WHERE s.level_id=l.id) nsec
           FROM levels l WHERE l.formation_id=? ORDER BY l.sort, l.name""",
        [("code", "الرمز"), ("name", "الطور"), ("short", "الاختصار"), ("color", "اللون"), ("profile", "ملف الفترات"),
         ("lunch_period", "حصة الغداء"), ("nsec", "الأقسام")],
        lambda ctx: [("code", "الرمز (BMP2، ESOC1، OF-R…)", "text", None), ("name", "اسم الطور", "text", None),
                     ("short", "الاختصار", "text", "يُولد تلقائياً"), ("color", "اللون", "color", None),
                     ("profile", "ملف الفترات", "combo", _profiles(ctx)),
                     ("lunch_period", "رقم حصة الغداء", "int", None), ("sort", "الترتيب", "int", None),
                     ("footer_note", "ملاحظة الطباعة", "multiline", None)],
        required=("name",), formation_scoped=True, before_save=_auto_short("levels"), color_col="color",
        defaults=lambda ctx: {"lunch_period": 3, "profile": "standard", "color": "#5B8DEF"})
    SPECS["specialties"] = EntitySpec(
        "specialties", "الاختصاصات", "اختصاصات كل طور مع المقرر والحجم الساعي والمدة.", "specialties",
        """SELECT sp.id, l.code lcode, sp.name, sp.short, sp.decree, sp.decree_date, sp.hours, sp.activities_hours, sp.weeks
           FROM specialties sp JOIN levels l ON l.id=sp.level_id WHERE l.formation_id=? ORDER BY l.sort, sp.name""",
        [("lcode", "الطور"), ("name", "الاختصاص"), ("short", "الاختصار"), ("decree", "المقرر"), ("decree_date", "تاريخه"),
         ("hours", "الحجم الساعي"), ("activities_hours", "النشاطات"), ("weeks", "الأسابيع")],
        lambda ctx: [("level_id", "الطور", "combo", _opts(ctx, "SELECT id, COALESCE(code,'')||' — '||name FROM levels WHERE formation_id=?",
                                                         (ctx.formation_id,))),
                     ("name", "اسم الاختصاص", "text", None), ("short", "الاختصار", "text", None),
                     ("decree", "رقم المقرر", "text", "مثل 2017/149"), ("decree_date", "تاريخ المقرر (كما يُكتب)", "text", None),
                     ("hours", "الحجم الساعي (سا)", "float", None), ("activities_hours", "ساعات النشاطات", "float", None),
                     ("weeks", "عدد الأسابيع", "int", None)],
        required=("name", "level_id"), formation_scoped=True, has_formation_col=False)
    SPECS["cohorts"] = EntitySpec(
        "cohorts", "الدورات / الدفعات", "لكل طور دورة أو أكثر ببداية ونهاية؛ يُحسب رقم الأسبوع من بداية الدورة.", "cohorts",
        """SELECT c.id, l.code lcode, c.name, c.start_date, c.end_date,
                  CASE c.week_mode WHEN 'first_full' THEN 'أول أسبوع كامل' ELSE 'من البداية' END wm
           FROM cohorts c JOIN levels l ON l.id=c.level_id WHERE l.formation_id=? ORDER BY l.sort, c.start_date""",
        [("lcode", "الطور"), ("name", "الدورة"), ("start_date", "البداية"), ("end_date", "النهاية"), ("wm", "عدّ الأسابيع")],
        lambda ctx: [("level_id", "الطور", "combo", _opts(ctx, "SELECT id, COALESCE(code,'')||' — '||name FROM levels WHERE formation_id=?",
                                                         (ctx.formation_id,))),
                     ("name", "اسم الدورة", "text", None), ("start_date", "البداية", "date", None),
                     ("end_date", "النهاية", "date", None),
                     ("week_mode", "عدّ الأسابيع", "combo", [("start", "من تاريخ البداية"), ("first_full", "من أول أسبوع كامل")]),
                     ("week_offset", "تصحيح رقم الأسبوع (±)", "int", None)],
        required=("name", "level_id"), formation_scoped=True, has_formation_col=False)
    SPECS["periods"] = EntitySpec(
        "periods", "الفترات (الحصص)", "أوقات الحصص لكل ملف فترات: عادي، القاعدي المشترك، القاعدي + الليلية. "
        "يُختار الملف لكل طور ويمكن تجاوزه للقسم.", "periods",
        """SELECT id, profile, idx, label, printf('%02d:%02d', start_min/60, start_min%60) st,
                  printf('%02d:%02d', end_min/60, end_min%60) en, CASE kind WHEN 'night' THEN 'ليلية' ELSE 'نهارية' END k
           FROM periods ORDER BY profile, idx""",
        [("profile", "الملف"), ("idx", "الرقم"), ("label", "الحصة"), ("st", "من"), ("en", "إلى"), ("k", "النوع")],
        lambda ctx: [("profile", "الملف", "text", "standard / basic / basic_night أو اسم جديد"),
                     ("idx", "رقم الحصة", "int", None), ("label", "الاسم", "text", None),
                     ("start_min", "البداية", "time", None), ("end_min", "النهاية", "time", None),
                     ("kind", "النوع", "combo", [("day", "نهارية"), ("night", "ليلية")])],
        required=("profile", "label"))
    SPECS["sections"] = EntitySpec(
        "sections", "الأقسام", "أقسام التكوين الحالي. يُنشأ «الفوج الكامل» تلقائياً لكل قسم.", "sections",
        """SELECT s.id, s.name, s.short, COALESCE(l.code, l.name) lname, sp.name spname, c.name cname, s.size,
                  COALESCE(s.lunch_period, '') lp, COALESCE(s.profile, '') pr,
                  (SELECT COUNT(*) FROM groups_ g WHERE g.section_id=s.id) ng
           FROM sections s LEFT JOIN levels l ON l.id=s.level_id LEFT JOIN specialties sp ON sp.id=s.specialty_id
           LEFT JOIN cohorts c ON c.id=s.cohort_id WHERE s.formation_id=? ORDER BY COALESCE(l.sort, 99), s.sort, s.short""",
        [("short", "الاختصار"), ("name", "القسم"), ("lname", "الطور"), ("spname", "الاختصاص"), ("cname", "الدورة"),
         ("size", "العدد"), ("lp", "الغداء (تجاوز)"), ("pr", "الفترات (تجاوز)"), ("ng", "الأفواج")],
        lambda ctx: [("name", "اسم القسم", "text", None), ("short", "الاختصار", "text", "يُولد تلقائياً"),
                     ("level_id", "الطور", "combo", _opts(ctx, "SELECT id, COALESCE(code,'')||' — '||name FROM levels WHERE formation_id=?",
                                                          (ctx.formation_id,), "—")),
                     ("specialty_id", "الاختصاص", "combo", _opts(ctx, """SELECT sp.id, COALESCE(l.code,'')||' — '||sp.name
                        FROM specialties sp JOIN levels l ON l.id=sp.level_id WHERE l.formation_id=?""", (ctx.formation_id,), "—")),
                     ("cohort_id", "الدورة", "combo", _opts(ctx, """SELECT c.id, COALESCE(l.code,'')||' — '||c.name
                        FROM cohorts c JOIN levels l ON l.id=c.level_id WHERE l.formation_id=?""", (ctx.formation_id,), "—")),
                     ("lunch_period", "حصة الغداء (فارغ = حسب الطور)", "int", None),
                     ("profile", "ملف الفترات (فارغ = حسب الطور)", "combo", [(None, "حسب الطور")] + _profiles(ctx)),
                     ("size", "عدد المتربصين", "int", None), ("sort", "الترتيب في الجدول العام", "int", None)],
        required=("name",), formation_scoped=True,
        before_save=_auto_short("sections", "AND formation_id=?", lambda c: c.formation_id),
        after_insert=_section_after_insert)
    SPECS["groups"] = EntitySpec(
        "groups", "الأفواج والمجموعات", "الفوج الكامل يتعارض مع مجموعاته الفرعية؛ المجموعات الفرعية لا تتعارض فيما بينها.",
        "groups_",
        """SELECT g.id, sec.short secs, g.name, g.short, CASE g.is_whole WHEN 1 THEN 'كامل' ELSE 'فرعي' END w, g.size
           FROM groups_ g JOIN sections sec ON sec.id=g.section_id WHERE sec.formation_id=? ORDER BY sec.short, g.is_whole DESC""",
        [("secs", "القسم"), ("name", "الفوج"), ("short", "الاختصار"), ("w", "النوع"), ("size", "العدد")],
        lambda ctx: [("section_id", "القسم", "combo", _opts(ctx, "SELECT id, short||' — '||name FROM sections WHERE formation_id=?",
                                                            (ctx.formation_id,))),
                     ("name", "اسم الفوج", "text", None), ("short", "الاختصار", "text", None),
                     ("is_whole", "فوج كامل", "bool", None), ("size", "العدد", "int", None)],
        required=("name", "section_id"), formation_scoped=True,
        before_save=lambda ctx, v, rid: {k: x for k, x in v.items()})
    SPECS["subjects"] = EntitySpec(
        "subjects", "المواد", "فعّل «قابلة للمشاركة» للمواد التي يمكن أن يدرّسها أستاذ واحد لعدة أفواج في حصة واحدة.",
        "subjects",
        """SELECT id, name, short, color, CASE shareable WHEN 1 THEN 'نعم' ELSE '' END sh,
                  CASE category WHEN 'military' THEN 'عسكرية' WHEN 'general' THEN 'عامة' WHEN 'specialty' THEN 'اختصاص'
                       WHEN 'pe' THEN 'تربية بدنية' WHEN 'drill' THEN 'نظام منظم' WHEN 'nonteach' THEN 'غير دراسية' ELSE '' END cat,
                  (SELECT COUNT(*) FROM teacher_subjects ts WHERE ts.subject_id=subjects.id) nt FROM subjects ORDER BY name""",
        [("name", "المادة"), ("short", "الاختصار (البطاقة)"), ("cat", "النوع"), ("color", "اللون"), ("sh", "مشتركة"),
         ("nt", "أساتذة مؤهلون")],
        lambda ctx: [("name", "اسم المادة", "text", None), ("short", "الاختصار", "text", "يُولد تلقائياً"),
                     ("category", "النوع", "combo", [("military", "عسكرية"), ("general", "عامة"), ("specialty", "اختصاص"),
                                                     ("pe", "تربية بدنية"), ("drill", "نظام منظم"),
                                                     ("nonteach", "غير دراسية (غداء، عطلة، خفارة…) — لا تُحتسب")]),
                     ("color", "اللون", "color", None), ("shareable", "قابلة للمشاركة (حصة مشتركة)", "bool", None)],
        required=("name",), before_save=lambda c, v, r: _subject_kind(c, _auto_short("subjects")(c, v, r), r),
        color_col="color")
    SPECS["rooms"] = EntitySpec(
        "rooms", "القاعات", "القاعات وسعتها ونوعها.", "rooms",
        "SELECT id, name, short, capacity, kind FROM rooms ORDER BY name",
        [("name", "القاعة"), ("short", "الاختصار"), ("capacity", "السعة"), ("kind", "النوع")],
        lambda ctx: [("name", "اسم القاعة", "text", None), ("short", "الاختصار", "text", None),
                     ("capacity", "السعة", "int", None), ("kind", "النوع", "text", "مخبر، قاعة درس…")],
        required=("name",))
    SPECS["teachers"] = EntitySpec(
        "teachers", "الأساتذة", "ملفات الأساتذة وتصنيفاتهم والمواد المؤهلين لها.", "teachers",
        """SELECT t.id, t.full_name, t.rank, c.name cat, t.specialty,
                  (SELECT GROUP_CONCAT(s.short, '، ') FROM teacher_subjects ts JOIN subjects s ON s.id=ts.subject_id
                   WHERE ts.teacher_id=t.id) subj,
                  CASE t.active WHEN 1 THEN 'نشط' ELSE 'غير نشط' END st
           FROM teachers t LEFT JOIN teacher_categories c ON c.id=t.category_id ORDER BY t.full_name""",
        [("full_name", "الاسم واللقب"), ("rank", "الرتبة"), ("cat", "التصنيف"), ("specialty", "التخصص"),
         ("subj", "المواد المؤهل لها"), ("st", "الحالة")],
        lambda ctx: [("full_name", "الاسم واللقب", "text", None), ("rank", "الرتبة", "text", None),
                     ("category_id", "التصنيف", "combo", _opts(ctx, "SELECT id, name FROM teacher_categories ORDER BY name",
                                                               (), "—")),
                     ("specialty", "التخصص", "text", None), ("max_week_hours", "أقصى ساعات أسبوعية (0 = بلا حد)", "float", None),
                     ("active", "نشط", "bool", None), ("notes", "ملاحظات", "multiline", None)],
        required=("full_name",), defaults=lambda ctx: {"active": 1},
        extra_actions=[("ملف الأستاذ", "mdi6.card-account-details-outline", _teacher_profile),
                       ("إجازة وتعويض", "mdi6.calendar-remove-outline", _teacher_leave),
                       ("المواد المؤهل لها", "mdi6.book-check-outline", teacher_subjects_dialog)],
        open_action=_teacher_profile)
    SPECS["categories"] = EntitySpec(
        "categories", "تصنيفات الأساتذة", "أسماء التصنيفات قابلة للتعديل حسب المؤسسة.", "teacher_categories",
        "SELECT id, name, CASE military WHEN 1 THEN 'عسكري' ELSE 'مدني' END m FROM teacher_categories ORDER BY name",
        [("name", "التصنيف"), ("m", "الصفة")],
        lambda ctx: [("name", "اسم التصنيف", "text", None), ("military", "عسكري", "bool", None)], required=("name",))
    SPECS["requirements"] = EntitySpec(
        "requirements", "المتطلبات (الحجم الساعي)",
        "ما يجب تدريسه لكل فوج. اترك الأستاذ فارغاً ليختاره المحرك من المؤهلين. "
        "رمز المشاركة نفسه + مادة قابلة للمشاركة + نفس الأستاذ = حصة مشتركة واحدة.", "requirements",
        """SELECT r.id, sec.short secs, g.name gname, s.name sname, COALESCE(t.full_name, '(تلقائي)') tname,
                  r.total_hours, r.weekly_hours,
                  CASE r.session_minutes WHEN 0 THEN 'يوم كامل' ELSE (r.session_minutes/60.0)||' سا' END dur,
                  rm.name room, r.share_code
           FROM requirements r JOIN groups_ g ON g.id=r.group_id JOIN sections sec ON sec.id=g.section_id
           JOIN subjects s ON s.id=r.subject_id LEFT JOIN teachers t ON t.id=r.teacher_id
           LEFT JOIN rooms rm ON rm.id=r.room_id WHERE r.formation_id=? ORDER BY sec.short, g.is_whole DESC, s.name""",
        [("secs", "القسم"), ("gname", "الفوج"), ("sname", "المادة"), ("tname", "الأستاذ"), ("total_hours", "الحجم الكلي"),
         ("weekly_hours", "أسبوعياً"), ("dur", "مدة الحصة"), ("room", "القاعة"), ("share_code", "رمز المشاركة")],
        lambda ctx: [
            ("group_id", "الفوج", "combo", _opts(ctx, """SELECT g.id, sec.short||' / '||g.name FROM groups_ g
                                                         JOIN sections sec ON sec.id=g.section_id WHERE sec.formation_id=?
                                                         ORDER BY sec.short, g.is_whole DESC""", (ctx.formation_id,))),
            ("subject_id", "المادة", "combo", _opts(ctx, "SELECT id, name FROM subjects ORDER BY name")),
            ("teacher_id", "الأستاذ", "combo", _opts(ctx, "SELECT id, full_name FROM teachers WHERE active=1 ORDER BY full_name",
                                                     (), "(تلقائي من المؤهلين)")),
            ("room_id", "قاعة محددة", "combo", _opts(ctx, "SELECT id, name FROM rooms ORDER BY name", (), "—")),
            ("total_hours", "الحجم الساعي الكلي", "float", None), ("weekly_hours", "الحجم الأسبوعي", "float", None),
            ("session_minutes", "مدة الحصة", "combo", _duration_opts()),
            ("needs_room", "تتطلب قاعة", "bool", None), ("share_code", "رمز المشاركة", "text", "مثال: EPS-A"),
            ("priority", "الأولوية", "int", (0, 10))],
        required=("group_id", "subject_id"), formation_scoped=True,
        defaults=lambda ctx: {"session_minutes": 120, "weekly_hours": 2},
        before_save=lambda ctx, v, rid: v | {"share_code": v.get("share_code") or None})
    SPECS["unavailability"] = EntitySpec(
        "unavailability", "أوقات عدم التوفر", "أوقات لا يتوفر فيها أستاذ أو قاعة أو فوج (أسبوعياً أو بتاريخ محدد). "
        "«إلزامي» يمنع البرمجة، وغيره تفضيل فقط.", "unavailability",
        """SELECT u.id, CASE u.kind WHEN 'teacher' THEN 'أستاذ' WHEN 'room' THEN 'قاعة' ELSE 'فوج' END k,
                  CASE u.kind WHEN 'teacher' THEN (SELECT full_name FROM teachers WHERE id=u.ref_id)
                              WHEN 'room' THEN (SELECT name FROM rooms WHERE id=u.ref_id)
                              ELSE (SELECT sec.short||'/'||g.name FROM groups_ g JOIN sections sec ON sec.id=g.section_id WHERE g.id=u.ref_id) END who,
                  COALESCE(u.date, '') d, u.weekday, printf('%02d:%02d', u.start_min/60, u.start_min%60) s,
                  printf('%02d:%02d', u.end_min/60, u.end_min%60) e, CASE u.hard WHEN 1 THEN 'إلزامي' ELSE 'تفضيل' END h
           FROM unavailability u ORDER BY u.kind""",
        [("k", "النوع"), ("who", "المعني"), ("weekday", "اليوم (0=الأحد)"), ("d", "تاريخ محدد"), ("s", "من"), ("e", "إلى"),
         ("h", "الطبيعة")],
        lambda ctx: [
            ("who", "المعني", "combo",
             [(f"teacher:{r[0]}", "أستاذ: " + r[1]) for r in ctx.db.q("SELECT id, full_name FROM teachers ORDER BY full_name")]
             + [(f"room:{r[0]}", "قاعة: " + r[1]) for r in ctx.db.q("SELECT id, name FROM rooms")]
             + [(f"group:{r[0]}", "فوج: " + r[1]) for r in ctx.db.q("""SELECT g.id, sec.short||'/'||g.name FROM groups_ g
                                                                   JOIN sections sec ON sec.id=g.section_id""")]),
            ("weekday", "اليوم", "combo", [(None, "—")] + list(enumerate(DAY_NAMES))),
            ("date", "تاريخ محدد (اتركه للتكرار الأسبوعي)", "text", "YYYY-MM-DD"),
            ("start_min", "من", "time", None), ("end_min", "إلى", "time", None), ("hard", "إلزامي", "bool", None)],
        required=("who",), defaults=lambda ctx: {"start_min": 480, "end_min": 720, "hard": 1},
        load=lambda row: row | {"who": f"{row['kind']}:{row['ref_id']}"},
        before_save=_unav_save)
    return SPECS
