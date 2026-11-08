"""نافذة إنشاء الجداول آلياً (أسبوع، كل الأقسام، فترة كاملة) مع تشغيل في خيط منفصل."""
from __future__ import annotations

import traceback
from datetime import date

from PySide6.QtCore import QDate, QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDateEdit, QDialog, QFormLayout, QHBoxLayout, QHeaderView,
                               QLabel, QListWidget, QListWidgetItem, QProgressBar, QPushButton, QSpinBox, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout, QWidget)

from ...db.database import Database
from ...scheduler.engine import Scheduler
from ...services import timetables as T
from ...utils import hm, iso, week_start
from ..context import AppContext
from ..widgets import confirm, error, info


class Worker(QObject):
    progress = Signal(int, int, str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, db_path, job: dict):
        super().__init__()
        self.db_path, self.job = db_path, job

    def run(self):
        db = Database(self.db_path)
        try:
            j = self.job
            fids = j.get("formation_ids") or [j["formation_id"]]
            names = {r[0]: r[1] for r in db.q("SELECT id, name FROM formations")}
            results = []
            for k, fid in enumerate(fids):
                tag = f"[{names.get(fid, fid)}] " if len(fids) > 1 else ""
                if j["mode"] == "period":
                    res = T.plan_period(db, fid, j.get("start"), j.get("end"), time_limit=j["time_limit"],
                                        progress=lambda i, n, w, tag=tag: self.progress.emit(
                                            i, n, f"{tag}أسبوع {w.strftime('%d/%m/%Y')}"))
                elif j["mode"] == "reschedule":
                    self.progress.emit(0, 0, f"{tag}تحليل الرزنامة…")
                    res = T.reschedule_after_calendar_change(db, fid, apply=True)
                else:
                    self.progress.emit(k, len(fids), f"{tag}حل نموذج القيود…")
                    override, rules, plan_rows = None, None, None
                    if j.get("priorities"):
                        from ...services import priorities as PRI
                        override, plan_rows = PRI.week_plan(db, fid, j["week"], j.get("groups"))
                        rules = PRI.rules(db)
                    res = Scheduler(db, time_limit=j["time_limit"]).schedule_week(
                        fid, j["week"], j.get("groups"), hours_override=override, rules=rules)
                    if plan_rows is not None:
                        from ...services import priorities as PRI
                        res.plan_rows = PRI.compare_result(plan_rows, res)
                    if j.get("autosave") and res.placements:
                        # عدة تكوينات: نحفظ كل تكوين قبل التالي حتى تُحترم موارده المشتركة (الأساتذة والقاعات)
                        T.save_result(db, fid, res)
                results.append(res)
            self.done.emit(results if len(results) > 1 else results[0])
        except Exception:
            self.failed.emit(traceback.format_exc())
        finally:
            db.close()


