"""الشريط السفلي لبطاقات المواد.

- البطاقات بلا وقت (المدة تُختار بعد الوضع من قائمة الزر الأيمن: 30 د حتى 4 سا).
- البطاقة تعرض الاسم الكامل للمادة بلون نوعها.
- «بطاقة جديدة»: بطاقة إضافية (مادة + أستاذ مقترح اختياري)؛ غير المثبتة تخرج من الشريط بعد وضعها.
"""
from __future__ import annotations

import json

from PySide6.QtCore import QMimeData, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPen
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QListView, QListWidget,
                               QListWidgetItem, QMenu, QStyle, QStyledItemDelegate, QVBoxLayout, QWidget)

from dpp.models import SUBJECT_KINDS
from dpp.ui.planner.grid import MIME_CARD, card_pixmap
from dpp.ui.theme import T, subject_color, text_on
from dpp.ui.widgets import button

ROLE_PAYLOAD = Qt.UserRole + 1
ROLE_COLOR = Qt.UserRole + 2
ROLE_SUB = Qt.UserRole + 3


class CardDelegate(QStyledItemDelegate):
    def paint(self, p: QPainter, opt, idx) -> None:
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        col = idx.data(ROLE_COLOR) or QColor("#E5E7EB")
        r = QRectF(opt.rect).adjusted(3, 3, -3, -3)
        p.setBrush(col)
        sel = bool(opt.state & QStyle.State_Selected)
        p.setPen(QPen(QColor("#0F172A") if sel else col.darker(125), 2 if sel else 1))
        p.drawRoundedRect(r, 6, 6)
        payload = idx.data(ROLE_PAYLOAD) or {}
        if payload.get("pinned") is False:
            p.setPen(QPen(QColor("#0F172A"), 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(2, 2, -2, -2), 5, 5)
        p.setPen(text_on(col))
        f = QFont(opt.font)
        f.setBold(True)
        f.setPointSizeF(8.5)
        p.setFont(f)
        sub = idx.data(ROLE_SUB) or ""
        tr = r.adjusted(6, 3, -6, -(16 if sub else 3))
        p.drawText(tr, Qt.AlignCenter | Qt.TextWordWrap, idx.data(Qt.DisplayRole))
        if sub:
            f.setBold(False)
            f.setPointSizeF(7.5)
            p.setFont(f)
            p.drawText(r.adjusted(6, r.height() - 17, -6, -2), Qt.AlignCenter, sub)
        p.restore()

    def sizeHint(self, opt, idx) -> QSize:
        return QSize(150, 54)


class CardList(QListWidget):
    def __init__(self):
        super().__init__()
        self.setViewMode(QListView.IconMode)
        self.setFlow(QListView.TopToBottom)
        self.setWrapping(True)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setSpacing(2)
        self.setDragEnabled(True)
        self.setItemDelegate(CardDelegate(self))
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)

    def startDrag(self, _actions) -> None:
        it = self.currentItem()
        if not it:
            return
        payload = dict(it.data(ROLE_PAYLOAD))
        mime = QMimeData()
        mime.setData(MIME_CARD, json.dumps(payload).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(card_pixmap(it.text(), it.data(ROLE_COLOR)))
        drag.exec(Qt.CopyAction)


class Palette(QWidget):
    newCardRequested = Signal()
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.custom: list[dict] = []  # بطاقات إضافية
        self.subjects = []
        self.remaining: dict[int, float] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        lbl = QLabel("بطاقات المواد — اسحب البطاقة إلى الجدول، ثم اضغط بالزر الأيمن لاختيار المدة")
        lbl.setObjectName("Muted")
        bar.addWidget(lbl)
        bar.addStretch(1)
        self.kind = QComboBox()
        self.kind.addItem("كل الأنواع", None)
        for k, v in SUBJECT_KINDS.items():
            self.kind.addItem(v, k)
        self.kind.currentIndexChanged.connect(self.rebuild)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة…")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(self.rebuild)
        bar.addWidget(self.kind)
        bar.addWidget(self.search)
        bar.addWidget(button("بطاقة جديدة", self.newCardRequested.emit, primary=True))
        lay.addLayout(bar)
        self.list = CardList()
        self.list.setFixedHeight(128)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self.list)

    def set_subjects(self, subjects, remaining: dict[int, float] | None = None) -> None:
        self.subjects = subjects
        self.remaining = remaining or {}
        self.rebuild()

    def add_custom(self, subject, teacher=None, pinned: bool = False) -> None:
        import uuid
        self.custom.append({"key": uuid.uuid4().hex[:8], "subject_id": subject.id,
                            "teacher_id": teacher.id if teacher else None,
                            "teacher": teacher.display_name if teacher else "", "pinned": pinned,
                            "_subject": subject})
        self.rebuild()
        self.changed.emit()

    def consume(self, key: str | None) -> None:
        """البطاقة غير المثبتة تخرج من الشريط بعد وضعها."""
        if not key:
            return
        before = len(self.custom)
        self.custom = [c for c in self.custom if not (c["key"] == key and not c["pinned"])]
        if len(self.custom) != before:
            self.rebuild()
            self.changed.emit()

    def _menu(self, pos) -> None:
        it = self.list.itemAt(pos)
        if not it:
            return
        pl = it.data(ROLE_PAYLOAD)
        if not pl.get("key"):
            return
        m = QMenu(self)
        m.addAction("إلغاء التثبيت" if pl.get("pinned") else "تثبيت (تبقى بعد الوضع)",
                    lambda: self._toggle_pin(pl["key"]))
        m.addAction("حذف البطاقة", lambda: self._remove(pl["key"]))
        m.exec(self.list.viewport().mapToGlobal(pos))

    def _toggle_pin(self, key) -> None:
        for c in self.custom:
            if c["key"] == key:
                c["pinned"] = not c["pinned"]
        self.rebuild()

    def _remove(self, key) -> None:
        self.custom = [c for c in self.custom if c["key"] != key]
        self.rebuild()

    def rebuild(self) -> None:
        q = self.search.text().strip()
        kind = self.kind.currentData()
        self.list.clear()

        def ok(subj) -> bool:
            if kind and subj.kind != kind:
                return False
            return not q or q in subj.name or q in (subj.short_name or "")

        for c in self.custom:
            subj = c["_subject"]
            if ok(subj):
                self._add(subj, {k: v for k, v in c.items() if k != "_subject"},
                          c["teacher"] or "بطاقة إضافية")
        for subj in self.subjects:
            if ok(subj):
                rem = self.remaining.get(subj.id)
                sub = f"متبقٍ {rem:g} سا" if rem is not None else SUBJECT_KINDS.get(subj.kind, "")
                self._add(subj, {"subject_id": subj.id, "teacher_id": None, "key": None, "pinned": True}, sub)

    def _add(self, subj, payload, sub) -> None:
        it = QListWidgetItem(subj.name)
        it.setData(ROLE_PAYLOAD, payload)
        it.setData(ROLE_COLOR, subject_color(subj))
        it.setData(ROLE_SUB, sub)
        it.setToolTip(f"{subj.name}\n{SUBJECT_KINDS.get(subj.kind, '')}")
        self.list.addItem(it)
