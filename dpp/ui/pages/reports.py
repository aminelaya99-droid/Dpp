"""مركز التقارير + مصمم القوالب + التصدير (Word/Excel/PDF) والمعاينة."""
from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ...exporters import model as M
from ...exporters.render import export
from ...services import templates as TP
from ...utils import iso, week_start, weeks_between
from ..context import AppContext
from ..widgets import FormDialog, error, icon, info, page_title

REPORTS = [
    ("week_section", "الجدول الأسبوعي للقسم", "week_section"),
    ("week_teacher", "جدول الأستاذ الأسبوعي", "week_teacher"),
    ("week_all", "جدول جميع الأقسام", "week_all"),
    ("period_plan", "مخطط فترة التكوين", "period_plan"),
    ("progress", "الساعات وتقدم المواد والمتأخرة", "progress"),
    ("teacher_hours", "كشف ساعات الأساتذة (توزيع ساعات التدريس)", "teacher_hours"),
    ("absences", "الغيابات والاستخلاف", "absences"),
    ("status", "الحصص المؤجلة والملغاة والتعويضية", "generic"),
    ("exams", "الامتحانات والمواعيد", "exams"),
    ("summary", "ملخص التكوين", "generic"),
]

def tpl_from_layout(db, key: str) -> dict:
    """إعدادات Word القديمة مأخوذة من تصميم التقرير في المحرر الواحد (الورق، الاتجاه، الهوامش، الألوان)."""
    from ...exporters import layout as L
    lay, _u = L.effective(db, f"report_{key}")
    t = TP.default_template("generic")
    t["paper"] = "A3" if lay["page"].get("paper") == "A3" else "A4"
    t["orientation"] = lay["page"].get("orientation", "portrait")
    t["margins_mm"] = [round(float(x) / 2.835) for x in lay["page"].get("margins", [22] * 4)]
    t["header_bg"] = lay["table"].get("head_fill") or t["header_bg"]
    t["border_color"] = lay["table"].get("border_color") or t["border_color"]
    t["font_size"] = int(round(float(lay["table"].get("title_pt") or 9)))
    t["show"] = t["show"] | {"institution": True, "week": True, "formation": True}
    return t