class GenerateDialog(QDialog):
    def __init__(self, ctx: AppContext, week=None, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("إنشاء الجداول آلياً")
        self.resize(820, 620)
        self.result = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.mode = QComboBox()
        for k, v in [("all", "أسبوع واحد — جميع الأقسام معاً (موارد المؤسسة مشتركة)"),
                     ("some", "أسبوع واحد — أقسام مختارة"),
                     ("period", "فترة التكوين كاملة (من البداية إلى النهاية)"),
                     ("reschedule", "إعادة برمجة الحصص المتأثرة بعد تعديل الرزنامة")]:
            self.mode.addItem(v, k)
        form.addRow("نوع العملية", self.mode)
        self.week = QDateEdit()
        self.week.setCalendarPopup(True)
        self.week.setDisplayFormat("dd/MM/yyyy")
        w = week_start(week or date.today())
        self.week.setDate(QDate(w.year, w.month, w.day))
        form.addRow("الأسبوع (أي يوم منه)", self.week)
        fids = ctx.formation_ids() or [ctx.formation_id]
        marks = ",".join("?" * len(fids))
        f = ctx.db.one(f"SELECT MIN(start_date) start_date, MAX(end_date) end_date FROM formations WHERE id IN ({marks})",
                       fids)
        self.p_start = QDateEdit(QDate.fromString(f["start_date"] or iso(date.today()), "yyyy-MM-dd"))
        self.p_end = QDateEdit(QDate.fromString(f["end_date"] or iso(date.today()), "yyyy-MM-dd"))
        for d in (self.p_start, self.p_end):
            d.setCalendarPopup(True)
            d.setDisplayFormat("dd/MM/yyyy")
        pr = QHBoxLayout()
        pr.addWidget(QLabel("من"))
        pr.addWidget(self.p_start)
        pr.addWidget(QLabel("إلى"))
        pr.addWidget(self.p_end)
        self.period_row = QWidget()
        self.period_row.setLayout(pr)
        form.addRow("فترة البرمجة", self.period_row)
        self.sections = QListWidget()
        self.sections.setMaximumHeight(130)
        for r in ctx.q("SELECT id, short, name FROM sections WHERE formation_id=? ORDER BY formation_id, sort, short",
                       (ctx.formation_id,)):
            it = QListWidgetItem(f"{r['short']} — {r['name']}")
            it.setData(Qt.UserRole, r["id"])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked)
            self.sections.addItem(it)
        form.addRow("الأقسام", self.sections)
        self.limit = QSpinBox()
        self.limit.setRange(5, 600)
        self.limit.setValue(int(ctx.db.get_setting("engine_time_limit", "30") or 30))
        self.limit.setSuffix(" ثانية")
        form.addRow("المهلة القصوى للحل (لكل أسبوع)", self.limit)
        wl = QHBoxLayout()
        self.w_spread = QSpinBox()
        self.w_compact = QSpinBox()
        self.w_pref = QSpinBox()
        for sb, key, lab in [(self.w_spread, "w_spread", "توزيع المادة على الأيام"),
                             (self.w_compact, "w_compact", "تقليل الفراغات/التبكير"),
                             (self.w_pref, "w_teacher_pref", "تفضيلات الأساتذة")]:
            sb.setRange(0, 20)
            sb.setValue(ctx.db.get_int(key))
            wl.addWidget(QLabel(lab))
            wl.addWidget(sb)
        ww = QWidget()
        ww.setLayout(wl)
        form.addRow("أوزان التفضيلات", ww)
        lay.addLayout(form)
        hint = QLabel("القيود الإلزامية (تعارض الأستاذ/القاعة/الفوج، الأهلية، العطل، التوفر، المدة) لا تُكسر أبداً؛ "
                      "الأوزان تؤثر فقط في جودة الحل.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        row = QHBoxLayout()
        self.run_b = QPushButton("تشغيل المحرك")
        self.run_b.setObjectName("Primary")
        self.run_b.clicked.connect(self.run)
        self.save_b = QPushButton("حفظ كمسودة")
        self.save_b.setEnabled(False)
        self.save_b.clicked.connect(self.save)
        close_b = QPushButton("إغلاق")
        close_b.clicked.connect(self.reject)
        self.bar = QProgressBar()
        self.bar.setVisible(False)
        self.status = QLabel()
        row.addWidget(self.run_b)
        row.addWidget(self.save_b)
        row.addWidget(self.bar, 1)
        row.addWidget(close_b)
        lay.addLayout(row)
        lay.addWidget(self.status)

        self.tabs = QTabWidget()
        self.placed_t = self._table(["اليوم", "التوقيت", "المادة / الأفواج", "الأستاذ", "القاعة"])
        self.unplaced_t = self._table(["الحصة", "المدة", "السبب"])
        self.problems = QTextEdit()
        self.problems.setReadOnly(True)
        self.tabs.addTab(self.placed_t, "الحصص المبرمجة")
        self.tabs.addTab(self.unplaced_t, "الحصص المتعذرة")
        self.tabs.addTab(self.problems, "ملاحظات ومشاكل البيانات")
        from .priorities_panel import PrioritiesPanel
        self.prio = PrioritiesPanel(ctx, lambda: self.week.date().toPython(), self._groups)
        self.tabs.insertTab(0, self.prio, "أولويات الأسبوع")
        self.tabs.setCurrentIndex(0)
        lay.addWidget(self.tabs, 1)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self._mode_changed()

    def _table(self, headers):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        t.horizontalHeader().setStretchLastSection(True)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        return t

    def _mode_changed(self):
        m = self.mode.currentData()
        self.week.setEnabled(m in ("all", "some"))
        self.period_row.setEnabled(m == "period")
        self.sections.setEnabled(m == "some")
        self.save_b.setVisible(m in ("all", "some"))

    def _groups(self):
        if self.mode.currentData() != "some":
            return None
        secs = [self.sections.item(i).data(Qt.UserRole) for i in range(self.sections.count())
                if self.sections.item(i).checkState() == Qt.Checked]
        if not secs:
            return []
        q = ",".join("?" * len(secs))
        return [r[0] for r in self.ctx.db.q(f"SELECT id FROM groups_ WHERE section_id IN ({q})", secs)]

    def run(self):
        db = self.ctx.db
        for sb, key in [(self.w_spread, "w_spread"), (self.w_compact, "w_compact"), (self.w_pref, "w_teacher_pref")]:
            db.set_setting(key, sb.value())
        m = self.mode.currentData()
        if m == "period" and not confirm(self, "ستُستبدل الحصص المولدة آلياً في المسودات خلال الفترة. "
                                               "الحصص اليدوية والمنجزة والجداول المعتمدة لا تُلمس. متابعة؟"):
            return
        if m == "reschedule" and not confirm(self, "حذف الحصص المولدة آلياً الواقعة في أيام محجوبة وإعادة برمجة ساعاتها؟"):
            return
        if self.prio.enabled.isChecked():
            from ...services import priorities as PRI
            PRI.save(db, self.prio.values())
        groups = self._groups()
        if groups == []:
            error(self, "اختر قسماً واحداً على الأقل.")
            return
        fids = self.ctx.formation_ids() or [self.ctx.formation_id]
        if len(fids) > 1 and m in ("all", "some") and not confirm(
                self, f"«كل التكوينات»: ستُبرمج {len(fids)} تكوينات بالتتابع وتُحفظ كل نتيجة مباشرة كمسودة "
                      "(حتى يحترم كل تكوين أساتذة وقاعات التكوين الذي قبله). متابعة؟"):
            return
        job = {"mode": "week" if m in ("all", "some") else m, "formation_id": self.ctx.formation_id,
               "formation_ids": fids, "autosave": len(fids) > 1,
               "week": self.week.date().toPython(), "groups": groups, "time_limit": float(self.limit.value()),
               "priorities": self.prio.enabled.isChecked() and m in ("all", "some"),
               "start": self.p_start.date().toPython(), "end": self.p_end.date().toPython()}
        self.run_b.setEnabled(False)
        self.save_b.setEnabled(False)
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self.status.setText("جارٍ الحل… يمكنك الانتظار؛ الواجهة لا تتجمد.")
        self.thread = QThread(self)
        self.worker = Worker(str(db.path), job)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._progress)
        self.worker.done.connect(self._done)
        self.worker.failed.connect(self._failed)
        self.worker.done.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.start()

    def _progress(self, i, n, text):
        if n:
            self.bar.setRange(0, n)
            self.bar.setValue(i)
        self.status.setText(text)

    def _failed(self, tb):
        self.bar.setVisible(False)
        self.run_b.setEnabled(True)
        error(self, "حدث خطأ أثناء الجدولة:\n" + tb.splitlines()[-1])
        self.problems.setPlainText(tb)

    def _done(self, res):
        self.bar.setVisible(False)
        self.run_b.setEnabled(True)
        m = self.mode.currentData()
        self.placed_t.setRowCount(0)
        self.unplaced_t.setRowCount(0)
        db = self.ctx.db
        tname = {r[0]: r[1] for r in db.q("SELECT id, full_name FROM teachers")}
        rname = {r[0]: r[1] for r in db.q("SELECT id, name FROM rooms")}
        if isinstance(res, list):          # عدة تكوينات: النتائج حُفظت أثناء الحل
            auto = m in ("all", "some")
            merged = res[0]
            if m in ("all", "some"):
                for r in res[1:]:
                    merged.placements += r.placements
                    merged.unplaced += r.unplaced
                    merged.problems += r.problems
            elif m == "period":
                for r in res[1:]:
                    merged.weeks += r.weeks
                    merged.messages += r.messages
            else:
                merged = dict(res[0])
                merged["removed"] = sum(r["removed"] for r in res)
                merged["needs_confirmation"] = [x for r in res for x in r["needs_confirmation"]]
            res = merged
        else:
            auto = False
        if m in ("all", "some"):
            self.result = None if auto else res
            for p in res.placements:
                self._add(self.placed_t, [p.day.strftime("%a %d/%m"), f"{hm(p.start_min)}–{hm(p.end_min)}", p.meeting.label,
                                          tname.get(p.meeting.teacher_id, "—"), rname.get(p.room_id, "—")])
            for u in res.unplaced:
                self._add(self.unplaced_t, [u.meeting.label, f"{(u.meeting.minutes or 0) / 60:g} سا" if u.meeting.minutes
                                            else "يوم كامل", u.reason])
            self.problems.setPlainText("\n".join(res.problems) or "لا توجد مشاكل في البيانات.")
            self.status.setText(f"{res.summary()} (حالة الحل: {res.status})")
            self.save_b.setEnabled(bool(res.placements) and not auto)
            if auto:
                self.status.setText(f"{res.summary()} — حُفظت كل التكوينات كمسودات.")
                self.ctx.changed("sessions")
            if getattr(res, "plan_rows", None):
                from .priorities_panel import show_plan
                short = sum(1 for r in res.plan_rows if r["short"])
                self.status.setText(self.status.text() + f" · الأولويات: {short} سطر لم يُوضع كاملاً")
                show_plan(self, res.plan_rows, "المطلوب مقابل الموضوع", result=True)
            if res.unplaced:
                self.tabs.setCurrentIndex(self.tabs.indexOf(self.unplaced_t))
        elif m == "period":
            for w, r, _tt in res.weeks:
                for u in r.unplaced:
                    self._add(self.unplaced_t, [f"{w.strftime('%d/%m')} — {u.meeting.label}", "", u.reason])
            lines = [f"أسبوع {w.strftime('%d/%m/%Y')}: {r.summary()}" for w, r, _ in res.weeks]
            self.problems.setPlainText("\n".join(lines + res.messages + sorted({p for _, r, _ in res.weeks for p in r.problems})))
            self.status.setText(f"تمت برمجة {res.placed} حصة على {len(res.weeks)} أسبوعاً وحُفظت كمسودات.")
            self.tabs.setCurrentWidget(self.problems)
            self.ctx.changed("sessions")
        else:
            nc = res["needs_confirmation"]
            txt = [f"حُذفت {res['removed']} حصة مولدة آلياً من أيام محجوبة وأعيدت برمجتها."]
            if res.get("plan"):
                txt.append(f"أعيدت برمجة {res['plan'].placed} حصة.")
            if nc:
                txt.append(f"\n{len(nc)} حصة في جداول معتمدة أو معدلة يدوياً تقع في أيام محجوبة وتحتاج قرارك "
                           "(انقلها أو ألغها من المخطط):")
                txt += [f"• {r['date']} {hm(r['start_min'])}" for r in nc]
            self.problems.setPlainText("\n".join(txt))
            self.status.setText("اكتملت إعادة البرمجة.")
            self.tabs.setCurrentWidget(self.problems)
            self.ctx.changed("sessions")

    def _add(self, t, vals):
        r = t.rowCount()
        t.insertRow(r)
        for j, v in enumerate(vals):
            t.setItem(r, j, QTableWidgetItem(str(v)))

    def save(self):
        if not self.result:
            return
        try:
            tt = T.save_result(self.ctx.db, self.ctx.formation_id, self.result)
        except T.ConflictError as e:
            error(self, "\n".join(e.conflicts))
            return
        self.ctx.changed("sessions")
        msg = "حُفظ الجدول كمسودة. راجعه في المخطط ثم اعتمده."
        if self.result.unplaced:
            msg += f"\nتنبيه: {len(self.result.unplaced)} حصة لم تُبرمج — الجدول غير مكتمل."
        info(self, msg)
        self.save_b.setEnabled(False)
        _ = tt
