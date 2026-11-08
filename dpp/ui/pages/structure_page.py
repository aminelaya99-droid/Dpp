"""مخطط التكوين: شجرة التنظيم (تكوين ← شهادة ← سنة/طور ← اختصاص ← أقسام) ومراحل التكوين بالأسابيع."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget, QLineEdit)

from ...services import formation_tree as FT
from .. import theme
from ..widgets import FormDialog, confirm, error, icon, info, page_title

KIND_ICONS = {"formation": "mdi6.school-outline", "certificate": "mdi6.certificate-outline",
              "level": "mdi6.layers-outline", "specialty": "mdi6.briefcase-outline", "section": "mdi6.google-classroom"}


class _Tree(QTreeWidget):
    """شجرة تقبل سحب قسم وإفلاته على اختصاص (أو طور) لتغيير انتمائه."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)

    def dropEvent(self, e):
        target = self.itemAt(e.position().toPoint())
        src = self.currentItem()
        e.ignore()
        if not target or not src:
            return
        s, t = src.data(0, Qt.UserRole), target.data(0, Qt.UserRole)
        if not s or not t or s["kind"] != "section" or t["kind"] not in ("specialty", "level"):
            info(self, "اسحب قسماً وأفلته على اختصاص (أو على طور) لنقله إليه.")
            return
        self.page.move_section(s, t)


