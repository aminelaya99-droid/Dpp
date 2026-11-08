"""النافذة الرئيسية: شريط Ribbon، لوحة جانبية، مساحة عمل، شريط حالة، اختصارات، بحث سريع."""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import QSize, QStringListModel, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QCompleter, QDialog, QDialogButtonBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QSplitter,
                               QStackedWidget, QStatusBar, QTabBar, QToolButton, QVBoxLayout, QWidget)

from .. import __version__
from ..services import backup as B
from ..services import calendar as C
from . import theme
from .context import AppContext
from .shell import (ALL_STYLES, DEFAULT_STYLE, NAV_GROUPS, STYLES, UPGRADE, CommandPalette, ContentHeader,
                    FocusBar, ModernSidebar, TopNav, normalize_style)
from .pages.absences import AbsencesPage
from .pages.calendar_page import CalendarPage
from .pages.dashboard import DashboardPage
from .pages.entities import SPECS, EntityPage, build_specs
from .pages.generate import GenerateDialog
from .pages.import_page import ImportPage
from .pages.master import MasterPage
from .pages.planner import PlannerPage
from .pages.progress import ProgressPage
from .pages.reports import ReportsPage
from .pages.settings_page import SettingsPage
from .widgets import confirm, error, icon, info

PAGES = [
    ("master", "الجدول العام", "mdi6.table-large"),
    ("dashboard", "لوحة التحكم", "mdi6.view-dashboard-outline"),
    ("planner", "المخطط الأسبوعي", "mdi6.calendar-week"),
    ("weeks", "الأسابيع", "mdi6.calendar-multiple-check"),
    ("formations", "التكوينات", "mdi6.school-outline"),
    ("structure", "مخطط التكوين", "mdi6.file-tree-outline"),
    ("levels", "الأطوار", "mdi6.layers-outline"),
    ("specialties", "الاختصاصات", "mdi6.certificate-outline"),
    ("cohorts", "الدورات", "mdi6.calendar-range"),
    ("periods", "الفترات", "mdi6.clock-outline"),
    ("sections", "الأقسام", "mdi6.google-classroom"),
    ("groups", "الأفواج", "mdi6.account-group-outline"),
    ("subjects", "المواد", "mdi6.book-open-page-variant-outline"),
    ("rooms", "القاعات", "mdi6.door"),
    ("requirements", "المتطلبات", "mdi6.clipboard-list-outline"),
    ("teachers", "الأساتذة", "mdi6.human-male-board"),
    ("categories", "التصنيفات", "mdi6.tag-multiple-outline"),
    ("unavailability", "عدم التوفر", "mdi6.calendar-remove-outline"),
    ("absences", "الغياب والاستخلاف", "mdi6.account-off-outline"),
    ("calendar", "الرزنامة", "mdi6.calendar-month-outline"),
    ("duty", "الخفارة والخدمات", "mdi6.shield-account-outline"),
    ("progress", "المقرر والتقدم", "mdi6.chart-donut"),
    ("curriculum", "المقرر", "mdi6.book-clock-outline"),
    ("reports", "التقارير والطباعة", "mdi6.printer-outline"),
    ("import", "الاستيراد", "mdi6.database-import-outline"),
    ("settings", "الإعدادات", "mdi6.cog-outline"),
]


