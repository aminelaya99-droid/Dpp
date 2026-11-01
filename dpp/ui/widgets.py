"""مكونات واجهة مشتركة: رأس الصفحة، بطاقات، نافذة نموذج عامة، رسائل."""
from __future__ import annotations

import datetime as dt
from typing import Any

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QTimeEdit,
                               QVBoxLayout, QWidget)

from dpp.models import DAY_NAMES


class Page(QWidget):
    """صفحة في النافذة الرئيسية؛ refresh() تُستدعى عند الإظهار."""
    title = ""
    subtitle = ""

    def __init__(self, main=None):
        super().__init__()
        self.main = main
        self.setObjectName("Page")
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(20, 16, 20, 16)
        self.root.setSpacing(10)
        head = QHBoxLayout()
        box = QVBoxLayout()
        box.setSpacing(0)
        self.title_lbl = QLabel(self.title)
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(self.subtitle)
        self.sub_lbl.setObjectName("PageSubtitle")
        box.addWidget(self.title_lbl)
        box.addWidget(self.sub_lbl)
        head.addLayout(box)
        head.addStretch(1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(6)
        head.addLayout(self.actions)
        self.root.addLayout(head)

    @property
    def s(self):
        from dpp.db import get_session
        return get_session()

    def add_action(self, text: str, slot, primary: bool = False, danger: bool = False) -> QPushButton:
        b = button(text, slot, primary, danger)
        self.actions.addWidget(b)
        return b

    def refresh(self) -> None:  # pragma: no cover - تعيد الصفحات تعريفها
        pass


def button(text: str, slot=None, primary: bool = False, danger: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setCursor(Qt.PointingHandCursor)
    if primary:
        b.setObjectName("Primary")
    elif danger:
        b.setObjectName("Danger")
    if slot:
        b.clicked.connect(slot)
    return b


def card(layout_cls=QVBoxLayout) -> tuple[QFrame, Any]:
    f = QFrame()
    f.setObjectName("Card")
    lay = layout_cls(f)
    lay.setContentsMargins(14, 12, 14, 12)
    return f, lay


def stat_card(value: str, label: str) -> tuple[QFrame, QLabel]:
    f, lay = card()
    v = QLabel(value)
    v.setObjectName("StatValue")
    lbl = QLabel(label)
    lbl.setObjectName("StatLabel")
    lay.addWidget(v)
    lay.addWidget(lbl)
    return f, v


def info(parent, text: str, title: str = "معلومة") -> None:
    QMessageBox.information(parent, title, text)


def warn(parent, text: str, title: str = "تنبيه") -> None:
    QMessageBox.warning(parent, title, text)


def confirm(parent, text: str, title: str = "تأكيد") -> bool:
    box = QMessageBox(QMessageBox.Question, title, text, parent=parent)
    yes = box.addButton("نعم", QMessageBox.YesRole)
    box.addButton("لا", QMessageBox.NoRole)
    box.exec()
    return box.clickedButton() is yes


class FormDialog(QDialog):
    """نافذة نموذج عامة.

    fields: قائمة (key, label, type, value, options) حيث type في:
    text, int, float, date, time, combo, check, days, multiline, password
    """

    def __init__(self, title: str, fields: list[tuple], parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self.widgets: dict[str, Any] = {}
        self.types: dict[str, str] = {}
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        for f in fields:
            key, label, typ = f[0], f[1], f[2]
            value = f[3] if len(f) > 3 else None
            opts = f[4] if len(f) > 4 else None
            w = self._make(typ, value, opts)
            self.widgets[key] = w
            self.types[key] = typ
            form.addRow(label, w)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Ok).setObjectName("Primary")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _make(self, typ, value, opts):
        if typ in ("text", "password"):
            w = QLineEdit("" if value is None else str(value))
            if typ == "password":
                w.setEchoMode(QLineEdit.Password)
            return w
        if typ == "multiline":
            w = QPlainTextEdit("" if value is None else str(value))
            w.setFixedHeight(80)
            return w
        if typ == "int":
            w = QSpinBox()
            lo, hi = opts or (0, 100000)
            w.setRange(lo, hi)
            w.setValue(int(value or 0))
            return w
        if typ == "float":
            w = QDoubleSpinBox()
            w.setRange(0, 100000)
            w.setDecimals(1)
            w.setValue(float(value or 0))
            return w
        if typ == "date":
            w = QDateEdit()
            w.setCalendarPopup(True)
            w.setDisplayFormat("dd/MM/yyyy")
            d = value or dt.date.today()
            w.setDate(QDate(d.year, d.month, d.day))
            return w
        if typ == "time":
            w = QTimeEdit()
            w.setDisplayFormat("HH:mm")
            m = int(value or 0)
            w.setTime(QTime(m // 60, m % 60))
            return w
        if typ == "combo":
            w = QComboBox()
            for data, text in opts or []:
                w.addItem(text, data)
            idx = w.findData(value)
            if idx >= 0:
                w.setCurrentIndex(idx)
            return w
        if typ == "check":
            w = QCheckBox()
            w.setChecked(bool(value))
            return w
        if typ == "days":
            w = QWidget()
            h = QHBoxLayout(w)
            h.setContentsMargins(0, 0, 0, 0)
            w.boxes = []
            for i, n in enumerate(DAY_NAMES):
                cb = QCheckBox(n)
                cb.setChecked(i in (value or []))
                h.addWidget(cb)
                w.boxes.append(cb)
            return w
        raise ValueError(typ)

    def values(self) -> dict[str, Any]:
        out = {}
        for k, w in self.widgets.items():
            t = self.types[k]
            if t in ("text", "password"):
                out[k] = w.text().strip()
            elif t == "multiline":
                out[k] = w.toPlainText().strip()
            elif t in ("int", "float"):
                out[k] = w.value()
            elif t == "date":
                q = w.date()
                out[k] = dt.date(q.year(), q.month(), q.day())
            elif t == "time":
                q = w.time()
                out[k] = q.hour() * 60 + q.minute()
            elif t == "combo":
                out[k] = w.currentData()
            elif t == "check":
                out[k] = w.isChecked()
            elif t == "days":
                out[k] = [i for i, cb in enumerate(w.boxes) if cb.isChecked()]
        return out


def ask_form(parent, title: str, fields: list[tuple]) -> dict | None:
    d = FormDialog(title, fields, parent)
    if d.exec() == QDialog.Accepted:
        return d.values()
    return None