class ReportsPage(QWidget):
    def __init__(self, ctx: AppContext):
        super().__init__()
        self.ctx = ctx
        TP.ensure_defaults(ctx.db)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 14)
        left = QVBoxLayout()
        left.addWidget(page_title("مركز التقارير"))
        self.list = QListWidget()
        self.list.setMaximumWidth(330)
        for key, lab, _k in REPORTS:
            it = QListWidgetItem(icon("mdi6.file-document-outline"), lab)
            it.setData(Qt.UserRole, key)
            self.list.addItem(it)
        self.list.currentRowChanged.connect(self._changed)
        left.addWidget(self.list)
        lay.addLayout(left)
        right = QVBoxLayout()
        self.box = QGroupBox("المرشحات")
        f = QFormLayout(self.box)
        self.section = QComboBox()
        self.teacher = QComboBox()
        self.week = QDateEdit()
        self.d0 = QDateEdit()
        self.d1 = QDateEdit()
        for d in (self.week, self.d0, self.d1):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        self.week.setDate(date.today())
        self.d0.setDate(date.today() - timedelta(days=30))
        self.d1.setDate(date.today())
        self.weeks_n = QSpinBox()
        self.weeks_n.setRange(1, 60)
        self.weeks_n.setValue(1)
        f.addRow("القسم", self.section)
        f.addRow("الأستاذ", self.teacher)
        f.addRow("الأسبوع (أي يوم منه)", self.week)
        f.addRow("عدد الأسابيع المتتالية", self.weeks_n)
        f.addRow("من تاريخ", self.d0)
        f.addRow("إلى تاريخ", self.d1)
        right.addWidget(self.box)
        tb = QGroupBox("القالب")
        tl = QHBoxLayout(tb)
        tl.addWidget(QLabel("شكل التقرير (الورق، الرأس، الجدول، النصوص) يُصمَّم في محرر الطباعة الواحد."))
        des = QPushButton(icon("mdi6.palette-outline"), "تصميم القالب")
        des.clicked.connect(self.design)
        tl.addWidget(des)
        right.addWidget(tb)
        ex = QHBoxLayout()
        for text, ic, fmt in [("معاينة", "mdi6.eye-outline", "preview"), ("Word", "mdi6.file-word-outline", "docx"),
                              ("Excel", "mdi6.file-excel-outline", "xlsx"), ("PDF", "mdi6.file-pdf-box", "pdf"),
                              ("طباعة", "mdi6.printer-outline", "print")]:
            b = QPushButton(icon(ic), text)
            if fmt == "preview":
                b.setObjectName("Primary")
            b.clicked.connect(lambda _=False, x=fmt: self.run(x))
            ex.addWidget(b)
        right.addLayout(ex)
        self.note = QLabel("المعاينة تفتح محرر الطباعة: تعديل على الورقة، تصميم القالب، طباعة، PDF وExcel.")
        self.note.setObjectName("Muted")
        self.note.setWordWrap(True)
        right.addWidget(self.note)
        right.addStretch()
        lay.addLayout(right, 1)
        ctx.data_changed.connect(lambda w: self._fill() if w in ("*", "sections", "teachers", "templates") else None)
        ctx.formation_changed.connect(lambda _: self._fill())
        self._fill()
        self.list.setCurrentRow(0)

    def _fill(self):
        db = self.ctx.db
        self.section.clear()
        for r in self.ctx.q("SELECT id, short, name FROM sections WHERE formation_id=? ORDER BY short", (self.ctx.formation_id or -1,)):
            self.section.addItem(f"{r['short']} — {r['name']}", r["id"])
        self.teacher.clear()
        for r in db.q("SELECT id, full_name FROM teachers WHERE active=1 ORDER BY full_name"):
            self.teacher.addItem(r["full_name"], r["id"])
        self._changed(self.list.currentRow())

    def _kind(self):
        i = self.list.currentRow()
        return REPORTS[i] if i >= 0 else REPORTS[0]

    def _changed(self, _i):
        key, _lab, kind = self._kind()
        self.section.setEnabled(key == "week_section")
        self.teacher.setEnabled(key == "week_teacher")
        self.week.setEnabled(key.startswith("week"))
        self.weeks_n.setEnabled(key.startswith("week"))
        self.d0.setEnabled(key in ("teacher_hours", "absences", "exams"))
        self.d1.setEnabled(key in ("teacher_hours", "absences", "exams", "progress"))

    def design(self):
        self.run("preview", design=True)

    def build(self):
        db, fid = self.ctx.db, self.ctx.formation_id
        key, _lab, kind = self._kind()
        tpl = tpl_from_layout(db, key)
        if key.startswith("week") or key in ("period_plan", "progress", "status", "summary"):
            if not fid:
                raise ValueError("لا يوجد تكوين حالي.")
        if key.startswith("week"):
            ws = week_start(self.week.date().toPython())
            reps = []
            for i in range(self.weeks_n.value()):
                w = ws + timedelta(days=7 * i)
                if key == "week_section":
                    if self.section.currentData() is None:
                        raise ValueError("اختر قسماً.")
                    reps.append(M.report_week(db, fid, w, tpl, section_id=self.section.currentData()))
                elif key == "week_teacher":
                    if self.teacher.currentData() is None:
                        raise ValueError("اختر أستاذاً.")
                    reps.append(M.report_week(db, None, w, tpl, teacher_id=self.teacher.currentData()))
                else:
                    reps.append(M.report_week(db, None if self.ctx.all_formations else fid, w, tpl))
            rep = reps[0]
            for r in reps[1:]:
                rep.blocks.append("")
                rep.blocks += [f"— {r.info_lines[-1]} —"] + r.blocks
            return rep, tpl
        if key == "period_plan":
            return M.report_period_plan(db, fid, tpl), tpl
        if key == "progress":
            return M.report_progress(db, self.ctx.formation_ids(), tpl, self.d1.date().toPython()), tpl
        if key == "teacher_hours":
            return M.report_teacher_hours(db, self.d0.date().toPython(), self.d1.date().toPython(), tpl), tpl
        if key == "absences":
            return M.report_absences(db, self.d0.date().toPython(), self.d1.date().toPython(), tpl), tpl
        if key == "status":
            return M.report_sessions_status(db, self.ctx.formation_ids(), tpl), tpl
        if key == "exams":
            return M.report_events(db, tpl, {"exam", "final_exam", "evaluation"}, iso(self.d0.date().toPython()),
                                   iso(self.d1.date().toPython())), tpl
        # ملخص التكوين
        from ...services import progress as PR
        cs = self.ctx.scalar
        fids = self.ctx.formation_ids()
        marks = ",".join("?" * len(fids))
        f = db.one(f"SELECT MIN(start_date) s, MAX(end_date) e FROM formations WHERE id IN ({marks})", fids)
        p = PR.summarize(PR.section_progress(db, fids))
        rows = [["التكوين", self.ctx.formation_label()], ["الفترة", f"{f['s']} → {f['e']}"],
                ["عدد الأقسام", cs("SELECT COUNT(*) FROM sections WHERE formation_id=?", (fid,), 0)],
                ["الحجم الساعي المقرر (المرحلة الحالية)", p["hours"]], ["المنجز", p["done"]],
                ["المتوقع حتى اليوم", round(p["expected"], 2)],
                ["نسبة الإنجاز", "—" if p["pct_done"] is None else f"{p['pct_done']}%"],
                ["نسبة التنفيذ", "—" if p["pct_exec"] is None else f"{p['pct_exec']}%"],
                ["المواد المتأخرة", p["late"]], ["مواد بلا مقرر", p["missing"]],
                ["الحصص المؤجلة", cs("""SELECT COUNT(*) FROM sessions s JOIN timetables t ON t.id=s.timetable_id
                                       WHERE t.formation_id=? AND s.status='postponed'""", (fid,), 0)],
                ["الحصص الملغاة", cs("""SELECT COUNT(*) FROM sessions s JOIN timetables t ON t.id=s.timetable_id
                                       WHERE t.formation_id=? AND s.status='cancelled'""", (fid,), 0)],
                ["الحصص التعويضية", cs("""SELECT COUNT(*) FROM sessions s JOIN timetables t ON t.id=s.timetable_id
                                         WHERE t.formation_id=? AND s.is_makeup=1""", (fid,), 0)]]
        return M.report_table(db, "ملخص التكوين", ["البند", "القيمة"], rows, tpl), tpl

    def _sheets(self, rep, key):
        """الأوراق للمحرر الواحد: جداول الأقسام والأساتذة بأوراقها الرسمية، وباقي التقارير صفحات تقرير."""
        from ...exporters import official as O
        from ...exporters import report_sheet as RS
        db = self.ctx.db
        if key in ("week_section", "week_teacher"):
            ws = week_start(self.week.date().toPython())
            kind = "section" if key == "week_section" else "teacher"
            tid = self.section.currentData() if kind == "section" else self.teacher.currentData()
            return [O.build(db, kind, tid, ws + timedelta(days=7 * i)) for i in range(self.weeks_n.value())]
        doc = RS.from_model(rep, key)
        if key == "week_all":
            doc.key = "week_all"
        return RS.sheets(db, doc)

    def _word_sections(self):
        """ورقة القسم بصيغة Word من قالب Word (القسم ← الطور ← المولَّد)؛ عدة أسابيع في ملف واحد."""
        from ...exporters import official as O
        from ...exporters import word_tpl as W
        import tempfile
        db = self.ctx.db
        sid = self.section.currentData()
        if sid is None:
            error(self, "اختر قسماً.")
            return
        ws = week_start(self.week.date().toPython())
        sheets = [O.build_section_sheet(db, sid, ws + timedelta(days=7 * i)) for i in range(self.weeks_n.value())]
        default = str(Path.home() / f"{W._safe(sheets[0].name)} — الأسبوع {sheets[0].values.get('week', '')}.docx")
        path, _ = QFileDialog.getSaveFileName(self, "حفظ Word", default, "Word (*.docx)")
        if not path:
            return
        if not path.lower().endswith(".docx"):
            path += ".docx"
        try:
            if len(sheets) == 1:
                W.fill_to(db, sheets[0], path)
            else:
                tmp = Path(tempfile.mkdtemp())
                parts = [W.fill_to(db, sh, tmp / f"{i}.docx") for i, sh in enumerate(sheets)]
                W.merge(parts, Path(path))
        except Exception as e:
            error(self, f"تعذر التصدير: {e}")
            return
        db.log("تصدير Word من قالب", "reports", None, {"section": sid, "file": path})
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def run(self, fmt, design=False):
        key = self._kind()[0]
        try:
            rep, tpl = self.build()
        except ValueError as e:
            error(self, str(e))
            return
        if fmt in ("preview", "print", "pdf", "xlsx"):
            from ..sheet_view import PreviewDialog
            try:
                sheets = self._sheets(rep, key)
            except Exception as e:
                error(self, f"تعذر إنشاء المعاينة: {e}")
                return
            if not sheets:
                info(self, "لا توجد بيانات.")
                return
            dlg = PreviewDialog(self.ctx.db, sheets, self,
                                self.ctx.db.get_setting("print_show_room", "1") == "1",
                                self.ctx.db.get_setting("print_color", "0") == "1")
            if design:
                dlg.b_design.setChecked(True)
            if fmt == "pdf":
                dlg.do_pdf()
            elif fmt == "xlsx":
                dlg.do_xlsx()
            elif fmt == "print":
                dlg.do_print()
            else:
                dlg.exec()
            return
        if fmt == "docx" and key == "week_section":
            self._word_sections()
            return
        default = str(Path.home() / f"{rep.title.replace('/', '-').replace(':', '')}.{fmt}")
        filt = {"docx": "Word (*.docx)"}[fmt]
        path, _ = QFileDialog.getSaveFileName(self, "حفظ التقرير", default, filt)
        if not path:
            return
        if not path.lower().endswith("." + fmt):
            path += "." + fmt
        try:
            export(rep, tpl, fmt, path)
        except Exception as e:
            error(self, f"تعذر التصدير: {e}")
            return
        self.ctx.db.log("تصدير تقرير", "reports", None, {"title": rep.title, "format": fmt, "file": path})
        info(self, f"تم التصدير إلى:\n{path}")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
