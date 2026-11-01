"""الهوية البصرية: رموز الألوان، الخطوط، وQSS للتطبيق."""
from __future__ import annotations

import colorsys
import hashlib

from PySide6.QtGui import QColor, QFont

# رموز الألوان (semantic tokens)
T = {
    "sidebar": "#0F172A",
    "sidebar_hover": "#1E293B",
    "sidebar_text": "#CBD5E1",
    "sidebar_active_text": "#FFFFFF",
    "accent": "#15803D",
    "accent_hover": "#166534",
    "accent_soft": "#DCFCE7",
    "bg": "#F1F5F9",
    "card": "#FFFFFF",
    "border": "#E2E8F0",
    "border_strong": "#CBD5E1",
    "text": "#0F172A",
    "muted": "#64748B",
    "danger": "#DC2626",
    "danger_soft": "#FEE2E2",
    "warning": "#D97706",
    "warning_soft": "#FEF3C7",
    "info": "#2563EB",
    "lunch": "#FDF6E3",
    "weekend": "#E2E8F0",
    "grid": "#E2E8F0",
    "grid_strong": "#94A3B8",
}

FONT_FAMILY = "Segoe UI"
FALLBACK_FONTS = ["Segoe UI", "Tahoma", "Arial", "Noto Sans Arabic", "DejaVu Sans"]

# أطياف الألوان حسب نوع المادة (الصبغة الأساسية، تشبع)
KIND_HUES = {
    "military": (0.33, 0.45),     # أخضر عسكري
    "specialized": (0.60, 0.55),  # أزرق
    "general": (0.09, 0.70),      # برتقالي/كهرماني
}
KIND_BASE = {"military": "#4D7C0F", "specialized": "#1D4ED8", "general": "#B45309"}


def app_font(size: int = 10) -> QFont:
    f = QFont()
    f.setFamilies(FALLBACK_FONTS)
    f.setPointSize(size)
    return f


def subject_color(subject) -> QColor:
    """لون المادة: لونها الخاص إن وُجد، وإلا درجة ثابتة من طيف نوعها."""
    if subject is None:
        return QColor("#E5E7EB")
    if getattr(subject, "color", ""):
        c = QColor(subject.color)
        if c.isValid():
            return c
    hue, sat = KIND_HUES.get(subject.kind, (0.0, 0.0))
    h = int(hashlib.md5(subject.name.encode("utf-8")).hexdigest()[:6], 16)
    hue = (hue + ((h % 9) - 4) * 0.012) % 1.0
    light = 0.80 + ((h >> 4) % 6) * 0.022
    r, g, b = colorsys.hls_to_rgb(hue, light, sat)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


def text_on(color: QColor) -> QColor:
    lum = 0.2126 * color.redF() + 0.7152 * color.greenF() + 0.0722 * color.blueF()
    return QColor("#0F172A") if lum > 0.55 else QColor("#FFFFFF")


