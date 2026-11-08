"""المظاهر ونظام الألوان (Design tokens) لكل نمط واجهة."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPalette

# نظام التصميم (مستخرج بمهارة UI/UX Pro Max): نمط «سويسري بسيط» لأدوات العمل الكثيفة،
# لون أساسي أخضر بترولي (teal) للإجراءات والتحديد، وبرتقالي للأمر الرئيسي فقط، وأحمر للتعارض.
# كل الألوان النصية تحقق تباين 4.5:1 على خلفياتها. كل نمط واجهة له لوحة ألوان خاصة به.
_BASE_LIGHT = {
    "accent": "#0F766E", "accent_hover": "#0D9488", "accent_text": "#FFFFFF",
    "cta": "#C2410C", "cta_hover": "#EA580C", "focus": "#0D9488",
    "ok": "#15803D", "warn": "#B45309", "bad": "#C62828",
}
# 1) Office / Ribbon فاتح
OFFICE = dict(_BASE_LIGHT, **{
    "bg": "#F3F5F6", "surface": "#FFFFFF", "surface2": "#F8FAFA", "border": "#D6DDDF", "text": "#1B2629",
    "muted": "#56656A", "ribbon": "#0F6B64", "ribbon_panel": "#FFFFFF", "sel": "#D3EEEB", "grid": "#E4EAEB",
    "header": "#F0F4F4",
    "side_bg": "#FFFFFF", "side_text": "#1B2629", "side_muted": "#6B7B80", "side_active": "#D3EEEB",
    "side_active_text": "#0B5D57", "side_hover": "rgba(15,118,110,0.07)", "side_border": "#D6DDDF",
})
# 3) Clean Light Professional (قائمة جانبية فاتحة)
LIGHT = dict(_BASE_LIGHT, **{
    "bg": "#F5F7F9", "surface": "#FFFFFF", "surface2": "#F8FAFB", "border": "#DDE3E7", "text": "#16232A",
    "muted": "#5A6B73", "ribbon": "#13343B", "ribbon_panel": "#FFFFFF", "sel": "#D9F0EE", "grid": "#E7ECEF",
    "header": "#F2F5F7",
    "side_bg": "#FFFFFF", "side_text": "#24343B", "side_muted": "#7A8A91", "side_active": "#E1F3F1",
    "side_active_text": "#0B5D57", "side_hover": "rgba(16,35,42,0.05)", "side_border": "#E3E8EB",
})
CLEAN = LIGHT
# 2) Modern Dark Teal
DARK = {
    "bg": "#0D1719", "surface": "#122124", "surface2": "#16282B", "border": "#22393C", "text": "#E2EEEE",
    "muted": "#98B0B2", "accent": "#2DD4BF", "accent_hover": "#5EEAD4", "accent_text": "#052421",
    "cta": "#FB923C", "cta_hover": "#FDBA74", "focus": "#5EEAD4",
    "ribbon": "#0A2A28", "ribbon_panel": "#142427", "ok": "#4ADE80", "warn": "#FBBF24", "bad": "#F87171",
    "sel": "#15504A", "grid": "#203538", "header": "#0F1E21",
    "side_bg": "#081315", "side_text": "#CFE0E0", "side_muted": "#6E8A8C", "side_active": "#0F766E",
    "side_active_text": "#FFFFFF", "side_hover": "rgba(45,212,191,0.10)", "side_border": "#06100F",
}
TEAL_DARK = DARK
# 4) تركيز: رمادي داكن
GRAPHITE = {
    "bg": "#1E1F22", "surface": "#26272B", "surface2": "#2C2D31", "border": "#3B3D43", "text": "#E8EAED",
    "muted": "#A0A6AD", "accent": "#5EEAD4", "accent_hover": "#99F6E4", "accent_text": "#0B1F1D",
    "cta": "#FB923C", "cta_hover": "#FDBA74", "focus": "#99F6E4",
    "ribbon": "#2A2C31", "ribbon_panel": "#26272B", "ok": "#86EFAC", "warn": "#FCD34D", "bad": "#FCA5A5",
    "sel": "#1F4B47", "grid": "#34363B", "header": "#222326",
    "side_bg": "#18191C", "side_text": "#D6D9DD", "side_muted": "#7D838A", "side_active": "#0F766E",
    "side_active_text": "#FFFFFF", "side_hover": "rgba(255,255,255,0.06)", "side_border": "#111214",
}

# ---- الإصدار 1.4: الواجهات الثلاث (من التصميم الذي اختاره المستخدم) ----
# أ) غرفة العمليات: داكن، قائمة أيقونات ضيقة، لون عنبري للأوامر والتحديد
OPS = {
    "bg": "#12161B", "surface": "#161B21", "surface2": "#1E252D", "border": "#2C3540", "text": "#E7ECEF",
    "muted": "#93A0AC", "accent": "#E8B04A", "accent_hover": "#F4CB78", "accent_text": "#12161B",
    "cta": "#E8B04A", "cta_hover": "#F4CB78", "focus": "#F4CB78",
    "ribbon": "#0D1014", "ribbon_panel": "#161B21", "ok": "#7FB069", "warn": "#E0B259", "bad": "#F07167",
    "sel": "#3A3220", "grid": "#222A33", "header": "#1A2027",
    "side_bg": "#0D1014", "side_text": "#CDD5DC", "side_muted": "#6F7C88", "side_active": "#2E3843",
    "side_active_text": "#E8B04A", "side_hover": "rgba(232,176,74,0.10)", "side_border": "#0A0C0F",
    "radius": "10px",
}
# ب) السجل: فاتح بشكل الورقة المطبوعة، خطوط حبر وأزرق رسمي
LEDGER = {
    "bg": "#E7EAEE", "surface": "#FFFFFF", "surface2": "#F5F6F8", "border": "#C8CED8", "text": "#1F2A44",
    "muted": "#5B6577", "accent": "#2B4C9B", "accent_hover": "#3A5FB8", "accent_text": "#FFFFFF",
    "cta": "#1F2A44", "cta_hover": "#2B3A5C", "focus": "#2B4C9B",
    "ribbon": "#1F2A44", "ribbon_panel": "#FFFFFF", "ok": "#3F7A2A", "warn": "#A26B0F", "bad": "#9B2C1F",
    "sel": "#DDE6F5", "grid": "#E3E7ED", "header": "#F2F4F7",
    "side_bg": "#E7EAEE", "side_text": "#3B465C", "side_muted": "#6B7588", "side_active": "#FFFFFF",
    "side_active_text": "#1F2A44", "side_hover": "rgba(31,42,68,0.06)", "side_border": "#D3D8E0",
    "radius": "4px",
}
# ج) يوم بيوم: فاتح، شريط تنقل علوي أخضر داكن (هوية البرنامج)
DAILY = {
    "bg": "#F1F4F3", "surface": "#FFFFFF", "surface2": "#F7FAF9", "border": "#D5DEDB", "text": "#17211E",
    "muted": "#5A6A65", "accent": "#0E7C66", "accent_hover": "#109079", "accent_text": "#FFFFFF",
    "cta": "#17211E", "cta_hover": "#2A3833", "focus": "#0E7C66",
    "ribbon": "#0F2A24", "ribbon_panel": "#FFFFFF", "ok": "#2F7D32", "warn": "#A15C07", "bad": "#B42318",
    "sel": "#DCEFEA", "grid": "#E4EAE8", "header": "#F3F7F6",
    "side_bg": "#0F2A24", "side_text": "#B9CEC8", "side_muted": "#7FA096", "side_active": "#1F4A40",
    "side_active_text": "#FFFFFF", "side_hover": "rgba(255,255,255,0.08)", "side_border": "#0A1E1A",
    "radius": "12px",
}

# د) DPP الحديثة (الافتراضي، الإصدار 1.7): Fluent + لوحة SaaS — قائمة جانبية داكنة مجمّعة،
# شريط علوي بمسار تنقل وبحث وإشعارات، بطاقات بزوايا ناعمة وظلال خفيفة، والأخضر العسكري لون الهوية.
COMMAND = {
    "bg": "#F4F6FA", "surface": "#FFFFFF", "surface2": "#F8FAFC", "border": "#E2E8F0", "text": "#0E1726",
    "muted": "#55657C", "accent": "#15803D", "accent_hover": "#166534", "accent_text": "#FFFFFF",
    "cta": "#15803D", "cta_hover": "#166534", "focus": "#15803D",
    "ribbon": "#0D1526", "ribbon_panel": "#FFFFFF", "ok": "#15803D", "warn": "#B45309", "bad": "#DC2626",
    "sel": "#DCFCE7", "grid": "#E8EDF3", "header": "#F8FAFC",
    "side_bg": "#0D1526", "side_text": "#C3CEDE", "side_muted": "#76859B", "side_active": "rgba(34,197,94,0.22)",
    "side_active_text": "#FFFFFF", "side_hover": "rgba(255,255,255,0.07)", "side_border": "#0A101D",
    "radius": "12px",
}
COMMAND_DARK = {
    "bg": "#0B1220", "surface": "#121B2C", "surface2": "#162033", "border": "#24324A", "text": "#E8EEF7",
    "muted": "#93A3BA", "accent": "#22C55E", "accent_hover": "#4ADE80", "accent_text": "#04140B",
    "cta": "#22C55E", "cta_hover": "#4ADE80", "focus": "#4ADE80",
    "ribbon": "#070D18", "ribbon_panel": "#121B2C", "ok": "#4ADE80", "warn": "#FBBF24", "bad": "#F87171",
    "sel": "#14361F", "grid": "#1E2A3F", "header": "#101828",
    "side_bg": "#070D18", "side_text": "#AFC0D6", "side_muted": "#7C8DA6", "side_active": "rgba(34,197,94,0.20)",
    "side_active_text": "#FFFFFF", "side_hover": "rgba(255,255,255,0.06)", "side_border": "#05090F",
    "radius": "12px",
}

PALETTES = {"office": OFFICE, "clean": LIGHT, "light": LIGHT, "dark": DARK, "teal": DARK, "graphite": GRAPHITE,
            "ops": OPS, "ledger": LEDGER, "daily": DAILY, "command": COMMAND, "command_dark": COMMAND_DARK}
# اللوحة الافتراضية لكل نمط واجهة (عند اختيار «حسب النمط»)
STYLE_THEME = {"office": "office", "teal": "dark", "clean": "clean", "focus": "graphite",
               "ops": "ops", "ledger": "ledger", "daily": "daily", "command": "command"}
NEW_STYLES = ("ops", "ledger", "daily", "command")
# لكل نمط حديث: (لوحته الفاتحة، لوحته الداكنة) — يستعملها «تلقائي» و«فاتح/داكن»
STYLE_PAIR = {"ops": ("ledger", "ops"), "ledger": ("ledger", "ops"), "daily": ("daily", "ops"),
              "command": ("command", "command_dark")}
THEME_MODES = [("style", "حسب نمط الواجهة"), ("auto", "تلقائي حسب Windows"), ("light", "فاتح"),
               ("dark", "داكن (أخضر بترولي)"), ("graphite", "رمادي داكن")]
FONTS = [("Almarai", "Almarai"), ("Tajawal", "Tajawal"), ("Cairo", "Cairo")]

CURRENT = dict(LIGHT)
CURRENT_NAME = "clean"


def system_is_dark() -> bool:
    try:
        return QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
    except Exception:
        return False


def resolve(mode: str, style: str | None = None) -> str:
    """يعيد اسم اللوحة الفعلية: office | clean | dark | graphite."""
    style = style or "clean"
    if mode in ("style", "", None):
        return STYLE_THEME.get(style, "clean")
    if style in NEW_STYLES:
        light, dark = STYLE_PAIR.get(style, ("ledger", "ops"))
        if mode == "auto":
            return dark if system_is_dark() else light
        if mode == "light":
            return light
        if mode in ("dark", "graphite"):
            return dark
        return STYLE_THEME.get(style, "ledger")
    if mode == "auto":
        return "dark" if system_is_dark() else ("office" if style == "office" else "clean")
    if mode == "light":
        return "office" if style == "office" else "clean"
    return mode if mode in ("dark", "graphite", "office", "clean") else "clean"


def is_dark(name: str | None = None) -> bool:
    return QColor((PALETTES.get(name) if name else CURRENT)["surface"]).lightness() < 110


def apply(app, mode: str, style: str | None = None) -> str:
    global CURRENT_NAME
    if style is None:
        style = app.property("ui_style") or "clean"
    name = resolve(mode, style)
    t = PALETTES.get(name, LIGHT)
    CURRENT.clear()
    CURRENT.update(t)
    CURRENT_NAME = name
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(t["bg"]))
    pal.setColor(QPalette.WindowText, QColor(t["text"]))
    pal.setColor(QPalette.Base, QColor(t["surface"]))
    pal.setColor(QPalette.AlternateBase, QColor(t["surface2"]))
    pal.setColor(QPalette.Text, QColor(t["text"]))
    pal.setColor(QPalette.Button, QColor(t["surface"]))
    pal.setColor(QPalette.ButtonText, QColor(t["text"]))
    pal.setColor(QPalette.Highlight, QColor(t["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(t["accent_text"]))
    pal.setColor(QPalette.ToolTipBase, QColor(t["surface"]))
    pal.setColor(QPalette.ToolTipText, QColor(t["text"]))
    pal.setColor(QPalette.PlaceholderText, QColor(t["muted"]))
    app.setPalette(pal)
    app.setStyleSheet(stylesheet(t))
    return name


def stylesheet(t: dict) -> str:
    return f"""
    * {{ font-size: 10.5pt; }}
    QWidget {{ color: {t['text']}; }}
    QMainWindow, QDialog {{ background: {t['bg']}; }}
    QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 6px 8px;
        border-radius: 6px; }}
    QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px; padding: 4px; }}
    QMenu::item {{ padding: 6px 18px; border-radius: 5px; }}
    QMenu::item:selected {{ background: {t['sel']}; color: {t['text']}; }}
    QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}

    /* ---------- الشريط الكلاسيكي (Ribbon) ---------- */
    #RibbonTop {{ background: {t['ribbon']}; }}
    #RibbonTop QLabel#AppTitle {{ color: white; font-weight: bold; font-size: 12pt; padding: 0 10px; }}
    #RibbonTop QLabel {{ color: white; }}
    #RibbonTop QLineEdit {{ background: rgba(255,255,255,0.12); color: white; border: 1px solid rgba(255,255,255,0.28);
        border-radius: 6px; padding: 5px 10px; min-width: 240px; }}
    #RibbonTop QLineEdit:focus {{ border: 2px solid {t['focus']}; }}
    #RibbonTop QToolButton {{ color: white; border: 1px solid transparent; padding: 4px 8px; border-radius: 6px; }}
    #RibbonTop QToolButton:hover {{ background: rgba(255,255,255,0.14); }}
    #RibbonTop QToolButton:focus {{ border-color: {t['focus']}; }}
    QTabBar#RibbonTabs {{ background: {t['ribbon']}; }}
    QTabBar#RibbonTabs::tab {{ color: rgba(255,255,255,0.88); background: transparent; padding: 7px 18px;
        border: none; margin: 0 1px; }}
    QTabBar#RibbonTabs::tab:selected {{ background: {t['ribbon_panel']}; color: {t['text']}; font-weight: bold;
        border-top-left-radius: 6px; border-top-right-radius: 6px; }}
    QTabBar#RibbonTabs::tab:hover:!selected {{ background: rgba(255,255,255,0.12); }}
    #RibbonPanel {{ background: {t['ribbon_panel']}; border-bottom: 1px solid {t['border']}; }}
    #RibbonGroup {{ border-left: 1px solid {t['border']}; }}
    #RibbonGroup QLabel#GroupTitle {{ color: {t['muted']}; font-size: 8.5pt; }}
    #RibbonPanel QToolButton {{ color: {t['text']}; border: 1px solid transparent; border-radius: 6px; padding: 3px 6px; }}
    #RibbonPanel QToolButton:hover {{ background: {t['sel']}; border-color: {t['border']}; }}
    #RibbonPanel QToolButton:focus {{ border-color: {t['focus']}; }}
    #RibbonPanel QToolButton:pressed {{ background: {t['accent']}; color: {t['accent_text']}; }}

    /* ---------- عام ---------- */
    QStatusBar {{ background: {t['surface']}; color: {t['muted']}; border-top: 1px solid {t['border']}; }}
    QStatusBar QLabel {{ color: {t['muted']}; padding: 0 8px; }}
    QFrame#Card {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 10px; }}
    QFrame#Card:hover {{ border-color: {t['accent']}; }}
    QLabel#CardValue {{ font-size: 22pt; font-weight: bold; color: {t['accent']}; }}
    QLabel#CardTitle {{ color: {t['muted']}; }}
    QLabel#PageTitle {{ font-size: 16pt; font-weight: bold; color: {t['text']}; }}
    QLabel#Muted {{ color: {t['muted']}; }}
    QLabel#SectionTitle {{ font-size: 11.5pt; font-weight: bold; color: {t['text']}; }}
    QTableView, QTreeView, QListView, QTableWidget {{ background: {t['surface']}; alternate-background-color: {t['surface2']};
        border: 1px solid {t['border']}; border-radius: 8px; gridline-color: {t['grid']};
        selection-background-color: {t['sel']}; selection-color: {t['text']}; outline: 0; }}
    QTableView:focus, QListView:focus, QTreeView:focus {{ border: 2px solid {t['focus']}; }}
    QHeaderView::section {{ background: {t['header']}; color: {t['text']}; border: none;
        border-left: 1px solid {t['border']}; border-bottom: 1px solid {t['border']}; padding: 6px 8px; font-weight: bold; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QTextEdit, QPlainTextEdit {{
        background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 6px;
        padding: 5px 8px; min-height: 20px; selection-background-color: {t['sel']}; selection-color: {t['text']}; }}
    QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDateEdit:hover {{ border-color: {t['muted']}; }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateEdit:focus, QTimeEdit:focus,
    QTextEdit:focus, QPlainTextEdit:focus {{ border: 2px solid {t['focus']}; padding: 4px 7px; }}
    QComboBox QAbstractItemView {{ background: {t['surface']}; border: 1px solid {t['border']};
        selection-background-color: {t['sel']}; selection-color: {t['text']}; }}
    QPushButton {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; border-radius: 6px;
        padding: 6px 14px; min-height: 20px; }}
    QPushButton:hover {{ border-color: {t['accent']}; background: {t['surface2']}; }}
    QPushButton:pressed {{ background: {t['sel']}; }}
    QPushButton:focus {{ border: 2px solid {t['focus']}; padding: 5px 13px; }}
    QPushButton:disabled {{ color: {t['muted']}; background: {t['surface2']}; }}
    QPushButton#Primary {{ background: {t['accent']}; color: {t['accent_text']}; border-color: {t['accent']}; font-weight: bold; }}
    QPushButton#Primary:hover {{ background: {t['accent_hover']}; border-color: {t['accent_hover']}; }}
    QPushButton#Cta {{ background: {t['cta']}; color: white; border-color: {t['cta']}; font-weight: bold; }}
    QPushButton#Cta:hover {{ background: {t['cta_hover']}; }}
    QPushButton#Danger {{ color: {t['bad']}; border-color: {t['bad']}; }}
    QCheckBox, QRadioButton {{ spacing: 8px; padding: 2px; }}
    QCheckBox:focus, QRadioButton:focus {{ color: {t['accent']}; }}
    QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
    QGroupBox {{ border: 1px solid {t['border']}; border-radius: 10px; margin-top: 14px; padding-top: 10px;
        background: {t['surface']}; }}
    QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: {t['muted']};
        font-weight: bold; }}
    QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 8px; background: {t['surface']}; top: -1px; }}
    QTabBar::tab {{ padding: 7px 16px; border: none; color: {t['muted']}; }}
    QTabBar::tab:selected {{ color: {t['accent']}; border-bottom: 2px solid {t['accent']}; font-weight: bold; }}
    QTabBar::tab:hover:!selected {{ color: {t['text']}; }}
    QSplitter::handle {{ background: {t['border']}; }}
    QSplitter::handle:vertical {{ height: 3px; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 12px; margin: 2px; }}
    QScrollBar:horizontal {{ background: transparent; height: 12px; margin: 2px; }}
    QScrollBar::handle {{ background: {t['border']}; border-radius: 4px; min-height: 28px; min-width: 28px; }}
    QScrollBar::handle:hover {{ background: {t['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
    #SidePanel {{ background: {t['surface']}; border-left: 1px solid {t['border']}; }}
    #CardStrip {{ background: {t['surface']}; border-top: 1px solid {t['border']}; }}
    QProgressBar {{ border: 1px solid {t['border']}; border-radius: 6px; text-align: center; background: {t['surface2']}; }}
    QProgressBar::chunk {{ background: {t['accent']}; border-radius: 5px; }}

    /* ---------- النمط العصري ---------- */
    #ModernSide, #ModernSideInner, #ModernSideScroll, #ModernSideScroll > QWidget > QWidget {{ background: {t['side_bg']}; }}
    #ModernSide {{ border-left: 1px solid {t['side_border']}; }}
    #ModernSide QLabel#SideTitle {{ color: {t['side_text']}; font-size: 14pt; font-weight: bold; }}
    #ModernSide QToolButton#SideCollapse {{ border: 1px solid transparent; border-radius: 6px; padding: 4px; }}
    #ModernSide QToolButton#SideCollapse:hover {{ background: {t['side_hover']}; }}
    #ModernSide QLabel#SideSub {{ color: {t['side_muted']}; font-size: 9pt; }}
    #ModernSide QLabel#NavGroup {{ color: {t['side_muted']}; font-size: 9pt; font-weight: bold;
        padding: 14px 12px 4px 0; }}
    QPushButton#NavItem {{ color: {t['side_text']}; background: transparent; border: 1px solid transparent;
        border-radius: 8px; padding: 8px 12px; text-align: right; min-height: 22px; }}
    QPushButton#NavItem:hover {{ background: {t['side_hover']}; }}
    QPushButton#NavItem:focus {{ border-color: {t['focus']}; padding: 8px 12px; }}
    QPushButton#NavItem:checked {{ background: {t['side_active']}; color: {t['side_active_text']}; font-weight: bold; }}
    QPushButton#NavItem[collapsed="1"] {{ text-align: center; padding: 8px 4px; }}
    QLabel#Badge {{ background: #DC2626; color: white; border-radius: 9px; padding: 1px 7px; font-size: 8.5pt;
        font-weight: bold; min-width: 10px; }}
    QLabel#Badge[warn="0"] {{ background: #3E5559; }}
    #ContentHeader {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
    QLabel#HeaderTitle {{ font-size: 15pt; font-weight: bold; color: {t['text']}; }}
    #ContentHeader QLineEdit {{ min-width: 280px; border-radius: 17px; padding: 6px 14px; background: {t['surface2']}; }}
    #ContentHeader QLineEdit:focus {{ padding: 5px 13px; }}
    #ContentHeader QComboBox {{ border-radius: 15px; padding: 5px 12px; min-width: 210px; }}
    #ContentHeader QToolButton {{ border: 1px solid {t['border']}; border-radius: 15px; padding: 5px; }}
    #ContentHeader QToolButton:hover {{ background: {t['sel']}; }}
    QToolButton#Pill {{ border: 1px solid {t['border']}; border-radius: 14px; padding: 4px 14px; background: {t['surface']};
        color: {t['text']}; }}
    QToolButton#Pill:hover {{ border-color: {t['accent']}; }}
    QToolButton#Pill:checked {{ background: {t['accent']}; color: {t['accent_text']}; border-color: {t['accent']};
        font-weight: bold; }}
    QToolButton:focus {{ border: 2px solid {t['focus']}; }}
    #GridToolbar {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    #GridToolbar QToolButton {{ border: 1px solid transparent; border-radius: 7px; padding: 4px 8px; color: {t['text']};
        min-height: 22px; }}
    #GridToolbar QToolButton:hover {{ background: {t['sel']}; }}
    #GridToolbar QToolButton#Pill {{ border: 1px solid {t['border']}; border-radius: 14px; padding: 4px 14px; }}
    #GridToolbar QToolButton#Pill:checked {{ background: {t['accent']}; color: {t['accent_text']}; border-color: {t['accent']}; }}
    #GridToolbar QToolButton#ConfBadge[active="1"] {{ background: {t['bad']}; color: white; font-weight: bold;
        border-radius: 14px; padding: 4px 12px; }}
    #GridToolbar QFrame#VSep {{ background: {t['border']}; max-width: 1px; min-width: 1px; margin: 4px 4px; }}
    #InfoPanel {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    #TrayPanel {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 12px; }}
    #TrayPanel QListWidget {{ border: none; background: transparent; }}
    QLabel#PanelTitle {{ color: {t['muted']}; font-weight: bold; font-size: 9.5pt; }}

    /* ---------- نمط التركيز ---------- */
    /* ---------- الواجهة ج: شريط التنقل العلوي ---------- */
    #TopNav {{ background: {t['ribbon']}; }}
    #TopNav QLabel#TopTitle {{ color: white; font-weight: bold; font-size: 13pt; padding: 0 10px 0 16px; }}
    QPushButton#TopNavItem {{ color: {t['side_text']}; background: transparent; border: 1px solid transparent;
        border-radius: 8px; padding: 7px 12px; }}
    QPushButton#TopNavItem:hover {{ background: {t['side_hover']}; }}
    QPushButton#TopNavItem:checked {{ background: {t['side_active']}; color: {t['side_active_text']}; font-weight: bold; }}
    QPushButton#TopNavItem:focus {{ border-color: {t['focus']}; }}
    QPushButton#TopNavItem::menu-indicator {{ width: 0; }}
    #TopNav QLineEdit {{ background: rgba(255,255,255,0.10); color: white; border: 1px solid rgba(255,255,255,0.22);
        border-radius: 8px; padding: 5px 10px; min-width: 200px; }}
    #TopNav QComboBox {{ background: rgba(255,255,255,0.10); color: white; border: 1px solid rgba(255,255,255,0.22);
        border-radius: 8px; padding: 4px 10px; }}
    #TopNav QToolButton {{ color: white; border: 1px solid transparent; border-radius: 8px; padding: 4px; }}
    #TopNav QToolButton:hover {{ background: rgba(255,255,255,0.12); }}
    QToolButton#DayTab {{ border: 1px solid {t['border']}; border-radius: 8px; padding: 4px 10px; background: {t['surface']};
        color: {t['text']}; }}
    QToolButton#DayTab:checked {{ background: {t['accent']}; color: {t['accent_text']}; border-color: {t['accent']};
        font-weight: bold; }}
    /* ---------- الواجهة د: DPP الحديثة — الشريط العلوي ---------- */
    QLabel#Crumb {{ color: {t['muted']}; font-size: 9pt; }}
    QLabel#Crumb[cur="1"] {{ color: {t['text']}; font-weight: bold; }}
    QToolButton#HeadIcon {{ border: 1px solid {t['border']}; border-radius: 10px; padding: 6px;
        background: {t['surface']}; }}
    QToolButton#HeadIcon:hover {{ background: {t['surface2']}; border-color: {t['accent']}; }}
    QLabel#HeadBadge {{ background: {t['bad']}; color: white; border-radius: 8px; font-size: 8pt;
        font-weight: bold; padding: 0 4px; min-width: 9px; }}
    QToolButton#UserChip {{ border: 1px solid {t['border']}; border-radius: 10px; padding: 3px 10px 3px 6px;
        background: {t['surface']}; color: {t['text']}; font-weight: bold; }}
    QToolButton#UserChip:hover {{ border-color: {t['accent']}; }}
    QToolButton#UserChip::menu-indicator {{ width: 0; }}
    QLabel#Avatar {{ background: {t['accent']}; color: {t['accent_text']}; border-radius: 9px;
        font-weight: bold; font-size: 9pt; }}
    QFrame#HeadSep {{ background: {t['border']}; max-width: 1px; min-width: 1px; margin: 6px 2px; }}

    {_style_extra(t)}

    #FocusBar {{ background: #24262A; border-bottom: 1px solid #16171A; }}
    #FocusBar QLabel {{ color: #E8EAED; }}
    #FocusBar QLabel#FocusTitle {{ color: #5EEAD4; font-weight: bold; font-size: 12pt; padding: 0 6px; }}
    #FocusBar QLabel#FocusPage {{ color: #E8EAED; font-size: 11pt; }}
    #FocusBar QToolButton {{ color: #E8EAED; border: 1px solid #45484F; border-radius: 7px; padding: 4px 10px; }}
    #FocusBar QToolButton:hover {{ background: #33363C; }}
    #FocusBar QLineEdit {{ background: #1A1B1E; color: #E8EAED; border: 1px solid #45484F; border-radius: 7px;
        min-width: 220px; }}
    #FocusBar QComboBox {{ background: #1A1B1E; color: #E8EAED; border: 1px solid #45484F; border-radius: 7px; }}
    QDialog#Palette {{ background: {t['surface']}; border: 2px solid {t['accent']}; border-radius: 12px; }}
    QDialog#Palette QLineEdit {{ font-size: 12pt; padding: 8px 12px; }}
    QDialog#Palette QListWidget {{ border: none; }}
    QDialog#Palette QListWidget::item {{ padding: 7px; border-radius: 6px; }}
    QDialog#Palette QListWidget::item:selected {{ background: {t['sel']}; }}
    """


def _style_extra(t: dict) -> str:
    """لمسات خاصة بكل واجهة من الواجهات الثلاث (الزوايا، الحدود، القائمة)."""
    r = t.get("radius")
    if not r:
        return ""
    out = f"""
    QFrame#Card, #GridToolbar, #TrayPanel, #InfoPanel {{ border-radius: {r}; }}
    QPushButton {{ border-radius: {r if r != '12px' else '9px'}; }}
    """
    if t is LEDGER or t.get("side_bg") == LEDGER["side_bg"]:
        out += f"""
    QTableView, QTreeView, QTableWidget {{ border: 1px solid {t['text']}; border-radius: 2px; }}
    QHeaderView::section {{ border-bottom: 2px solid {t['text']}; }}
    QPushButton#NavItem:checked {{ border-right: 3px solid {t['accent']}; border-radius: 6px; }}
    #ModernSide {{ border-left: 1px solid {t['side_border']}; }}
    """
    if t.get("side_bg") == OPS["side_bg"] and t.get("accent") == OPS["accent"]:
        out += f"""
    QPushButton#NavItem[collapsed="1"] {{ padding: 10px 4px; border-radius: 10px; }}
    QPushButton#Primary, QPushButton#Cta {{ color: {t['accent_text']}; }}
    """
    if t is COMMAND or t is COMMAND_DARK:
        out += f"""
    QFrame#Card {{ border-radius: 14px; }}
    QFrame#Card:hover {{ border-color: {t['border']}; }}
    QLabel#CardValue {{ font-size: 20pt; color: {t['text']}; }}
    QPushButton {{ border-radius: 10px; padding: 7px 14px; }}
    QPushButton#Primary, QPushButton#Cta {{ border-radius: 10px; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit {{ border-radius: 10px; padding: 7px 10px; }}
    QGroupBox {{ border-radius: 14px; margin-top: 16px; padding-top: 12px; }}
    QGroupBox::title {{ padding: 0 10px; }}
    QTableView, QTreeView, QListView, QTableWidget {{ border-radius: 12px; }}
    QHeaderView::section {{ background: {t['header']}; color: {t['muted']}; border-left: none;
        border-bottom: 1px solid {t['border']}; padding: 8px 10px; }}
    QPushButton#NavItem {{ border-radius: 10px; padding: 9px 12px; }}
    QPushButton#NavItem:checked {{ border-right: 3px solid {t['accent']}; }}
    #ModernSide QLabel#NavGroup {{ padding: 15px 12px 5px 0; letter-spacing: 0.4px; }}
    #ContentHeader {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
    QLabel#HeaderTitle {{ font-size: 14.5pt; }}
    #ContentHeader QLineEdit {{ border-radius: 10px; min-width: 260px; background: {t['surface2']};
        border: 1px solid {t['border']}; }}
    #ContentHeader QComboBox {{ border-radius: 10px; }}
    #ContentHeader QToolButton {{ border-radius: 10px; }}
    QTabBar::tab {{ padding: 8px 16px; }}
    #TrayPanel, #InfoPanel, #GridToolbar {{ border-radius: 14px; }}
    """
    return out


_FONTS_LOADED = False


def load_fonts() -> str | None:
    """يحمّل خط Almarai (عربي + لاتيني) المضمّن مع البرنامج."""
    global _FONTS_LOADED
    from pathlib import Path
    import sys
    from PySide6.QtGui import QFontDatabase
    if _FONTS_LOADED:
        return "Almarai"
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    d = base / "dpp" / "assets" / "fonts"
    if not d.exists():
        d = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    ok = False
    for f in list(d.glob("Almarai-*.ttf")) + list(d.glob("Tajawal-*.ttf")) + list(d.glob("Cairo-*.ttf")):
        if QFontDatabase.addApplicationFont(str(f)) >= 0:
            ok = True
    _FONTS_LOADED = ok
    return "Almarai" if ok else None


def app_font(family: str | None = None) -> QFont:
    f = QFont()
    fam = load_fonts()
    if fam and family in dict(FONTS):
        fam = family
    f.setFamilies(([fam] if fam else []) + ["Segoe UI", "Tahoma", "Arial", "Noto Sans Arabic", "DejaVu Sans"])
    f.setPointSizeF(10.5)
    f.setHintingPreference(QFont.PreferFullHinting)
    return f


class _LtrNumbers(QObject):
    """حقول التاريخ والوقت والأرقام تبقى من اليسار إلى اليمين داخل واجهة RTL (حتى لا تنقلب 08:30 إلى 30:08)."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Polish:
            from PySide6.QtWidgets import QAbstractSpinBox, QCalendarWidget
            if isinstance(obj, QAbstractSpinBox) and not isinstance(obj, QCalendarWidget):
                obj.setLayoutDirection(Qt.LeftToRight)
        return False


_FILTER = None


def install_ltr_filter(app):
    global _FILTER
    if _FILTER is None:
        _FILTER = _LtrNumbers(app)
        app.installEventFilter(_FILTER)
