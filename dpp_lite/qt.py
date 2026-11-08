"""طبقة توافق Qt: PySide2 (Qt 5) لويندوز 7، وPySide6 (Qt 6) للتطوير والتجربة.

النسخة الخفيفة تُبنى بـ PySide2 لأن Qt 6 أسقط دعم ويندوز 7 نهائياً، لكن نفس الشيفرة
تعمل بـ PySide6 حتى تُجرَّب وتُلتقط لها لقطات في بيئة التطوير.
"""
from __future__ import annotations

try:                                    # ويندوز 7: Qt 5
    from PySide2 import QtCore, QtGui, QtPrintSupport, QtWidgets
    QT5 = True
except ImportError:                     # التطوير: Qt 6
    from PySide6 import QtCore, QtGui, QtPrintSupport, QtWidgets
    QT5 = False

Qt = QtCore.Qt
Signal = QtCore.Signal
QDate = QtCore.QDate
QPoint = QtCore.QPoint
QRect = QtCore.QRect
QRectF = QtCore.QRectF
QSize = QtCore.QSize
QColor = QtGui.QColor
QFont = QtGui.QFont
QPainter = QtGui.QPainter
QPen = QtGui.QPen
QBrush = QtGui.QBrush
QPrinter = QtPrintSupport.QPrinter
QPrintDialog = QtPrintSupport.QPrintDialog

# QAction/QShortcut انتقلا من QtWidgets (Qt5) إلى QtGui (Qt6)
QAction = QtWidgets.QAction if QT5 else QtGui.QAction
QShortcut = QtWidgets.QShortcut if QT5 else QtGui.QShortcut
QKeySequence = QtGui.QKeySequence


def run(dlg):
    """تشغيل نافذة حوار (exec_ في Qt5، exec في Qt6)."""
    return dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()


def run_app(app):
    return app.exec_() if hasattr(app, "exec_") else app.exec()


def ev_pos(ev):
    """موضع حدث الفأرة كنقطة صحيحة في النسختين."""
    if QT5:
        return ev.pos()
    return ev.position().toPoint()


def ev_global(ev):
    """موضع الحدث على الشاشة (Qt5: globalPos، Qt6: globalPosition)."""
    if QT5:
        return ev.globalPos()
    return ev.globalPosition().toPoint()


def popup(menu, ev):
    return menu.exec_(ev_global(ev)) if hasattr(menu, "exec_") else menu.exec(ev_global(ev))


def set_landscape(printer):
    """الاتجاه الأفقي للطباعة في النسختين."""
    try:                                   # Qt 6
        from PySide6.QtGui import QPageLayout
        printer.setPageOrientation(QPageLayout.Landscape)
    except Exception:
        try:                               # Qt 5
            printer.setOrientation(QPrinter.Landscape)
        except Exception:
            pass


def text_width(fm, text: str) -> int:
    return fm.horizontalAdvance(text)


def set_hidpi():
    """تمكين التحجيم عالي الدقة (مطلوب صراحةً في Qt 5 فقط)."""
    if QT5:
        QtCore.QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
        QtCore.QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)


def page_rect(printer) -> QRectF:
    """مستطيل الصفحة القابل للرسم، بواجهة موحّدة بين Qt5 وQt6."""
    try:                                  # Qt 6
        return printer.pageLayout().paintRectPixels(printer.resolution())
    except AttributeError:                # Qt 5
        return printer.pageRect()
