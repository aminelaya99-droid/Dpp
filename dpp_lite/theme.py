"""ألوان النسخة الخفيفة وQSS — نسخة مستقلة عن `dpp.ui.theme` (الذي يستورد PySide6)."""
from __future__ import annotations

from .qt import QColor, QFont

T = {
    "bg": "#F4F6FA", "surface": "#FFFFFF", "surface2": "#F8FAFC", "border": "#E2E8F0",
    "text": "#0E1726", "muted": "#55657C", "accent": "#15803D", "accent_hover": "#166534",
    "sel": "#DCFCE7", "grid": "#E8EDF3", "header": "#F8FAFC", "lunch": "#FDF6E3",
    "bad": "#DC2626", "warn": "#B45309", "ok": "#15803D", "weekend": "#EEF2F7",
}

# ألوان أنواع المواد (نفس منطق النسخة الكاملة: درجة ثابتة لكل مادة داخل طيف نوعها)
KIND_BASE = {"military": "#C7E0B4", "specialty": "#BFD4F2", "general": "#F6DDB4"}


def subject_color(color: str | None, category: str | None) -> QColor:
    c = QColor(color) if color else QColor()
    if c.isValid() and color:
        return c
    return QColor(KIND_BASE.get(category or "specialty", "#D9E2EC"))


def text_on(c: QColor) -> QColor:
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return QColor("#0E1726") if lum > 0.55 else QColor("#FFFFFF")


def app_font(size: float = 10.0) -> QFont:
    f = QFont()
    fams = ["Almarai", "Segoe UI", "Tahoma", "Arial", "Noto Sans Arabic", "DejaVu Sans"]
    if hasattr(f, "setFamilies"):
        f.setFamilies(fams)
    else:                                   # Qt قديم جداً
        f.setFamily(fams[1])
    f.setPointSizeF(size)
    return f


def stylesheet() -> str:
    t = T
    return f"""
    QWidget {{ color: {t['text']}; }}
    QMainWindow, QDialog {{ background: {t['bg']}; }}
    QFrame#Bar {{ background: {t['surface']}; border-bottom: 1px solid {t['border']}; }}
    QFrame#Tray {{ background: {t['surface']}; border-top: 1px solid {t['border']}; }}
    QLabel#Title {{ font-size: 13pt; font-weight: bold; }}
    QLabel#Muted {{ color: {t['muted']}; }}
    QPushButton {{ background: {t['surface']}; border: 1px solid {t['border']}; border-radius: 8px;
        padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {t['accent']}; background: {t['surface2']}; }}
    QPushButton:disabled {{ color: {t['muted']}; background: {t['surface2']}; }}
    QPushButton#Primary {{ background: {t['accent']}; color: white; border-color: {t['accent']};
        font-weight: bold; }}
    QPushButton#Primary:hover {{ background: {t['accent_hover']}; }}
    QComboBox, QLineEdit, QSpinBox {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: 8px; padding: 5px 9px; }}
    QComboBox:focus, QLineEdit:focus {{ border: 2px solid {t['accent']}; padding: 4px 8px; }}
    QListWidget, QTableWidget {{ background: {t['surface']}; border: 1px solid {t['border']};
        border-radius: 10px; }}
    QStatusBar {{ background: {t['surface']}; border-top: 1px solid {t['border']}; color: {t['muted']}; }}
    QToolTip {{ background: {t['surface']}; color: {t['text']}; border: 1px solid {t['border']}; padding: 5px; }}
    QMenu {{ background: {t['surface']}; border: 1px solid {t['border']}; }}
    QMenu::item:selected {{ background: {t['sel']}; color: {t['text']}; }}
    """
