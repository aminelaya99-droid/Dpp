"""أنماط الواجهة الأربعة (تختلف في تنظيم النافذة، لا في اللون فقط):

* office «Office فاتح»: شريط أوامر Ribbon بتبويبات ومجموعات، خلفية فاتحة، لوحة صفحات جانبية بسيطة.
* teal   «عصري داكن» (الافتراضي): قائمة جانبية داكنة مجمّعة (الجدولة / البيانات / المتابعة / النظام) بشارات،
  ورأس صفحة خفيف، بالأخضر البترولي والتركواز.
* clean  «فاتح احترافي»: قائمة جانبية فاتحة قابلة للطيّ إلى أيقونات، بطاقات نظيفة ومساحات مرتبة.
* focus  «تركيز»: بلا قائمة جانبية؛ شريط علوي رفيع ولوحة أوامر Ctrl+K، رمادي داكن.
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)

from .widgets import icon

# الواجهات الثلاث (الإصدار 1.4) — تُختار من الإعدادات ← المظهر
STYLES = [("ops", "أ — غرفة العمليات (داكن، قائمة أيقونات)"), ("ledger", "ب — السجل (فاتح، شكل الورقة المطبوعة)"),
          ("daily", "ج — يوم بيوم (فاتح، تنقل علوي)")]
# الأنماط السابقة تبقى صالحة (للقواعد القديمة والاختبارات) لكنها لا تُعرض في القائمة
OLD_STYLES = [("office", "Office فاتح (Ribbon)"), ("teal", "عصري داكن (أخضر بترولي)"),
              ("clean", "فاتح احترافي"), ("focus", "تركيز (لوحة أوامر)")]
ALL_STYLES = STYLES + OLD_STYLES
LEGACY_STYLES = {"modern": "teal", "classic": "office"}
# عند أول تشغيل للإصدار 1.4: النمط القديم ← أقرب واجهة جديدة
UPGRADE = {"teal": "ops", "focus": "ops", "clean": "ledger", "office": "daily"}


def normalize_style(style: str | None) -> str:
    style = LEGACY_STYLES.get(style or "", style or "ops")
    return style if style in dict(ALL_STYLES) else "ops"

NAV_GROUPS = [
    ("الجدولة", ["master", "planner", "weeks", "dashboard"]),
    ("البيانات", ["formations", "structure", "levels", "specialties", "cohorts", "periods", "sections", "groups", "subjects", "rooms", "requirements", "teachers",
                 "categories"]),
    ("المتابعة", ["absences", "calendar", "duty", "progress", "reports", "unavailability"]),
    ("النظام", ["import", "settings"]),
]


class NavButton(QPushButton):
    """زر صفحة في القائمة الجانبية: الأيقونة ثم الاسم ملتصقين باليمين (تخطيط RTL صريح)،
    والشارة في الطرف الآخر. في الوضع المطوي تبقى الأيقونة في الوسط ويظهر الاسم كتلميح."""

    def __init__(self, key, title, ic):
        super().__init__("")
        self.key = key
        self.ic = ic
        self.title = title
        self.setToolTip(title)
        self.setObjectName("NavItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setLayoutDirection(Qt.RightToLeft)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 0, 10, 0)
        lay.setSpacing(9)
        self.ic_lbl = QLabel()
        self.ic_lbl.setFixedSize(20, 20)
        self.ic_lbl.setAlignment(Qt.AlignCenter)
        self.txt = QLabel(title)
        self.txt.setObjectName("NavText")
        self.txt.setAlignment(Qt.AlignRight | Qt.AlignVCenter | Qt.AlignAbsolute)
        self.badge = QLabel()
        self.badge.setObjectName("Badge")
        self.badge.hide()
        lay.addWidget(self.ic_lbl)
        lay.addWidget(self.txt, 1)
        lay.addWidget(self.badge)
        self._lay = lay
        for w in (self.ic_lbl, self.txt, self.badge):
            w.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.set_colors("#C9D1DE")

    def set_colors(self, color: str):
        self.ic_lbl.setPixmap(icon(self.ic, color).pixmap(18, 18))
        self.txt.setStyleSheet(f"color: {color}; background: transparent; font-weight: "
                               f"{'bold' if self.isChecked() else 'normal'};")

    def set_collapsed(self, on: bool):
        self.txt.setVisible(not on)
        self._lay.setContentsMargins(0, 0, 0, 0) if on else self._lay.setContentsMargins(10, 0, 10, 0)
        self._lay.setAlignment(self.ic_lbl, Qt.AlignHCenter if on else Qt.AlignRight)
        if on:
            self.badge.hide()
        self.setToolTip(self.title)

    def sizeHint(self):
        from PySide6.QtCore import QSize as _S
        return _S(40, 38)

    def set_badge(self, n: int | str | None, warn=True):
        if self.property("collapsed") == "1":
            self.setToolTip(f"{self.title} ({n})" if n else self.title)
            self.badge.hide()
            return
        if not n:
            self.badge.hide()
            return
        self.badge.setText(str(n))
        self.badge.setProperty("warn", "1" if warn else "0")
        self.badge.style().unpolish(self.badge)
        self.badge.style().polish(self.badge)
        self.badge.show()


class ModernSidebar(QFrame):
    navigate = Signal(str)

    def __init__(self, pages: list[tuple], parent=None):
        super().__init__(parent)
        self.setObjectName("ModernSide")
        self.setFixedWidth(240)
        self.collapsed = False
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 10, 8, 8)
        v.setSpacing(2)
        head = QHBoxLayout()
        self.logo = QLabel()
        head.addWidget(self.logo)
        t = QVBoxLayout()
        self.title_lbl = QLabel("DPP")
        self.title_lbl.setObjectName("SideTitle")
        self.sub_lbl = QLabel("مخطط التكوين")
        self.sub_lbl.setObjectName("SideSub")
        t.addWidget(self.title_lbl)
        t.addWidget(self.sub_lbl)
        head.addLayout(t)
        head.addStretch()
        self.collapse_btn = QToolButton()
        self.collapse_btn.setObjectName("SideCollapse")
        self.collapse_btn.setToolTip("طيّ / توسيع القائمة (Ctrl+B)")
        self.collapse_btn.setCursor(Qt.PointingHandCursor)
        self.collapse_btn.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        head.addWidget(self.collapse_btn)
        v.addLayout(head)
        self.group_labels: list[QLabel] = []
        v.addSpacing(8)
        titles = {k: (title, ic) for k, title, ic in pages}
        self.buttons: dict[str, NavButton] = {}
        inner = QWidget()
        inner.setObjectName("ModernSideInner")
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(1)
        for gname, keys in NAV_GROUPS:
            lab = QLabel(gname)
            lab.setObjectName("NavGroup")
            self.group_labels.append(lab)
            iv.addWidget(lab)
            for k in keys:
                if k not in titles:
                    continue
                btn = NavButton(k, *titles[k])
                btn.clicked.connect(lambda _=False, k=k: self.navigate.emit(k))
                iv.addWidget(btn)
                self.buttons[k] = btn
        iv.addStretch()
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(inner)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setObjectName("ModernSideScroll")
        # بلا شريط تمرير ظاهر (كان يترك عموداً فارغاً بين القائمة والصفحة)؛ التمرير بالعجلة يبقى
        sc.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        v.addWidget(sc, 1)
        self.footer = QHBoxLayout()
        self.user = QLabel()
        self.user.setObjectName("SideSub")
        self.footer.addWidget(self.user)
        self.footer.addStretch()
        v.addLayout(self.footer)

    collapsed_changed = Signal(bool)

    def set_current(self, key: str):
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self.recolor()

    def set_collapsed(self, on: bool, emit=True):
        self.collapsed = on
        self.setFixedWidth(66 if on else 240)
        for lab in self.group_labels:
            lab.setVisible(not on)
        self.title_lbl.setVisible(not on)
        self.sub_lbl.setVisible(not on)
        self.user.setVisible(not on)
        for b in self.buttons.values():
            b.set_collapsed(on)
            b.setProperty("collapsed", "1" if on else "0")
            b.style().unpolish(b)
            b.style().polish(b)
            if on:
                b.badge.hide()
        self.recolor()
        if emit:
            self.collapsed_changed.emit(on)

    def recolor(self):
        from . import theme
        t = theme.CURRENT
        for b in self.buttons.values():
            b.set_colors(t["side_active_text"] if b.isChecked() else t["side_text"])
        self.logo.setPixmap(icon("mdi6.calendar-star", t["accent"]).pixmap(26, 26))
        self.collapse_btn.setIcon(icon("mdi6.chevron-double-right" if not self.collapsed else "mdi6.chevron-double-left",
                                       t["side_muted"]))


class ContentHeader(QFrame):
    """رأس الصفحة في النمط العصري: العنوان + البحث + أزرار سريعة."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentHeader")
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(14, 8, 14, 8)
        self.title = QLabel()
        self.title.setObjectName("HeaderTitle")
        self.sub = QLabel()
        self.sub.setObjectName("Muted")
        tv = QVBoxLayout()
        tv.setSpacing(0)
        tv.addWidget(self.title)
        tv.addWidget(self.sub)
        self.h.addLayout(tv)
        self.h.addStretch()
        self.slot = QHBoxLayout()     # يُنقل إليه البحث واختيار التكوين
        self.h.addLayout(self.slot)