def stylesheet() -> str:
    t = T
    return f"""
* {{ font-family: "Segoe UI", "Tahoma", "Arial"; }}
QMainWindow, QDialog {{ background: {t['bg']}; color: {t['text']}; }}
QWidget#Page {{ background: {t['bg']}; }}
QFrame#Sidebar {{ background: {t['sidebar']}; }}
QLabel#Brand {{ color: white; font-size: 18pt; font-weight: 700; padding: 16px 12px 2px 12px; }}
QLabel#BrandSub {{ color: {t['sidebar_text']}; font-size: 8.5pt; padding: 0 12px 12px 12px; }}
QListWidget#Nav {{ background: transparent; border: none; color: {t['sidebar_text']};
    font-size: 10.5pt; outline: 0; }}
QListWidget#Nav::item {{ padding: 9px 14px; margin: 1px 8px; border-radius: 6px; }}
QListWidget#Nav::item:hover {{ background: {t['sidebar_hover']}; color: white; }}
QListWidget#Nav::item:selected {{ background: {t['accent']}; color: white; }}
QLabel#PageTitle {{ font-size: 16pt; font-weight: 700; color: {t['text']}; }}
QLabel#PageSubtitle {{ color: {t['muted']}; }}
QLabel#Muted {{ color: {t['muted']}; }}
QFrame#Card {{ background: {t['card']}; border: 1px solid {t['border']}; border-radius: 8px; }}
QLabel#StatValue {{ font-size: 20pt; font-weight: 700; color: {t['text']}; }}
QLabel#StatLabel {{ color: {t['muted']}; }}
QPushButton {{ background: {t['card']}; border: 1px solid {t['border_strong']}; border-radius: 6px;
    padding: 6px 12px; color: {t['text']}; min-height: 20px; }}
QPushButton:hover {{ background: #F8FAFC; border-color: {t['grid_strong']}; }}
QPushButton:pressed {{ background: {t['border']}; }}
QPushButton:disabled {{ color: #94A3B8; background: #F8FAFC; }}
QPushButton#Primary {{ background: {t['accent']}; color: white; border: 1px solid {t['accent']}; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {t['accent_hover']}; }}
QPushButton#Danger {{ background: {t['card']}; color: {t['danger']}; border: 1px solid #FCA5A5; }}
QPushButton#Danger:hover {{ background: {t['danger_soft']}; }}
QPushButton:focus, QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDateEdit:focus, QTimeEdit:focus {{
    border: 1px solid {t['accent']}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateEdit, QTimeEdit, QTextEdit, QPlainTextEdit {{
    background: white; border: 1px solid {t['border_strong']}; border-radius: 6px; padding: 4px 8px;
    min-height: 20px; selection-background-color: {t['accent']}; }}
QTreeWidget, QTreeView, QTableWidget, QTableView, QListWidget {{ background: white; border: 1px solid {t['border']};
    border-radius: 6px; alternate-background-color: #F8FAFC; gridline-color: {t['border']};
    selection-background-color: {t['accent_soft']}; selection-color: {t['text']}; }}
QTreeView::item, QTableView::item {{ padding: 3px 4px; min-height: 22px; }}
QHeaderView::section {{ background: #F8FAFC; border: none; border-bottom: 1px solid {t['border']};
    border-left: 1px solid {t['border']}; padding: 6px; font-weight: 600; color: {t['muted']}; }}
QTabWidget::pane {{ border: 1px solid {t['border']}; border-radius: 6px; background: white; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 7px 14px; color: {t['muted']}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {t['text']}; border-bottom: 2px solid {t['accent']}; font-weight: 600; }}
QGroupBox {{ border: 1px solid {t['border']}; border-radius: 8px; margin-top: 14px; padding-top: 8px; background: white; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top right; padding: 0 8px; color: {t['muted']}; font-weight: 600; }}
QToolTip {{ background: {t['sidebar']}; color: white; border: none; padding: 6px; }}
QMenu {{ background: white; border: 1px solid {t['border_strong']}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {t['accent_soft']}; color: {t['text']}; }}
QMenu::separator {{ height: 1px; background: {t['border']}; margin: 4px 6px; }}
QStatusBar {{ background: white; border-top: 1px solid {t['border']}; color: {t['muted']}; }}
QScrollBar:vertical {{ width: 10px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #CBD5E1; border-radius: 5px; min-height: 24px; }}
QScrollBar:horizontal {{ height: 10px; background: transparent; }}
QScrollBar::handle:horizontal {{ background: #CBD5E1; border-radius: 5px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QLabel#Badge {{ background: {t['warning_soft']}; color: #92400E; border-radius: 9px; padding: 2px 8px; }}
QLabel#BadgeDanger {{ background: {t['danger_soft']}; color: #991B1B; border-radius: 9px; padding: 2px 8px; }}
QLabel#BadgeOk {{ background: {t['accent_soft']}; color: #166534; border-radius: 9px; padding: 2px 8px; }}
"""