class StructurePage(QWidget):
    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.db = ctx.db
        FT.ensure_defaults(self.db)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.addWidget(page_title("مخطط التكوين",
                                 "التنظيم كشجرة: التكوين ← الشهادة ← السنة (الطور) ← الاختصاص ← الأقسام. "
                                 "اسحب قسماً إلى اختصاص آخر لتغيير انتمائه، وانقر مرتين على أي فرع لتعديله."))
        bar = QHBoxLayout()
        acts = [("mdi6.plus", "إضافة تحت المحدد", self.add), ("mdi6.pencil", "تعديل", self.edit),
                ("mdi6.delete-outline", "حذف", self.delete), (None, None, None),
                ("mdi6.table-large", "فتح الجدول", self.open_master), ("mdi6.chart-donut", "فتح التقدم", self.open_progress),
                (None, None, None), ("mdi6.printer-outline", "طباعة المخطط", self.print_tree),
                ("mdi6.arrow-expand-all", "توسيع الكل", lambda: self.tree.expandAll()),
                ("mdi6.arrow-collapse-all", "طيّ الكل", lambda: self.tree.collapseToDepth(1))]
        for ic, lab, fn in acts:
            if ic is None:
                sep = QFrame()
                sep.setFrameShape(QFrame.VLine)
                bar.addWidget(sep)
                continue
            b = QPushButton(icon(ic), lab)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch()
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث في الشجرة…")
        self.search.textChanged.connect(self._filter)
        bar.addWidget(self.search)
        lay.addLayout(bar)
        split = QSplitter(Qt.Horizontal)
        self.tree = _Tree(self)
        self.tree.setHeaderLabels(["الفرع", "الأقسام", "مواد مقررة", "ساعات مقررة", "نوع التربص / المدة"])
        self.tree.setAlternatingRowColors(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.edit())
        self.tree.currentItemChanged.connect(lambda *_: self._sync_phases())
        split.addWidget(self.tree)
        split.addWidget(self._phases_panel())
        split.setSizes([900, 420])
        lay.addWidget(split, 1)
        ctx.data_changed.connect(lambda w: self.refresh() if w in ("*", "sections", "levels", "specialties",
                                                                     "formations", "curriculum") else None)
        self.refresh()

    # ------------------------------------------------------------------ الشجرة
    def refresh(self):
        expanded = {self._key(it) for it in self._all_items() if it.isExpanded()}
        cur = self._key(self.tree.currentItem()) if self.tree.currentItem() else None
        self.tree.clear()
        bold = QFont(self.font())
        bold.setBold(True)
        t = theme.CURRENT
        first = not expanded
        for f in FT.tree(self.db):
            nsec = sum(len(sp["sections"]) for c in f["certificates"] for lv in c["levels"] for sp in lv["specialties"])
            fi = self._item(None, {"kind": "formation", "id": f["id"]}, f["name"], [str(nsec), "", "",
                            f"{f['start'] or ''} ← {f['end'] or ''}"], bold)
            for c in f["certificates"]:
                parent = fi
                if c["name"]:
                    n = sum(len(sp["sections"]) for lv in c["levels"] for sp in lv["specialties"])
                    parent = self._item(fi, {"kind": "certificate", "name": c["name"], "formation": f["id"]},
                                        c["name"], [str(n), "", "", ""], bold)
                for lv in c["levels"]:
                    year = FT.YEAR_LABELS.get(lv["year"] or 0)
                    title = f"{year}: {lv['code']} — {lv['name']}" if year else f"{lv['code']} — {lv['name']}"
                    n = sum(len(sp["sections"]) for sp in lv["specialties"])
                    li = self._item(parent, {"kind": "level", "id": lv["id"], "formation": f["id"]}, title,
                                    [str(n), "", "", ""])
                    li.setForeground(0, QBrush(QColor(lv["color"])))
                    for sp in lv["specialties"]:
                        intern = (f"{sp['internship'] or ''} · {sp['weeks']} أسبوع" if sp["weeks"] else
                                  (sp["internship"] or ""))
                        si = self._item(li, {"kind": "specialty", "id": sp["id"], "level": lv["id"],
                                             "formation": f["id"]}, sp["name"],
                                        [str(len(sp["sections"])), str(sp["subjects"] or "—"),
                                         f"{sp['hours']:g}" if sp["hours"] else "—", intern.strip(" ·")])
                        if not sp["id"]:
                            si.setForeground(0, QBrush(QColor(t["warn"])))
                            si.setToolTip(0, "أقسام بلا اختصاص: لا يُعرف مقررها — اسحبها إلى اختصاصها")
                        elif not sp["subjects"]:
                            si.setForeground(2, QBrush(QColor(t["warn"])))
                            si.setToolTip(2, "لا يوجد مقرر لهذا الاختصاص")
                        for s in sp["sections"]:
                            self._item(si, {"kind": "section", "id": s["id"], "level": lv["id"],
                                            "specialty": sp["id"], "formation": f["id"]},
                                       f"{s['short']}" + (f"  ({s['name']})" if s["name"] and s["name"] != s["short"] else ""),
                                       ["", "", "", ""])
        for it in self._all_items():
            if self._key(it) in expanded or (first and it.data(0, Qt.UserRole)["kind"] in ("formation", "certificate")):
                it.setExpanded(True)
            if cur and self._key(it) == cur:
                self.tree.setCurrentItem(it)
        self.tree.resizeColumnToContents(1)
        self._filter()

    def _item(self, parent, data, text, cols, font=None):
        it = QTreeWidgetItem([text] + cols)
        it.setData(0, Qt.UserRole, data)
        it.setIcon(0, icon(KIND_ICONS[data["kind"]]))
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if data["kind"] == "section":
            flags |= Qt.ItemIsDragEnabled
        if data["kind"] in ("specialty", "level"):
            flags |= Qt.ItemIsDropEnabled
        it.setFlags(flags)
        for k in range(1, 4):
            it.setTextAlignment(k, Qt.AlignCenter)
        if font:
            it.setFont(0, font)
        (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
        return it

    def _all_items(self):
        out = []

        def walk(it):
            out.append(it)
            for i in range(it.childCount()):
                walk(it.child(i))
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        return out

    @staticmethod
    def _key(it):
        if not it:
            return None
        d = it.data(0, Qt.UserRole)
        return (d["kind"], d.get("id"), d.get("name"), d.get("level"))

    def _filter(self, *_):
        q = self.search.text().strip()
        for it in self._all_items():
            it.setHidden(False)
        if not q:
            return

        def visible(it) -> bool:
            show = q in it.text(0)
            for i in range(it.childCount()):
                show = visible(it.child(i)) or show
            it.setHidden(not show)
            if show:
                it.setExpanded(True)
            return show
        for i in range(self.tree.topLevelItemCount()):
            visible(self.tree.topLevelItem(i))

    def current(self) -> dict | None:
        it = self.tree.currentItem()
        return it.data(0, Qt.UserRole) if it else None

    # ------------------------------------------------------------------ تعديل
    def add(self):
        d = self.current()
        if not d:
            info(self, "اختر فرعاً لتضيف تحته: طوراً تحت التكوين أو الشهادة، اختصاصاً تحت الطور، قسماً تحت الاختصاص.")
            return
        db = self.db
        if d["kind"] in ("formation", "certificate"):
            dlg = FormDialog(self, "طور / سنة جديدة", [("code", "الرمز", "text", None), ("name", "الاسم", "text", None),
                                                        ("certificate", "الشهادة", "text", None),
                                                        ("year_no", "السنة (0 = بلا سنة)", "int", (0, 5))],
                             {"certificate": d.get("name", "")}, required=("code", "name"))
            if dlg.exec():
                v = dlg.values()
                with db.tx():
                    db.insert("levels", formation_id=d.get("id") if d["kind"] == "formation" else d["formation"],
                              code=v["code"], name=v["name"], short=v["code"], full_name=v["name"],
                              certificate=v["certificate"] or None, year_no=v["year_no"] or None, sort=99)
        elif d["kind"] == "level":
            dlg = FormDialog(self, "اختصاص جديد", [("name", "الاسم", "text", None),
                                                  ("internship", "نوع التربص", "text", None),
                                                  ("weeks", "مدة التكوين التخصصي (أسابيع)", "int", (0, 60))],
                             {}, required=("name",))
            if dlg.exec():
                v = dlg.values()
                with db.tx():
                    db.insert("specialties", level_id=d["id"], name=v["name"], short=v["name"][:20],
                              internship=v["internship"] or None, weeks=v["weeks"])
        elif d["kind"] == "specialty" and d.get("id"):
            dlg = FormDialog(self, "قسم جديد", [("short", "الاسم المختصر", "text", None),
                                               ("name", "الاسم الكامل", "text", None)], {}, required=("short",))
            if dlg.exec():
                v = dlg.values()
                with db.tx():
                    sid = db.insert("sections", formation_id=d["formation"], level_id=d["level"], specialty_id=d["id"],
                                    short=v["short"], name=v["name"] or v["short"])
                    db.insert("groups_", section_id=sid, name="الفوج الكامل", short="ALL", is_whole=1, size=0)
        else:
            info(self, "لا يُضاف شيء تحت القسم. اختر الاختصاص لإضافة قسم.")
            return
        self.ctx.changed("sections")

    def edit(self):
        d = self.current()
        if not d:
            return
        db = self.db
        if d["kind"] == "formation":
            r = db.one("SELECT * FROM formations WHERE id=?", (d["id"],))
            dlg = FormDialog(self, "التكوين", [("name", "الاسم", "text", None), ("start_date", "البداية", "date", None),
                                               ("end_date", "النهاية", "date", None)], dict(r), required=("name",))
            if dlg.exec():
                v = dlg.values()
                with db.tx():
                    db.update("formations", d["id"], name=v["name"], start_date=v["start_date"], end_date=v["end_date"])
        elif d["kind"] == "certificate":
            dlg = FormDialog(self, "الشهادة", [("name", "اسم الشهادة", "text", None)], {"name": d["name"]})
            if dlg.exec():
                with db.tx():
                    db.execute("UPDATE levels SET certificate=? WHERE formation_id=? AND certificate=?",
                               (dlg.values()["name"] or None, d["formation"], d["name"]))
        elif d["kind"] == "level":
            r = db.one("SELECT * FROM levels WHERE id=?", (d["id"],))
            dlg = FormDialog(self, "الطور / السنة", [("name", "الاسم", "text", None),
                                                     ("certificate", "الشهادة", "text", None),
                                                     ("year_no", "السنة (0 = بلا سنة)", "int", (0, 5))],
                             {"name": r["name"], "certificate": r["certificate"] or "", "year_no": r["year_no"] or 0})
            if dlg.exec():
                v = dlg.values()
                with db.tx():
                    db.update("levels", d["id"], name=v["name"], certificate=v["certificate"] or None,
                              year_no=v["year_no"] or None)
        elif d["kind"] == "specialty" and d.get("id"):
            r = db.one("SELECT * FROM specialties WHERE id=?", (d["id"],))
            dlg = FormDialog(self, "الاختصاص", [("name", "الاسم", "text", None),
                                                ("internship", "نوع التربص", "text", None),
                                                ("weeks", "مدة التكوين التخصصي (أسابيع، 0 = حسب المراحل)", "int", (0, 60))],
                             {"name": r["name"], "internship": r["internship"] or "", "weeks": r["weeks"] or 0},
                             required=("name",))
            if dlg.exec():
                v = dlg.values()
                with db.tx():
                    db.update("specialties", d["id"], name=v["name"], internship=v["internship"] or None,
                              weeks=v["weeks"])
        elif d["kind"] == "section":
            r = db.one("SELECT * FROM sections WHERE id=?", (d["id"],))
            dlg = FormDialog(self, "القسم", [("short", "الاسم المختصر", "text", None), ("name", "الاسم الكامل", "text", None)],
                             dict(r), required=("short",))
            if dlg.exec():
                v = dlg.values()
                with db.tx():
                    db.update("sections", d["id"], short=v["short"], name=v["name"] or v["short"])
        else:
            return
        self.ctx.changed("sections")

    def delete(self):
        d = self.current()
        if not d:
            return
        db = self.db
        if d["kind"] == "section":
            n = FT.section_impact(db, d["id"])["sessions"]
            if not confirm(self, f"حذف القسم نهائياً؟\nسيُحذف معه {n} حصة من جداوله." if n else "حذف القسم؟", danger=True):
                return
            with db.tx():
                db.execute("DELETE FROM sections WHERE id=?", (d["id"],))
                db.log("حذف قسم", "sections", d["id"])
        elif d["kind"] == "specialty" and d.get("id"):
            n = db.scalar("SELECT COUNT(*) FROM sections WHERE specialty_id=?", (d["id"],), 0)
            if not confirm(self, f"حذف الاختصاص؟\nأقسامه ({n}) تبقى «بلا اختصاص» ولا تُحذف، ومقرره يبقى محفوظاً.",
                           danger=True):
                return
            with db.tx():
                db.execute("UPDATE sections SET specialty_id=NULL WHERE specialty_id=?", (d["id"],))
                db.execute("DELETE FROM specialties WHERE id=?", (d["id"],))
                db.log("حذف اختصاص", "specialties", d["id"])
        elif d["kind"] == "level":
            n = db.scalar("SELECT COUNT(*) FROM sections WHERE level_id=?", (d["id"],), 0)
            if n:
                error(self, f"لا يُحذف طور فيه أقسام ({n}). انقل أقسامه أو احذفها أولاً.")
                return
            if confirm(self, "حذف هذا الطور الفارغ؟", danger=True):
                with db.tx():
                    db.execute("DELETE FROM levels WHERE id=?", (d["id"],))
        else:
            info(self, "يُحذف التكوين من صفحة «التكوينات»، والشهادة بتفريغ اسمها من أطوارها.")
            return
        self.ctx.changed("sections")

    def move_section(self, s: dict, t: dict):
        level = t["id"] if t["kind"] == "level" else t["level"]
        spec = t["id"] if t["kind"] == "specialty" else None
        if s.get("specialty") == spec and s.get("level") == level:
            return
        n = FT.section_impact(self.db, s["id"])["sessions"]
        name = self.db.scalar("SELECT short FROM sections WHERE id=?", (s["id"],))
        to = self.db.scalar("SELECT name FROM specialties WHERE id=?", (spec,)) if spec else "بلا اختصاص"
        msg = f"نقل القسم «{name}» إلى «{to}»؟"
        if n:
            msg += f"\n\nللقسم {n} حصة: تبقى كما هي، لكن مقرره وتقدمه يُحسبان من الآن حسب الاختصاص الجديد."
        if confirm(self, msg):
            FT.move_section(self.db, s["id"], level, spec)
            self.ctx.changed("sections")

    def open_master(self):
        d = self.current()
        if d and d["kind"] == "section":
            self.ctx.navigate.emit("master", ("section", d["id"]))
        else:
            self.ctx.navigate.emit("master", None)

    def open_progress(self):
        d = self.current()
        self.ctx.navigate.emit("progress", None)
        if d and d["kind"] == "section":
            win = self.window()
            pg = getattr(win, "pages", {}).get("progress")
            if pg:
                pg.select_section(d["id"])

    def print_tree(self):
        from PySide6.QtGui import QPageLayout, QPageSize, QPainter, QTextDocument
        from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
        rows = []
        for it in self._all_items():
            depth, p = 0, it.parent()
            while p:
                depth, p = depth + 1, p.parent()
            d = it.data(0, Qt.UserRole)
            style = "font-weight:bold;" if d["kind"] in ("formation", "certificate", "level") else ""
            extra = " · ".join(x for x in (it.text(1) and f"{it.text(1)} قسم", it.text(4)) if x)
            rows.append(f"<div style='margin-right:{depth * 22}px;{style}'>{it.text(0)}"
                        + (f" <span style='color:#666'>({extra})</span>" if extra and d["kind"] != "section" else "")
                        + "</div>")
        html = ("<html dir='rtl'><body style='font-family:Almarai,Tahoma;font-size:10pt'>"
                "<h2 style='text-align:center'>مخطط التكوين</h2>" + "".join(rows) + "</body></html>")
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        printer.setPageOrientation(QPageLayout.Portrait)
        doc = QTextDocument()
        doc.setHtml(html)
        dlg = QPrintPreviewDialog(printer, self)
        dlg.setWindowTitle("معاينة طباعة مخطط التكوين")
        dlg.paintRequested.connect(lambda pr: doc.print_(pr))
        dlg.resize(900, 900)
        dlg.exec()

    # ------------------------------------------------------------------ المراحل
    def _phases_panel(self) -> QWidget:
        w = QFrame()
        w.setObjectName("Card")
        v = QVBoxLayout(w)
        self.ph_title = QLabel("مراحل التكوين")
        self.ph_title.setObjectName("SectionTitle")
        v.addWidget(self.ph_title)
        hint = QLabel("مراحل التكوين بالأسابيع، بالترتيب. مدة «التكوين التخصصي» هنا افتراضية؛ "
                      "كل اختصاص يحدد مدته حسب نوع التربص (انقر الاختصاص مرتين في الشجرة).")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        v.addWidget(hint)
        self.ph = QTableWidget(0, 3)
        self.ph.setHorizontalHeaderLabels(["المرحلة", "الاسم", "الأسابيع"])
        self.ph.verticalHeader().setVisible(False)
        self.ph.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.ph.setColumnWidth(0, 170)
        self.ph.setColumnWidth(2, 110)
        v.addWidget(self.ph, 1)
        b = QHBoxLayout()
        for ic, lab, fn in (("mdi6.plus", "مرحلة", self._ph_add), ("mdi6.minus", "حذف", self._ph_del),
                            ("mdi6.arrow-up", "", lambda: self._ph_move(-1)),
                            ("mdi6.arrow-down", "", lambda: self._ph_move(1))):
            x = QPushButton(icon(ic), lab)
            x.clicked.connect(fn)
            b.addWidget(x)
        b.addStretch()
        save = QPushButton(icon("mdi6.content-save-outline"), "حفظ المراحل")
        save.setObjectName("Primary")
        save.clicked.connect(self._ph_save)
        b.addWidget(save)
        v.addLayout(b)
        self.preview = QLabel()
        self.preview.setObjectName("Muted")
        self.preview.setWordWrap(True)
        v.addWidget(self.preview)
        self.replace = QCheckBox("استبدال المخطط الزمني المستورد من Excel لهذه الأطوار")
        self.replace.setToolTip("المخطط المستورد هو المرجع؛ لا يُستبدل إلا إذا فعّلت هذا الخيار")
        v.addWidget(self.replace)
        gen = QPushButton(icon("mdi6.timeline-clock-outline"), "تطبيق المراحل على المخطط الزمني")
        gen.clicked.connect(self._ph_generate)
        v.addWidget(gen)
        self.ph_formation = None
        return w

    def _sync_phases(self):
        d = self.current()
        fid = d.get("formation", d.get("id")) if d else None
        if d and d["kind"] == "formation":
            fid = d["id"]
        if fid == self.ph_formation:
            self._preview()
            return
        self.ph_formation = fid
        name = self.db.scalar("SELECT name FROM formations WHERE id=?", (fid,), "") if fid else ""
        self.ph_title.setText(f"مراحل التكوين — {name}" if name else "مراحل التكوين")
        self.ph.setRowCount(0)
        for p in (FT.phases(self.db, fid) if fid else []):
            self._ph_row(p["kind"], p["label"], p["weeks"])
        self._preview()

    def _ph_row(self, kind="basic", label="", weeks=1):
        r = self.ph.rowCount()
        self.ph.insertRow(r)
        cb = QComboBox()
        for k, lab in FT.PHASE_KINDS.items():
            cb.addItem(lab, k)
        cb.setCurrentIndex(max(0, cb.findData(kind)))
        self.ph.setCellWidget(r, 0, cb)
        self.ph.setItem(r, 1, QTableWidgetItem(label or FT.PHASE_KINDS.get(kind, "")))
        sp = QSpinBox()
        sp.setRange(0, 60)
        sp.setValue(int(weeks))
        sp.setSuffix(" أسبوع")
        self.ph.setCellWidget(r, 2, sp)

    def _ph_rows(self):
        out = []
        for r in range(self.ph.rowCount()):
            out.append((self.ph.cellWidget(r, 0).currentData(), (self.ph.item(r, 1).text() if self.ph.item(r, 1) else ""),
                        self.ph.cellWidget(r, 2).value()))
        return out

    def _ph_add(self):
        if self.ph_formation:
            self._ph_row("basic", "", 1)

    def _ph_del(self):
        r = self.ph.currentRow()
        if r >= 0:
            self.ph.removeRow(r)

    def _ph_move(self, step):
        r = self.ph.currentRow()
        rows = self._ph_rows()
        if r < 0 or not 0 <= r + step < len(rows):
            return
        rows[r], rows[r + step] = rows[r + step], rows[r]
        self.ph.setRowCount(0)
        for k, lab, w in rows:
            self._ph_row(k, lab, w)
        self.ph.setCurrentCell(r + step, 1)

    def _ph_save(self):
        if not self.ph_formation:
            return
        FT.save_phases(self.db, self.ph_formation, self._ph_rows())
        self._preview()
        self.ctx.changed("formations")

    def _preview(self):
        if not self.ph_formation:
            self.preview.setText("")
            return
        d = self.current() or {}
        spec = d.get("id") if d.get("kind") == "specialty" else d.get("specialty")
        start = self.db.scalar("""SELECT MIN(c.start_date) FROM cohorts c JOIN levels l ON l.id=c.level_id
                                  WHERE l.formation_id=?""", (self.ph_formation,)) \
            or self.db.scalar("SELECT start_date FROM formations WHERE id=?", (self.ph_formation,))
        if not start or not FT.phases(self.db, self.ph_formation):
            self.preview.setText("لا توجد مراحل محفوظة لهذا التكوين.")
            return
        sch = FT.schedule(self.db, self.ph_formation, start, spec)
        sp_name = self.db.scalar("SELECT name FROM specialties WHERE id=?", (spec,)) if spec else None
        lines = [f"• {p['label']}: {p['start'].strftime('%d/%m')} ← {p['end'].strftime('%d/%m/%Y')} ({p['weeks']} أسبوع)"
                 for p in sch]
        self.preview.setText(("أول دفعة" + (f" — {sp_name}" if sp_name else "") + ":\n") + "\n".join(lines))

    def _ph_generate(self):
        if not self.ph_formation:
            return
        self._ph_save()
        rep = self.replace.isChecked()
        if rep and not confirm(self, "استبدال المخطط الزمني المستورد لأطوار هذا التكوين بالمراحل؟", danger=True):
            return
        res = FT.generate_timeline(self.db, self.ph_formation, replace_imported=rep)
        msg = f"كُتب {res['weeks']} أسبوع في المخطط الزمني."
        if res["skipped"]:
            msg += ("\nلم تُغيَّر أطوار لها مخطط مستورد من Excel (هو المرجع): " + "، ".join(res["skipped"])
                    + "\nفعّل «استبدال المخطط المستورد» إن أردت تطبيق المراحل عليها.")
        info(self, msg)
        self.ctx.changed("timeline")