class TopNav(QFrame):
    """شريط التنقل العلوي للواجهة ج: الصفحات الرئيسية أزراراً، والباقي في «المزيد»."""
    navigate = Signal(str)
    MAIN = ["master", "planner", "weeks", "structure", "progress", "teachers", "absences", "duty", "calendar", "reports"]

    def __init__(self, pages: list[tuple], parent=None):
        super().__init__(parent)
        from PySide6.QtWidgets import QMenu
        self.setObjectName("TopNav")
        self.setFixedHeight(54)
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(8, 6, 12, 6)
        self.h.setSpacing(4)
        t = QLabel("DPP")
        t.setObjectName("TopTitle")
        self.h.addWidget(t)
        titles = {k: (title, ic) for k, title, ic in pages}
        self.titles = titles
        self.buttons: dict[str, QPushButton] = {}

        nav = self

        class _NavBox(QWidget):
            def minimumSizeHint(self):          # لا يفرض عرضاً: الأزرار التي لا تتسع تنتقل إلى «المزيد»
                from PySide6.QtCore import QSize
                return QSize(nav.more.sizeHint().width() + 8, super().minimumSizeHint().height())

            def resizeEvent(self, e):
                super().resizeEvent(e)
                nav._fit()
        self.navbox = _NavBox()
        nb = QHBoxLayout(self.navbox)
        nb.setContentsMargins(0, 0, 0, 0)
        nb.setSpacing(4)
        for k in self.MAIN:
            if k not in titles:
                continue
            b = QPushButton(titles[k][0])
            b.setObjectName("TopNavItem")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=k: self.navigate.emit(k))
            b.setMinimumWidth(b.sizeHint().width())
            nb.addWidget(b)
            self.buttons[k] = b
        more = QPushButton("المزيد")
        more.setObjectName("TopNavItem")
        more.setCursor(Qt.PointingHandCursor)
        self.menu = QMenu(more)
        self.menu.aboutToShow.connect(self._fill_more)
        more.setMenu(self.menu)
        self.more = more
        nb.addWidget(more)
        nb.addStretch()
        self.h.addWidget(self.navbox, 1)
        self.slot = QHBoxLayout()
        self.h.addLayout(self.slot)

    def _fill_more(self):
        m = self.menu
        m.clear()
        hidden = [k for k, b in self.buttons.items() if b.isHidden()]
        if hidden:
            m.addSection("الصفحات")
            for k in hidden:
                m.addAction(icon(self.titles[k][1]), self.titles[k][0], lambda k=k: self.navigate.emit(k))
        for gname, keys in NAV_GROUPS:
            extra = [k for k in keys if k in self.titles and k not in self.MAIN]
            if not extra:
                continue
            m.addSection(gname)
            for k in extra:
                m.addAction(icon(self.titles[k][1]), self.titles[k][0], lambda k=k: self.navigate.emit(k))

    def _fit(self):
        avail = self.navbox.width() - self.more.sizeHint().width() - 8
        used = 0
        for b in self.buttons.values():
            w = b.sizeHint().width() + 4
            show = used + w <= avail
            b.setVisible(show)
            if show:
                used += w

    def set_current(self, key: str):
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        self.more.setChecked(False)


