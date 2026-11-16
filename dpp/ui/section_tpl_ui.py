"""شاشة مراجعة القوالب الافتراضية للأقسام: أي قالب يأخذه كل قسم، كيف طوبق، وتصحيح المطابقة يدوياً."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHeaderView, QLabel, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..exporters import section_defaults as SD
from .widgets import icon

AUTO = "\x00auto"
HOW = {"exact": "مطابقة تامة", "approx": "تقريبية، راجعها", "manual": "اختيارك", "none": "لا قالب خاص"}
SOURCE = {"section": "قالب القسم", "level": "قالب الطور", "general": "القالب العام"}
COLS = ["القسم", "الطور", "القالب", "المطابقة", "الورق", "القاعة", "المقرر", "الحالة"]


class SectionTemplatesDialog(QDialog):
    """سطر لكل قسم. لا يُكتب شيء في قوالبك: الاختيار يُحفظ كإعداد ويمكن الرجوع عنه في أي وقت."""

    def __init__(self, db, formation_id=None, parent=None):
        super().__init__(parent)
        self.db, self.formation_id = db, formation_id
        self.changed = False
        self.setWindowTitle("القوالب الافتراضية للأقسام")
        self.resize(1280, 660)
        v = QVBoxLayout(self)
        head = QLabel(
            "هذه القوالب مستنتجة من أوراق البرنامج الأسبوعي للمؤسسة (39 ورقة): تصميم واحد مشترك هو "
            "<b>القالب العام</b>، ونصوص كل طور (<b>قالب الطور</b>) وكل قسم (<b>قالب القسم</b>: القاعة والمقرر). "
            "تُطبَّق تلقائياً تحت قوالبك؛ القسم الذي ليس له قالب يأخذ قالب طوره ثم القالب العام.")
        head.setWordWrap(True)
        v.addWidget(head)
        self.chk_on = QCheckBox("استعمال القوالب الافتراضية للمؤسسة")
        self.chk_on.setChecked(SD.enabled(db))
        self.chk_on.toggled.connect(self._toggle)
        v.addWidget(self.chk_on)
        self.sum_lbl = QLabel()
        self.sum_lbl.setObjectName("Muted")
        self.sum_lbl.setWordWrap(True)
        v.addWidget(self.sum_lbl)
        self.table = QTableWidget(0, len(COLS))
        self.table.setHorizontalHeaderLabels(COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        hh.setSectionResizeMode(2, QHeaderView.Fixed)
        self.table.setColumnWidth(2, 210)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.ElideMiddle)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.itemSelectionChanged.connect(self._show_flags)
        v.addWidget(self.table, 1)
        self.flag_lbl = QLabel()
        self.flag_lbl.setWordWrap(True)
        v.addWidget(self.flag_lbl)
        bb = QDialogButtonBox()
        self.b_auto = QPushButton(icon("mdi6.auto-fix"), "إرجاع الكل إلى المطابقة الآلية")
        self.b_auto.clicked.connect(self._all_auto)
        bb.addButton(self.b_auto, QDialogButtonBox.ResetRole)
        bb.addButton("إغلاق", QDialogButtonBox.AcceptRole)
        bb.accepted.connect(self.accept)
        v.addWidget(bb)
        self.fill()

    # ------------------------------------------------------------------ التعبئة
    def fill(self):
        self.rows = SD.overview(self.db, self.formation_id)
        on = SD.enabled(self.db)
        self.table.setEnabled(on)
        self.table.setRowCount(len(self.rows))
        for i, r in enumerate(self.rows):
            m, p = r["match"], r["props"]
            name = QTableWidgetItem(f"{r['short']} — {r['name']}" if r["short"] and r["short"] != r["name"] else r["name"])
            name.setToolTip(r["name"])
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, QTableWidgetItem(r["level_code"]))
            cb = QComboBox()
            cb.addItem("آلي (حسب الاسم)", AUTO)
            cb.addItem("بلا قالب قسم (قالب الطور أو العام)", "")
            for e in SD.entries():
                cb.addItem(f"{e['key']}  ·  {e['level'] or ''}", e["key"])
                cb.setItemData(cb.count() - 1, e["name"], Qt.ToolTipRole)
            cur = (m.entry["key"] if m.entry else "") if m.how == "manual" else AUTO
            cb.setCurrentIndex(max(0, cb.findData(cur)))
            cb.currentIndexChanged.connect(lambda _i, sid=r["id"], cb=cb: self._choose(sid, cb.currentData()))
            self.table.setCellWidget(i, 2, cb)
            how = SOURCE[m.source] + (f": {m.entry['key']}" if m.entry else "")
            how += f" — {HOW[m.how]}" + (f" ({m.score:.0%})" if m.how == "approx" else "")
            it = QTableWidgetItem(how)
            if m.how == "approx" or m.flags:
                it.setForeground(QColor("#B45309"))
                it.setIcon(icon("mdi6.alert-outline", "#B45309"))
            self.table.setItem(i, 3, it)
            self.table.setItem(i, 4, QTableWidgetItem("عنوان + جدول" if p.get("simple") else p.get("paper", "A4")))
            self.table.setItem(i, 5, QTableWidgetItem(p.get("room", "")))
            dec = f"{p['decree']} — {p.get('decree_date', '')}" if p.get("decree") else ""
            self.table.setItem(i, 6, QTableWidgetItem(dec))
            if not on:
                st = "القوالب الافتراضية معطّلة"
            elif r["applied"]:
                st = "مطبَّق" + (" (مع تعديلاتك المحفوظة)" if r["saved"] else "")
            else:
                st = "غير مطبَّق: للقسم تصميم محفوظ من قبل"
            self.table.setItem(i, 7, QTableWidgetItem(st))
            if on and not r["applied"] and m.mode != "off":
                b = QPushButton("طبّقه تحت تصميمي")
                b.setToolTip("يضع القالب الافتراضي تحت تصميمك المحفوظ: ما عدّلتَه يبقى كما هو والباقي يأخذ شكل الورقة الرسمية")
                b.clicked.connect(lambda _=False, sid=r["id"]: self._force(sid))
                self.table.setCellWidget(i, 7, b)
        c = SD.summary(self.rows)
        self.sum_lbl.setText(
            f"{len(self.rows)} قسماً: {c['section']} بقالب القسم، {c['level']} بقالب الطور، {c['general']} بالقالب العام"
            + (f" · {c['approx']} مطابقة تقريبية تحتاج مراجعة" if c["approx"] else "")
            + (f" · {c['flags']} قسماً عليه ملاحظة" if c["flags"] else "")
            + (f" · {c['custom']} قسماً له تصميم محفوظ" if c["custom"] else ""))
        self._show_flags()

    def _show_flags(self):
        i = self.table.currentRow()
        notes = []
        if 0 <= i < len(self.rows):
            notes = [f"• {x}" for x in self.rows[i]["match"].flags]
        else:
            for r in self.rows:
                notes += [f"• <b>{r['short'] or r['name']}</b>: {x}" for x in r["match"].flags]
        self.flag_lbl.setText("<b>ملاحظات على الأوراق الأصلية:</b><br>" + "<br>".join(notes) if notes else "")

    # ------------------------------------------------------------------ الأفعال
    def _toggle(self, on: bool):
        SD.set_enabled(self.db, on)
        self.changed = True
        self.fill()

    def _choose(self, section_id: int, key):
        SD.set_choice(self.db, section_id, None if key == AUTO else key,
                      (SD._choices(self.db).get(str(section_id)) or {}).get("mode"))
        self.changed = True
        self.fill()

    def _force(self, section_id: int):
        ch = SD._choices(self.db).get(str(section_id)) or {}
        SD.set_choice(self.db, section_id, ch.get("key"), "on")
        self.changed = True
        self.fill()

    def _all_auto(self):
        for r in self.rows:
            SD.set_choice(self.db, r["id"], None, None)
        self.changed = True
        self.fill()


def open_dialog(db, formation_id=None, parent=None) -> bool:
    """يفتح شاشة المراجعة ويعيد True إذا تغيّر شيء (فتُعاد المعاينة)."""
    dlg = SectionTemplatesDialog(db, formation_id, parent)
    dlg.exec()
    return dlg.changed