class Ribbon(QWidget):
    """شريط أوامر بتبويبات ومجموعات، مستوحى من فكرة Ribbon."""

    def __init__(self, parent):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.top = QFrame()
        self.top.setObjectName("RibbonTop")
        self.top_l = QHBoxLayout(self.top)
        self.top_l.setContentsMargins(8, 4, 8, 0)
        lay.addWidget(self.top)
        self.tabs = QTabBar()
        self.tabs.setObjectName("RibbonTabs")
        self.tabs.setExpanding(False)
        self.tabs.setDrawBase(False)
        tabrow = QFrame()
        tabrow.setObjectName("RibbonTop")
        tl = QHBoxLayout(tabrow)
        tl.setContentsMargins(8, 0, 8, 0)
        tl.addWidget(self.tabs)
        tl.addStretch()
        lay.addWidget(tabrow)
        self.stack = QStackedWidget()
        self.stack.setObjectName("RibbonPanel")
        self.stack.setFixedHeight(92)
        lay.addWidget(self.stack)
        self.tabs.currentChanged.connect(self.stack.setCurrentIndex)

    def add_tab(self, title: str, groups: list[tuple[str, list[tuple]]]):
        panel = QFrame()
        panel.setObjectName("RibbonPanel")
        h = QHBoxLayout(panel)
        h.setContentsMargins(6, 4, 6, 2)
        h.setSpacing(0)
        for gtitle, actions in groups:
            g = QFrame()
            g.setObjectName("RibbonGroup")
            gv = QVBoxLayout(g)
            gv.setContentsMargins(6, 0, 6, 0)
            gv.setSpacing(0)
            row = QHBoxLayout()
            row.setSpacing(2)
            for text, ic, fn, tip in actions:
                b = QToolButton()
                b.setText(text)
                b.setIcon(icon(ic, theme.CURRENT["accent"]))
                b.setIconSize(QSize(24, 24))
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setMinimumWidth(64)
                b.setToolTip(tip or text)
                b.clicked.connect(fn)
                row.addWidget(b)
            gv.addLayout(row)
            lab = QLabel(gtitle)
            lab.setObjectName("GroupTitle")
            lab.setAlignment(Qt.AlignCenter)
            gv.addWidget(lab)
            h.addWidget(g)
        h.addStretch()
        self.stack.addWidget(panel)
        self.tabs.addTab(title)


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, app: QApplication):
        super().__init__()
        self.ctx, self.app = ctx, app
        self.setWindowTitle("DPP — تسيير التكوين والتربصات")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(1360, 860)
        build_specs()
        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        self.ribbon = Ribbon(self)
        cl.addWidget(self.ribbon)
        self.focus_bar = FocusBar(self)
        self.focus_bar.palette_btn.clicked.connect(self.command_palette)
        cl.addWidget(self.focus_bar)
        self.top_nav = TopNav(PAGES, self)
        self.top_nav.navigate.connect(self.navigate)
        cl.addWidget(self.top_nav)
        # القائمة الجانبية خارج أي QSplitter: الفاصل كان يحتفظ بعرضها القديم (240) بعد الطيّ فيبقى شريط فارغ.
        # تخطيط أفقي عادي يعطيها عرضها الثابت فقط، والصفحة تأخذ الباقي.
        self.split = QWidget()
        _sl = QHBoxLayout(self.split)
        _sl.setContentsMargins(0, 0, 0, 0)
        _sl.setSpacing(0)
        self.modern_side = ModernSidebar(PAGES, self)
        self.modern_side.navigate.connect(self.navigate)
        self.modern_side.collapsed_changed.connect(lambda on: ctx.db.set_setting("side_collapsed", int(on)))
        _sl.addWidget(self.modern_side)
        self.side = QListWidget()
        self.side.setObjectName("SidePanel")
        self.side.setMaximumWidth(230)
        self.side.setIconSize(QSize(18, 18))
        for key, title, ic in PAGES:
            it = QListWidgetItem(icon(ic), title)
            it.setData(Qt.UserRole, key)
            self.side.addItem(it)
        self.side.currentItemChanged.connect(lambda it, _p: it and self.show_page(it.data(Qt.UserRole)))
        self.stack = QStackedWidget()
        _sl.addWidget(self.side)
        content = QWidget()
        content.setObjectName("PageContent")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)
        self.header = ContentHeader(self)
        self.header.bell.setMenu(self._notif_menu())
        self.header.user_btn.setMenu(self._user_menu())
        cv.addWidget(self.header)
        # الصفحات داخل منطقة تمرير: صفحة عريضة لا تدفع النافذة أوسع من الشاشة (فتختفي القائمة الجانبية)
        from PySide6.QtWidgets import QScrollArea
        self.page_scroll = QScrollArea()
        self.page_scroll.setObjectName("PageScroll")
        self.page_scroll.setWidgetResizable(True)
        self.page_scroll.setFrameShape(QFrame.NoFrame)
        self.page_scroll.setWidget(self.stack)
        cv.addWidget(self.page_scroll, 1)
        _sl.addWidget(content, 1)
        cl.addWidget(self.split, 1)
        self.setCentralWidget(central)
        self.pages: dict[str, QWidget] = {}
        self._build_top()
        self._build_ribbon()
        self._build_status()
        self._shortcuts()
        ctx.navigate.connect(self.navigate)
        ctx.status.connect(lambda m: self.statusBar().showMessage(m, 6000))
        ctx.formation_changed.connect(lambda _: self._update_status())
        ctx.data_changed.connect(lambda w: self._fill_formations() if w in ("*", "formations") else None)
        # ترحيل إعدادات المظهر القديمة: لكل نمط لوحة ألوانه افتراضياً
        if ctx.db.get_setting("theme_v2", "") != "1":
            ctx.db.set_setting("theme", "style")
            ctx.db.set_setting("theme_v2", "1")
        self.modern_side.set_collapsed(ctx.db.get_setting("side_collapsed", "0") == "1", emit=False)
        # الإصدار 1.4: النمط القديم ← أقرب واجهة من الواجهات الثلاث (مرة واحدة)
        if ctx.db.get_setting("ui_style_v14", "") != "1":
            old = normalize_style(ctx.db.get_setting("ui_style", "teal"))
            ctx.db.set_setting("ui_style", UPGRADE.get(old, old))
            ctx.db.set_setting("ui_style_v14", "1")
        # الإصدار 1.7: «DPP الحديثة» تصبح الواجهة الافتراضية مرة واحدة (الواجهات أ/ب/ج تبقى متاحة)
        if ctx.db.get_setting("ui_style_v17", "") != "1":
            ctx.db.set_setting("ui_style", DEFAULT_STYLE)
            ctx.db.set_setting("ui_style_v17", "1")
        self.apply_style(ctx.db.get_setting("ui_style", DEFAULT_STYLE), save=False)
        self.side.setCurrentRow(0)
        self.badge_timer = QTimer(self)
        self.badge_timer.timeout.connect(self.update_badges)
        self.badge_timer.start(60 * 1000)
        ctx.data_changed.connect(lambda _w: QTimer.singleShot(300, self.update_badges))
        QTimer.singleShot(500, self.update_badges)
        QTimer.singleShot(800, self._startup_notices)
        QTimer.singleShot(1500, self._restore_word_templates)
        QTimer.singleShot(1500, self._bootstrap_curriculum)
        self.reminder_timer = QTimer(self)
        self.reminder_timer.timeout.connect(self._startup_notices)
        self.reminder_timer.start(6 * 3600 * 1000)
        self._reminded: set = set()
        self.minute_timer = QTimer(self)                 # تذكير صوتي قبل الحصص
        self.minute_timer.timeout.connect(self._time_reminders)
        self.minute_timer.start(60 * 1000)

    # ------------------------------------------------------------------ واجهة
    def _build_top(self):
        t = self.ribbon.top_l
        title = QLabel("DPP")
        title.setObjectName("AppTitle")
        t.addWidget(title)
        lab = QLabel("التكوين:")
        lab.setStyleSheet("color: white;")
        t.addWidget(lab)
        self.formation_cb = QComboBox()
        self.formation_cb.setMinimumWidth(240)
        self.formation_cb.currentIndexChanged.connect(
            lambda _: self.formation_cb.currentData() is not None and self.ctx.set_formation(self.formation_cb.currentData()))
        t.addWidget(self.formation_cb)
        t.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث سريع: قسم، أستاذ، مادة، صفحة…  (Ctrl+F)")
        self._search_model = QStringListModel()
        comp = QCompleter(self._search_model, self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.activated.connect(self._search_go)
        self.search.setCompleter(comp)
        self.search.returnPressed.connect(lambda: self._search_go(self.search.text()))
        t.addWidget(self.search)
        thm = QToolButton()
        thm.setIcon(icon("mdi6.theme-light-dark", "white"))
        thm.setToolTip("تبديل الوضع الفاتح/الداكن (Ctrl+Shift+D)")
        thm.clicked.connect(self.toggle_theme)
        t.addWidget(thm)
        self.style_btn = QToolButton()
        self.style_btn.setIcon(icon("mdi6.palette-swatch-outline", "white"))
        self.style_btn.setToolTip("نمط الواجهة (Ctrl+Shift+L)")
        self.style_btn.setPopupMode(QToolButton.InstantPopup)
        from PySide6.QtWidgets import QMenu
        sm = QMenu(self.style_btn)
        for k, lab in STYLES:
            sm.addAction(lab, lambda k=k: self.apply_style(k))
        self.style_btn.setMenu(sm)
        t.addWidget(self.style_btn)
        self.thm_btn = thm
        side = QToolButton()
        side.setIcon(icon("mdi6.page-layout-sidebar-right", "white"))
        side.setToolTip("إظهار/إخفاء اللوحة الجانبية (Ctrl+B)")
        side.clicked.connect(self.toggle_side)
        t.addWidget(side)
        self.side_btn = side
        self._fill_formations()

    def _fill_formations(self):
        self.formation_cb.blockSignals(True)
        self.formation_cb.clear()
        from .context import ALL
        self.formation_cb.addItem(icon("mdi6.select-all"), "كل التكوينات", ALL)
        for r in self.ctx.formations(include_archived=True):
            self.formation_cb.addItem(r["name"] + ("  (مؤرشف)" if r["archived"] else ""), r["id"])
        i = self.formation_cb.findData(self.ctx.selection)
        if i >= 0:
            self.formation_cb.setCurrentIndex(i)
        self.formation_cb.blockSignals(False)
        self._refresh_search()

    def _refresh_search(self):
        db = self.ctx.db
        items = [f"صفحة: {t}" for _, t, _ in PAGES]
        items += [f"قسم: {r[0]} — {r[1]}" for r in self.ctx.q("SELECT short, name FROM sections WHERE formation_id=?",
                                                               (self.ctx.formation_id or -1,))]
        items += [f"أستاذ: {r[0]}" for r in db.q("SELECT full_name FROM teachers")]
        items += [f"مادة: {r[0]}" for r in db.q("SELECT name FROM subjects")]
        items += [f"تكوين: {r[0]}" for r in db.q("SELECT name FROM formations")]
        items += [f"فوج: {r[0]} / {r[1]}" for r in self.ctx.q("""SELECT sec.short, g.name FROM groups_ g JOIN sections sec
                                                           ON sec.id=g.section_id WHERE sec.formation_id=?""",
                                                        (self.ctx.formation_id or -1,))]
        self._search_model.setStringList(items)

    def _search_go(self, text):
        text = (text or "").strip()
        if not text:
            return
        db = self.ctx.db
        kind, _, val = text.partition(": ")
        if not val:
            kind, val = "", text
        if kind == "صفحة":
            for k, t, _ in PAGES:
                if t == val:
                    self.navigate(k)
                    return
        if kind == "قسم":
            short = val.split(" — ")[0]
            r = db.one(self.ctx.scope("SELECT id FROM sections WHERE short=? AND formation_id=?"), (short, self.ctx.formation_id))
            if r:
                self.navigate("planner", ("section", r["id"]))
                return
        if kind == "أستاذ":
            r = db.one("SELECT id FROM teachers WHERE full_name=?", (val,))
            if r:
                self.navigate("planner", ("teacher", r["id"]))
                return
        if kind == "فوج":
            short, _, g = val.partition(" / ")
            r = db.one("""SELECT g.id FROM groups_ g JOIN sections s ON s.id=g.section_id
                          WHERE s.short=? AND g.name=? AND s.formation_id=?""".replace("s.formation_id=?", self.ctx.scope("s.formation_id=?")), (short, g, self.ctx.formation_id))
            if r:
                self.navigate("planner", ("group", r["id"]))
                return
        if kind == "مادة":
            self.navigate("subjects")
            self.pages["subjects"].search.setText(val)
            return
        if kind == "تكوين":
            r = db.one("SELECT id FROM formations WHERE name=?", (val,))
            if r:
                self.ctx.set_formation(r["id"])
                self._fill_formations()
                return
        # بحث حر
        r = db.one("SELECT id FROM teachers WHERE full_name LIKE ?", (f"%{val}%",))
        if r:
            self.navigate("planner", ("teacher", r["id"]))
            return
        r = db.one(self.ctx.scope("SELECT id FROM sections WHERE (name LIKE ? OR short LIKE ?) AND formation_id=?"),
                   (f"%{val}%", f"%{val}%", self.ctx.formation_id))
        if r:
            self.navigate("planner", ("section", r["id"]))
            return
        self.statusBar().showMessage("لا توجد نتيجة مطابقة.", 4000)

    def _build_ribbon(self):
        P = lambda k: (lambda: self.navigate(k))  # noqa: E731
        pl = lambda name: (lambda: self._planner_call(name))  # noqa: E731
        self.ribbon.add_tab("الرئيسية", [
            ("عرض", [("الجدول العام", "mdi6.table-large", P("master"), "Ctrl+1"),
                     ("لوحة التحكم", "mdi6.view-dashboard-outline", P("dashboard"), None),
                     ("المخطط الأسبوعي", "mdi6.calendar-week", P("planner"), "Ctrl+2")]),
            ("الجدولة", [("إنشاء جدول", "mdi6.auto-fix", self.open_generate, "إنشاء الجداول آلياً (Ctrl+G)"),
                         ("اعتماد", "mdi6.check-decagram-outline", pl("approve"), "اعتماد جدول الأسبوع المعروض")]),
            ("البيانات", [("نسخة احتياطية الآن", "mdi6.content-save-move-outline", self.backup_now, "Ctrl+Shift+S"),
                          ("استيراد", "mdi6.database-import-outline", P("import"), None)]),
        ])
        self.ribbon.add_tab("التكوينات", [
            ("التكوين", [("التكوينات", "mdi6.school-outline", P("formations"), None),
                         ("الأطوار", "mdi6.layers-outline", P("levels"), None),
                         ("الاختصاصات", "mdi6.certificate-outline", P("specialties"), None),
                         ("الدورات", "mdi6.calendar-range", P("cohorts"), None),
                         ("الفترات", "mdi6.clock-outline", P("periods"), None),
                         ("الأقسام", "mdi6.google-classroom", P("sections"), None),
                         ("الأفواج", "mdi6.account-group-outline", P("groups"), None)]),
            ("المحتوى", [("المواد", "mdi6.book-open-page-variant-outline", P("subjects"), None),
                         ("المتطلبات", "mdi6.clipboard-list-outline", P("requirements"), "الحجم الساعي لكل فوج ومادة"),
                         ("القاعات", "mdi6.door", P("rooms"), None)]),
            ("الاستيراد", [("ملف .roz / Excel", "mdi6.database-import-outline", P("import"), None)]),
        ])
        self.ribbon.add_tab("الجداول", [
            ("إنشاء", [("إنشاء آلي", "mdi6.auto-fix", self.open_generate, "Ctrl+G"),
                       ("المخطط", "mdi6.calendar-week", P("planner"), None)]),
            ("الأسبوع", [("السابق", "mdi6.chevron-right", pl("prev"), "Ctrl+PgUp"),
                         ("التالي", "mdi6.chevron-left", pl("next"), "Ctrl+PgDown"),
                         ("نسخ أسبوع", "mdi6.content-copy", pl("copy_week"), None),
                         ("مقارنة", "mdi6.compare-horizontal", pl("compare"), None)]),
            ("الحالة", [("اعتماد", "mdi6.check-decagram-outline", pl("approve"), None),
                        ("إعادة فتح", "mdi6.lock-open-variant-outline", pl("reopen"), None),
                        ("النسخ السابقة", "mdi6.history", pl("versions"), None)]),
            ("العرض", [("تكبير", "mdi6.magnify-plus-outline", pl("zoom_in"), "Ctrl++"),
                       ("تصغير", "mdi6.magnify-minus-outline", pl("zoom_out"), "Ctrl+-"),
                       ("الحجم الافتراضي", "mdi6.restore", pl("reset_sizes"), "Ctrl+0")]),
        ])
        self.ribbon.add_tab("الأساتذة", [
            ("الأساتذة", [("الأساتذة", "mdi6.human-male-board", P("teachers"), None),
                          ("التصنيفات", "mdi6.tag-multiple-outline", P("categories"), None)]),
            ("التوفر", [("الغياب والاستخلاف", "mdi6.account-off-outline", P("absences"), None),
                        ("عدم التوفر", "mdi6.calendar-remove-outline", P("unavailability"), None)]),
        ])
        self.ribbon.add_tab("الرزنامة", [
            ("الرزنامة", [("الرزنامة", "mdi6.calendar-month-outline", P("calendar"), None),
                          ("إضافة حدث", "mdi6.calendar-plus", lambda: (self.navigate("calendar"),
                                                                       self.pages["calendar"].add()), None)]),
        ])
        self.ribbon.add_tab("التقارير", [
            ("المتابعة", [("تقدم المواد", "mdi6.chart-donut", P("progress"), None),
                          ("المقرر", "mdi6.book-clock-outline", P("curriculum"), None),
                          ("مركز التقارير", "mdi6.file-chart-outline", P("reports"), None)]),
        ])
        self.ribbon.add_tab("الطباعة", [
            ("البرنامج الرسمي", [("طباعة ومعاينة", "mdi6.printer-eye", self.print_program, "Ctrl+P")]),
            ("الأسبوع المعروض", [("PDF", "mdi6.file-pdf-box", lambda: self.quick_export("pdf"), None),
                                 ("Word", "mdi6.file-word-outline", lambda: self.quick_export("docx"), None),
                                 ("Excel", "mdi6.file-excel-outline", lambda: self.quick_export("xlsx"), None)]),
            ("القوالب", [("التقارير والقوالب", "mdi6.palette-outline", P("reports"), None)]),
        ])
        self.ribbon.add_tab("الإعدادات", [
            ("الإعدادات", [("الإعدادات", "mdi6.cog-outline", P("settings"), None),
                           ("النسخ الاحتياطي", "mdi6.backup-restore", lambda: self.navigate("backup"), None),
                           ("المظهر", "mdi6.theme-light-dark", self.toggle_theme, None)]),
            ("مساعدة", [("حول البرنامج", "mdi6.information-outline", self.about, None)]),
        ])

    def _build_status(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.st_user = QLabel()
        self.st_form = QLabel()
        self.st_date = QLabel(date.today().strftime("%d/%m/%Y"))
        for w in (self.st_user, self.st_form, self.st_date):
            sb.addPermanentWidget(w)
        self._update_status()

    def _update_status(self):
        self.st_user.setText(f"المستخدم: {self.ctx.db.current_user}")
        self.st_form.setText(f"التكوين: {self.ctx.formation_label()}")
        i = self.formation_cb.findData(self.ctx.selection)
        if i >= 0 and i != self.formation_cb.currentIndex():
            self.formation_cb.blockSignals(True)
            self.formation_cb.setCurrentIndex(i)
            self.formation_cb.blockSignals(False)
        self._refresh_search()

    def _shortcuts(self):
        def sc(seq, fn):
            QShortcut(QKeySequence(seq), self, activated=fn)
        sc("Ctrl+1", lambda: self.navigate("master"))
        sc("Ctrl+3", lambda: self.navigate("dashboard"))
        sc("Ctrl+2", lambda: self.navigate("planner"))
        sc("Ctrl+G", self.open_generate)
        sc("Ctrl+F", lambda: (self.search.setFocus(), self.search.selectAll()))
        sc("Ctrl+B", self.toggle_side)
        sc("Ctrl+K", self.command_palette)
        sc("Ctrl+Shift+L", self.cycle_style)
        sc("Ctrl+Shift+D", self.toggle_theme)
        sc("Ctrl+P", self.print_program)
        sc("Ctrl+Shift+S", self.backup_now)
        sc("Ctrl+PgUp", lambda: self._planner_call("prev"))
        sc("Ctrl+PgDown", lambda: self._planner_call("next"))
        sc("Ctrl++", lambda: self._zoom(1))
        sc("Ctrl+=", lambda: self._zoom(1))
        sc("Ctrl+-", lambda: self._zoom(-1))
        sc("Ctrl+0", lambda: self._planner_call("reset_sizes"))
        sc("F5", lambda: self.ctx.changed("*"))

    # ------------------------------------------------------------------ تنقل
    def _make_page(self, key):
        if key == "master":
            return MasterPage(self.ctx)
        if key == "dashboard":
            return DashboardPage(self.ctx)
        if key == "planner":
            return PlannerPage(self.ctx)
        if key == "absences":
            return AbsencesPage(self.ctx)
        if key == "calendar":
            return CalendarPage(self.ctx)
        if key == "progress":
            return ProgressPage(self.ctx)
        if key == "curriculum":
            from .pages.curriculum_page import CurriculumPage
            return CurriculumPage(self.ctx)
        if key == "structure":
            from .pages.structure_page import StructurePage
            return StructurePage(self.ctx)
        if key == "weeks":
            from .pages.weeks_page import WeeksPage
            return WeeksPage(self.ctx)
        if key == "duty":
            from .pages.duty_page import DutyPage
            return DutyPage(self.ctx)
        if key == "reports":
            return ReportsPage(self.ctx)
        if key == "import":
            return ImportPage(self.ctx)
        if key == "settings":
            p = SettingsPage(self.ctx)
            p.theme_changed.connect(lambda m: self.apply_theme(m))
            p.style_changed.connect(self.apply_style)
            p.database_replaced.connect(self.replace_db)
            return p
        return EntityPage(self.ctx, SPECS[key])

    def show_page(self, key):
        if key not in self.pages:
            self.pages[key] = self._make_page(key)
            self.stack.addWidget(self.pages[key])
        self.stack.setCurrentWidget(self.pages[key])
        titles = {k: t for k, t, _ in PAGES}
        self.header.title.setText(titles.get(key, ""))
        self.focus_bar.title.setText("· " + titles.get(key, ""))
        self.modern_side.set_current(key)
        self.top_nav.set_current(key)
        self._current = key
        self._set_crumbs(key)
        for i in range(self.side.count()):
            if self.side.item(i).data(Qt.UserRole) == key and self.side.currentRow() != i:
                self.side.blockSignals(True)
                self.side.setCurrentRow(i)
                self.side.blockSignals(False)
        return self.pages[key]

    def navigate(self, key, arg=None):
        if key == "generate":
            self.open_generate()
            return
        if key == "backup":
            p = self.show_page("settings")
            p.tabs.setCurrentIndex(1)
            return
        if key == "curriculum":            # المقرر صار تبويباً داخل «المقرر والتقدم»
            self.show_page("progress").show_curriculum()
            return
        page = self.show_page(key)
        if key == "planner" and arg:
            page.select(*arg)
        elif key == "master" and arg and arg[0] == "section":
            page.focus_section(arg[1])
        elif key == "master" and arg and arg[0] == "week_section":
            from ..utils import to_date
            page.set_week(to_date(arg[1]))
            page.focus_section(arg[2])

    def _zoom(self, step):
        master = self.pages.get("master")
        if master is not None and self.stack.currentWidget() is master:
            master.zoom(step)
        else:
            self._planner_call("zoom_in" if step > 0 else "zoom_out")

    def _planner_call(self, name):
        page = self.show_page("planner")
        if name == "prev":
            page.set_week(page.ws - timedelta(days=7))
        elif name == "next":
            page.set_week(page.ws + timedelta(days=7))
        else:
            getattr(page, name)()

    # ------------------------------------------------------------------ أوامر
    def open_generate(self):
        if not self.ctx.formation_id:
            error(self, "أنشئ تكويناً أولاً.")
            return
        week = self.pages["planner"].ws if "planner" in self.pages else None
        GenerateDialog(self.ctx, week, self).exec()
        self.ctx.changed("sessions")

    def print_program(self, kind=None, target=None):
        """الطباعة بالقالب الرسمي: يأخذ الأسبوع والقسم/الأستاذ من الصفحة الحالية."""
        from .sheet_view import open_print
        cur = self.stack.currentWidget()
        master = self.pages.get("master")
        planner = self.pages.get("planner")
        ws, k, t = date.today(), kind or "section", target
        if master is not None and cur is master:
            ws = master.grid.ws
            if kind is None:
                k, t = master.print_target()
        elif planner is not None and cur is planner:
            ws = planner.ws
            mode, tid = planner.mode.currentData(), planner.target.currentData()
            if kind is None:
                k, t = {"teacher": ("teacher", tid), "section": ("section", tid)}.get(mode, ("all_sections", None))
        elif master is not None:
            ws = master.grid.ws
        open_print(self.ctx, ws, self, k, t)

    def quick_export(self, fmt):
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        from ..exporters import model as M
        from ..exporters.render import export
        from ..services import templates as TP
        page = self.show_page("planner")
        mode, tid = page.mode.currentData(), page.target.currentData()
        kind = {"teacher": "week_teacher", "section": "week_section"}.get(mode, "week_all")
        TP.ensure_defaults(self.ctx.db)
        tpl = TP.get_template(self.ctx.db, None, kind)
        kw = {"section": {"section_id": tid}, "teacher": {"teacher_id": tid}, "group": {"group_id": tid}}.get(mode, {})
        fid = None if (mode == "teacher" or self.ctx.all_formations) else self.ctx.formation_id
        rep = M.report_week(self.ctx.db, fid, page.ws, tpl, **kw)
        default = str(Path.home() / f"{rep.title.replace('/', '-').replace(':', '')}_{page.ws}.{fmt}")
        path, _ = QFileDialog.getSaveFileName(self, "تصدير الجدول", default, f"*.{fmt}")
        if path:
            if not path.lower().endswith("." + fmt):
                path += "." + fmt
            try:
                export(rep, tpl, fmt, path)
            except Exception as e:
                error(self, f"تعذر التصدير: {e}")
                return
            self.statusBar().showMessage(f"تم التصدير: {path}", 8000)
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def backup_now(self):
        try:
            p = B.create_backup(self.ctx.db, "يدوي")
        except Exception as e:
            error(self, f"فشل النسخ الاحتياطي: {e}")
            return
        info(self, f"تم إنشاء نسخة احتياطية:\n{p}")

    def toggle_theme(self):
        new = "light" if theme.is_dark() else "dark"
        self.ctx.db.set_setting("theme", new)
        self.apply_theme(new)

    def apply_theme(self, mode=None):
        """تطبيق لوحة الألوان دون إعادة إنشاء الصفحات ولا لمس البيانات."""
        if mode is None:
            mode = self.ctx.db.get_setting("theme", "style") or "style"
        theme.apply(self.app, mode, getattr(self, "ui_style", "ops"))
        self._recolor_icons()
        # إعادة بناء أيقونات الشريط بألوان المظهر الجديد
        idx = self.ribbon.tabs.currentIndex()
        while self.ribbon.stack.count():
            w = self.ribbon.stack.widget(0)
            self.ribbon.stack.removeWidget(w)
            w.deleteLater()
        while self.ribbon.tabs.count():
            self.ribbon.tabs.removeTab(0)
        self._build_ribbon()
        self.ribbon.tabs.setCurrentIndex(max(0, idx))
        # إعادة رسم الصفحات المفتوحة فقط (بلا إعادة تحميل البيانات)
        for key, page in getattr(self, "pages", {}).items():
            try:
                if key == "master":
                    page.rebuild()
                elif key in ("planner", "dashboard") and hasattr(page, "refresh"):
                    page.refresh()
                else:
                    page.update()
            except Exception:
                pass

    def _recolor_icons(self):
        t = theme.CURRENT
        on_bar = self.ui_style in ("office", "focus", "daily")      # أزرار فوق شريط ملوّن
        col = "white" if on_bar else t["text"]
        for b, ic in ((self.style_btn, "mdi6.palette-swatch-outline"), (self.thm_btn, "mdi6.theme-light-dark"),
                      (self.side_btn, "mdi6.page-layout-sidebar-right")):
            b.setIcon(icon(ic, col))
        self.focus_bar.palette_btn.setIcon(icon("mdi6.console-line", "#E6E9ED"))
        self.header.recolor()
        self.header.set_user(str(getattr(self.ctx.db, "current_user", "") or ""))
        self.modern_side.recolor()
        icons = {k: ic for k, _, ic in PAGES}
        for i in range(self.side.count()):
            it = self.side.item(i)
            it.setIcon(icon(icons[it.data(Qt.UserRole)]))

    # ------------------------------------------------------------------ أنماط الواجهة
    def apply_style(self, style: str, save=True):
        style = normalize_style(style)
        self.ui_style = style
        if save:
            self.ctx.db.set_setting("ui_style", style)
        self.app.setProperty("ui_style", style)
        office, focus, daily = style == "office", style == "focus", style == "daily"
        sidebar = style in ("teal", "clean", "ops", "ledger", "command")
        self.ribbon.setVisible(office)
        self.focus_bar.setVisible(focus)
        self.top_nav.setVisible(daily)
        self.modern_side.setVisible(sidebar)
        self.side.setVisible(office)
        self.header.setVisible(sidebar or daily)
        # الواجهة أ: قائمة أيقونات ضيقة دائماً
        if style == "ops":
            self.modern_side.set_collapsed(True, emit=False)
        elif style in ("ledger", "teal", "clean", "command"):
            self.modern_side.set_collapsed(self.ctx.db.get_setting("side_collapsed", "0") == "1", emit=False)
        self.modern_side.collapse_btn.setVisible(style != "ops")
        self.header.set_rich(style == "command")
        # نقل البحث واختيار التكوين وأزرار المظهر إلى شريط النمط الحالي
        target = (self.header.slot if sidebar else self.top_nav.slot if daily
                  else (self.focus_bar.slot if focus else self.ribbon.top_l))
        for w in (self.formation_cb, self.search, self.style_btn, self.thm_btn):
            target.addWidget(w)
        self.side_btn.setVisible(office)
        self.apply_theme()
        if hasattr(self, "_current"):
            self._set_crumbs(self._current)
        master = getattr(self, "pages", {}).get("master")
        if master is not None and hasattr(master, "apply_ui_style"):
            master.apply_ui_style(style)
        self.statusBar().showMessage(f"نمط الواجهة: {dict(ALL_STYLES)[style]}", 4000)

    def cycle_style(self):
        keys = [k for k, _ in STYLES]
        cur = self.ui_style if self.ui_style in keys else keys[-1]
        self.apply_style(keys[(keys.index(cur) + 1) % len(keys)])

    def toggle_side(self):
        if self.ui_style in ("teal", "clean", "ledger", "ops", "command"):
            self.modern_side.set_collapsed(not self.modern_side.collapsed)
        elif self.ui_style == "office":
            self.side.setVisible(not self.side.isVisible())

    def command_palette(self):
        cmds = [(f"اذهب إلى: {t}", ic, (lambda k=k: self.navigate(k))) for k, t, ic in PAGES]
        cmds += [("إنشاء جدول آلياً", "mdi6.auto-fix", self.open_generate),
                 ("نسخة احتياطية الآن", "mdi6.content-save-move-outline", self.backup_now),
                 ("طباعة البرنامج الرسمي (معاينة)", "mdi6.printer-eye", self.print_program),
                 ("تصدير الأسبوع PDF", "mdi6.file-pdf-box", lambda: self.quick_export("pdf")),
                 ("تبديل الوضع الفاتح/الداكن", "mdi6.theme-light-dark", self.toggle_theme)]
        cmds += [(f"نمط الواجهة: {lab}", "mdi6.palette-swatch-outline", (lambda k=k: self.apply_style(k)))
                 for k, lab in STYLES]
        p = CommandPalette(self, cmds)
        g = self.geometry()
        p.move(g.center().x() - p.width() // 2, g.y() + 90)
        p.exec()

    # ------------------------------------------------------------- الشريط العلوي
    def _set_crumbs(self, key: str):
        """مسار التنقل: DPP ‹ المجموعة ‹ الصفحة."""
        titles = {k: t for k, t, _ in PAGES}
        group = next((g for g, keys in NAV_GROUPS if key in keys), "")
        parts = ["DPP"] + ([group] if group else []) + [titles.get(key, "")]
        self.header.set_crumbs([p for p in parts if p])

    def _notif_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.aboutToShow.connect(lambda: self._fill_notifs(m))
        return m

    def _fill_notifs(self, m):
        """مركز الإشعارات: تعارضات الأسبوعين، تذكيرات الرزنامة، التنبيهات المفتوحة."""
        from ..services import alerts as AL
        from ..services import conflicts as CF
        from ..utils import week_start
        m.clear()
        n = 0
        try:
            ws = week_start(date.today())
            conf = CF.active_conflicts(self.ctx.db, ws, ws + timedelta(days=13))
        except Exception:
            conf = []
        if conf:
            m.addSection(f"التعارضات ({len(conf)})")
            for c in conf[:6]:
                txt = c.get("text") or c.get("title") or c.get("kind") or "تعارض"
                m.addAction(icon("mdi6.alert-outline", theme.CURRENT["bad"]), str(txt)[:90],
                            lambda: self.navigate("master"))
            n += len(conf)
        try:
            rem = C.due_reminders(self.ctx.db)
        except Exception:
            rem = []
        if rem:
            m.addSection(f"تذكيرات الرزنامة ({len(rem)})")
            for r in rem[:6]:
                m.addAction(icon("mdi6.calendar-clock", theme.CURRENT["warn"]), str(r.get("title", ""))[:90],
                            lambda: self.navigate("calendar"))
            n += len(rem)
        try:
            al = AL.open_alerts(self.ctx.db)
        except Exception:
            al = []
        if al:
            m.addSection(f"تنبيهات ({len(al)})")
            for a in al[:6]:
                m.addAction(icon("mdi6.information-outline", theme.CURRENT["muted"]), str(a.get("title", ""))[:90],
                            lambda: self.navigate("progress"))
            n += len(al)
        if not n:
            act = m.addAction(icon("mdi6.check-circle-outline", theme.CURRENT["ok"]), "لا توجد إشعارات")
            act.setEnabled(False)

    def _user_menu(self):
        from PySide6.QtWidgets import QMenu
        m = QMenu(self)
        m.addAction(icon("mdi6.cog-outline"), "الإعدادات", lambda: self.navigate("settings"))
        m.addAction(icon("mdi6.theme-light-dark"), "تبديل الوضع الفاتح/الداكن", self.toggle_theme)
        sm = m.addMenu(icon("mdi6.palette-swatch-outline"), "نمط الواجهة")
        for k, lab in STYLES:
            sm.addAction(lab, lambda k=k: self.apply_style(k))
        m.addSeparator()
        m.addAction(icon("mdi6.content-save-move-outline"), "نسخة احتياطية الآن", self.backup_now)
        m.addAction(icon("mdi6.console-line"), "لوحة الأوامر  Ctrl+K", self.command_palette)
        m.addSeparator()
        m.addAction(icon("mdi6.information-outline"), "حول DPP", self.about)
        return m

    def update_badges(self):
        try:
            from ..services import conflicts as CF
            from ..utils import week_start
            ws = week_start(date.today())
            n = len(CF.active_conflicts(self.ctx.db, ws, ws + timedelta(days=13)))
            self.modern_side.buttons["master"].set_badge(n)
            rem = len(C.due_reminders(self.ctx.db))
            self.modern_side.buttons["calendar"].set_badge(rem, warn=False)
            ab = self.ctx.db.scalar("SELECT COUNT(*) FROM absences WHERE start_date<=? AND end_date>=?",
                                    (date.today().isoformat(), date.today().isoformat()), 0)
            self.modern_side.buttons["absences"].set_badge(ab, warn=False)
            self.modern_side.user.setText(f"المستخدم: {self.ctx.db.current_user}")
            try:
                from ..services import alerts as AL
                self.header.set_notifications(n + rem + AL.count_open(self.ctx.db))
            except Exception:
                self.header.set_notifications(n + rem)
            self.header.set_user(str(self.ctx.db.current_user or ""))
            if getattr(self, "_current", "") == "master" and "master" in self.pages:
                g = self.pages["master"].grid
                from ..services.grid import week_number
                self.header.sub.setText(f"الأسبوع {week_number(self.ctx.db, g.ws)} · {len(g.sections)} قسماً · "
                                        f"{len(g.cards)} حصة")
            else:
                self.header.sub.setText("")
        except Exception:
            pass

    def replace_db(self, new_db):
        self.ctx.db = new_db
        self.ctx._formation_id = None
        self._fill_formations()
        self._update_status()
        self.ctx.changed("*")

    def about(self):
        info(self, f"DPP — برنامج تسيير مؤسسة التكوين والتربصات\nالإصدار {__version__}\n\n"
                   f"قاعدة البيانات: {self.ctx.db.path}\n"
                   "محرك الجدولة: Google OR-Tools (CP-SAT)\nالواجهة: Qt / PySide6", "حول DPP")

    def _bootstrap_curriculum(self):
        """الإصدار 1.4: إدراج المقرر المرفق مرة واحدة (ما أدخلته يدوياً لا يُمس)."""
        try:
            from ..services import fullday as FD
            from ..services import templates as TP
            FD.subjects(self.ctx.db)
            FD.bootstrap_exams(self.ctx.db)
            TP.migrate_to_layout(self.ctx.db)
        except Exception:
            pass
        try:
            from ..importers import curriculum as CI
            res = CI.bootstrap(self.ctx.db)
        except Exception as ex:          # لا يمنع البرنامج من العمل
            self.statusBar().showMessage(f"تعذر إدراج المقرر المرفق: {ex}", 10000)
            return
        if res:
            self.ctx.changed("curriculum")
            self.statusBar().showMessage(
                f"أُدرج المقرر المرفق: {res['imported']} مادة، {res['created']} مادة جديدة، "
                f"{res['issues']} سطر للمراجعة — راجع «المقرر والتقدم ← التنبيهات».", 20000)

    def _time_reminders(self):
        """قبل بداية حصة اليوم بالمدة المحددة في الإعدادات: صوت التذكير ورسالة في شريط الحالة."""
        from datetime import datetime

        from . import sounds
        o = sounds.load(self.ctx.db)
        if not o.get("enabled") or not o.get("reminder"):
            return
        now = datetime.now()
        target = now.hour * 60 + now.minute + int(o.get("reminder_min", 10))
        try:
            rows = self.ctx.db.q("""SELECT s.id, s.start_min, sub.name sname, GROUP_CONCAT(DISTINCT sec.short) secs
                                    FROM sessions s JOIN subjects sub ON sub.id=s.subject_id
                                    LEFT JOIN session_groups sg ON sg.session_id=s.id
                                    LEFT JOIN groups_ g ON g.id=sg.group_id LEFT JOIN sections sec ON sec.id=g.section_id
                                    WHERE s.date=? AND s.status='planned' AND s.start_min=?
                                    AND COALESCE(sub.kind,'teach')<>'nonteach' GROUP BY s.id""",
                                 (now.date().isoformat(), target))
        except Exception:
            return
        new = [r for r in rows if r["id"] not in self._reminded]
        if not new:
            return
        self._reminded |= {r["id"] for r in new}
        sounds.play("reminder", self.ctx.db)
        self.statusBar().showMessage(
            f"بعد {o.get('reminder_min', 10)} دقائق ({len(new)} حصة): " +
            " · ".join(f"{r['sname']} — {r['secs'] or ''}" for r in new[:4]), 60000)

    def _restore_word_templates(self):
        """مراقبة قوالب Word المفتوحة سابقاً واستيراد ما حُفظ منها والبرنامج مغلق."""
        try:
            from .word_ui import watcher
            watcher(self.ctx).restore()
        except Exception:
            pass

    def _startup_notices(self):
        try:
            from ..services import alerts as AL
            from . import sounds
            if AL.count_open(self.ctx.db) or C.due_reminders(self.ctx.db):
                sounds.play("alert", self.ctx.db)
        except Exception:
            pass
        try:
            rem = C.due_reminders(self.ctx.db)
        except Exception:                 # قاعدة البيانات أُغلقت
            return
        if rem:
            msg = "\n".join(f"• {e['title']} ({e['kind_label']}) — " + ("اليوم" if e["days_left"] <= 0 else f"بعد {e['days_left']} يوم")
                            for e in rem[:8])
            self.statusBar().showMessage(f"{len(rem)} تذكير بموعد قريب — راجع لوحة التحكم.", 15000)
            try:
                from PySide6.QtWidgets import QSystemTrayIcon
                if QSystemTrayIcon.isSystemTrayAvailable():
                    if not hasattr(self, "_tray"):
                        self._tray = QSystemTrayIcon(self.windowIcon(), self)
                        self._tray.show()
                    self._tray.showMessage("DPP — مواعيد قريبة", msg, QSystemTrayIcon.Information, 10000)
            except Exception:
                pass

    def closeEvent(self, e):
        if self.app.property("dpp_wiped"):          # قاعدة البيانات مُسحت وأُغلقت
            super().closeEvent(e)
            return
        try:
            B.auto_backup_if_due(self.ctx.db, hours=12)
        except Exception:
            pass
        self.ctx.db.close()
        super().closeEvent(e)


# ===================================================================== تسجيل الدخول
class LoginDialog(QDialog):
    def __init__(self, db, first_run: bool):
        super().__init__()
        self.db, self.first = db, first_run
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("DPP — " + ("إنشاء حساب المدير" if first_run else "تسجيل الدخول"))
        self.setMinimumWidth(380)
        v = QVBoxLayout(self)
        t = QLabel("DPP")
        t.setObjectName("PageTitle")
        t.setAlignment(Qt.AlignCenter)
        v.addWidget(t)
        s = QLabel("تسيير مؤسسة التكوين والتربصات" + ("\nأول تشغيل: أنشئ حساب المدير (حساب واحد بكل الصلاحيات)." if first_run else ""))
        s.setObjectName("Muted")
        s.setAlignment(Qt.AlignCenter)
        v.addWidget(s)
        f = QFormLayout()
        self.user = QLineEdit("admin")
        self.pw = QLineEdit()
        self.pw.setEchoMode(QLineEdit.Password)
        f.addRow("اسم المستخدم", self.user)
        f.addRow("كلمة المرور", self.pw)
        if first_run:
            self.pw2 = QLineEdit()
            self.pw2.setEchoMode(QLineEdit.Password)
            f.addRow("تأكيد كلمة المرور", self.pw2)
        v.addLayout(f)
        self.err = QLabel()
        self.err.setStyleSheet(f"color:{theme.CURRENT['bad']}")
        v.addWidget(self.err)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("إنشاء الحساب" if first_run else "دخول")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("خروج")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.pw.setFocus()

    def _ok(self):
        u, p = self.user.text().strip(), self.pw.text()
        if self.first:
            if p != self.pw2.text():
                self.err.setText("كلمتا المرور غير متطابقتين.")
                return
            try:
                self.db.create_admin(u, p)
            except ValueError as e:
                self.err.setText(str(e))
                return
            self.db.check_login(u, p)
            self.accept()
        elif self.db.check_login(u, p):
            self.db.log("تسجيل الدخول")
            self.accept()
        else:
            self.err.setText("اسم المستخدم أو كلمة المرور غير صحيحة.")
            self.pw.selectAll()