class FocusBar(QFrame):
    """شريط نمط «تركيز» الرفيع."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FocusBar")
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(10, 3, 10, 3)
        a = QLabel("DPP")
        a.setObjectName("FocusTitle")
        self.h.addWidget(a)
        self.title = QLabel()
        self.title.setObjectName("FocusPage")
        self.h.addWidget(self.title)
        self.h.addStretch()
        self.palette_btn = QToolButton()
        self.palette_btn.setText("لوحة الأوامر  Ctrl+K")
        self.palette_btn.setIcon(icon("mdi6.console-line", "#E6E9ED"))
        self.palette_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.h.addWidget(self.palette_btn)
        self.slot = QHBoxLayout()
        self.h.addLayout(self.slot)


class CommandPalette(QDialog):
    """لوحة أوامر: اكتب للبحث في الصفحات والأوامر، Enter للتنفيذ."""

    def __init__(self, parent, commands: list[tuple[str, str, object]]):
        super().__init__(parent)
        self.setObjectName("Palette")
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.resize(560, 420)
        self.commands = commands
        v = QVBoxLayout(self)
        v.setContentsMargins(10, 10, 10, 10)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("اكتب أمراً أو اسم صفحة…")
        v.addWidget(self.edit)
        self.lst = QListWidget()
        v.addWidget(self.lst, 1)
        self.edit.textChanged.connect(self._fill)
        self.edit.returnPressed.connect(self._run)
        self.lst.itemActivated.connect(lambda _: self._run())
        self._fill("")

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            r = self.lst.currentRow() + (1 if e.key() == Qt.Key_Down else -1)
            self.lst.setCurrentRow(max(0, min(self.lst.count() - 1, r)))
            return
        super().keyPressEvent(e)

    def _fill(self, text):
        self.lst.clear()
        t = text.strip()
        for title, ic, fn in self.commands:
            if t and t not in title:
                continue
            it = QListWidgetItem(icon(ic), title)
            it.setData(Qt.UserRole, fn)
            self.lst.addItem(it)
        self.lst.setCurrentRow(0)

    def _run(self):
        it = self.lst.currentItem()
        if it:
            fn = it.data(Qt.UserRole)
            self.accept()
            fn()
