"""صفحة المخطط الأسبوعي التفاعلي."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                               QMenu, QScrollArea, QSlider, QSpinBox, QSplitter, QVBoxLayout, QWidget)

from dpp.models import (DAY_NAMES, FULL_DAY_KINDS, LESSON_KINDS, LESSON_NORMAL, Event, Lesson, Section,
                        Subject, Teacher, Training)
from dpp.services import catalog, planner, roz_import, structure
from dpp.services import settings as cfg
from dpp.services.timeutil import duration_choices, fmt, fmt_duration
from dpp.ui.planner.dialogs import ConflictDialog, LessonEditDialog, SubjectPicker, TeacherDialog
from dpp.ui.planner.grid import (DAYS_ROWS, MAIN, TIME_GRID, BlockVM, CardVM, GridModel, LaneVM, PlannerGrid,
                                 tooltip_for)
from dpp.ui.planner.palette import Palette
from dpp.ui.theme import T, subject_color
from dpp.ui.widgets import Page, button, confirm, info

FULL_DAY_COLORS = {"exam": "#FCA5A5", "guard": "#CBD5E1", "service": "#D6D3D1", "field": "#A7F3D0"}


class PlannerPage(Page):
    title = "المخطط الأسبوعي"
    subtitle = "اسحب بطاقات المواد إلى الجدول؛ الزر الأيمن على الحصة لاختيار المدة والوقت"

    def __init__(self, main):
        super().__init__(main)
        self._loading = False
        self._conflict_ids: set[int] = set()
        self._conflicts = []
        # ---- شريط الأدوات
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.training = QComboBox()
        self.training.currentIndexChanged.connect(self._training_changed)
        self.week = QSpinBox()
        self.week.setRange(1, 200)
        self.week.setPrefix("الأسبوع ")
        self.week.valueChanged.connect(self.reload)
        self.week_lbl = QLabel()
        self.week_lbl.setObjectName("Muted")
        self.view = QComboBox()
        self.view.addItem("كل الفروع (العرض الرئيسي)", MAIN)
        self.view.addItem("فرع واحد", "single")
        self.view.currentIndexChanged.connect(self._view_changed)
        self.level = QComboBox()
        self.level.currentIndexChanged.connect(self.reload)
        self.section = QComboBox()
        self.section.currentIndexChanged.connect(self.reload)
        self.layout_box = QComboBox()
        self.layout_box.addItem("الأيام صفوف", DAYS_ROWS)
        self.layout_box.addItem("الشبكة الزمنية", TIME_GRID)
        self.layout_box.currentIndexChanged.connect(self._layout_changed)
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(50, 250)
        self.zoom.setValue(100)
        self.zoom.setFixedWidth(110)
        self.zoom.setToolTip("تكبير/تصغير")
        self.zoom.valueChanged.connect(lambda v: self.grid.set_zoom(v / 100))
        for w in (self.training, button("‹", lambda: self.week.setValue(self.week.value() - 1)), self.week,
                  button("›", lambda: self.week.setValue(self.week.value() + 1)), self.week_lbl, self.view,
                  self.level, self.section, self.layout_box):
            bar.addWidget(w)
        for c in (self.training, self.view, self.level, self.section, self.layout_box):
            c.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        self.training.setMinimumWidth(190)
        bar.addStretch(1)
        bar.addWidget(QLabel("تكبير"))
        bar.addWidget(self.zoom)
        self.root.addLayout(bar)
        self.add_action("نسخ الأسبوع السابق", self.copy_previous)
        self.revert_btn = self.add_action("الرجوع للنسخة المستوردة", self.revert_import, danger=True)

        # ---- الشبكة + لوحة التعارضات
        split = QSplitter(Qt.Horizontal)
        self.grid = PlannerGrid()
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.grid)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignRight | Qt.AlignTop)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea { background: white; border: 1px solid #E2E8F0; border-radius: 6px; }")
        side = QWidget()
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        self.conf_title = QLabel("التعارضات")
        self.conf_title.setStyleSheet("font-weight: 700;")
        sv.addWidget(self.conf_title)
        self.conf_list = QListWidget()
        self.conf_list.setWordWrap(True)
        self.conf_list.itemClicked.connect(self._conflict_clicked)
        sv.addWidget(self.conf_list, 1)
        r = QHBoxLayout()
        r.addWidget(button("تجاهل المحدد", self._ignore_selected))
        sv.addLayout(r)
        split.addWidget(side)
        split.addWidget(self.scroll)
        split.setStretchFactor(1, 1)
        split.setSizes([260, 1000])
        self.root.addWidget(split, 1)

        # ---- الشريط السفلي
        self.palette = Palette()
        self.palette.newCardRequested.connect(self.new_card)
        self.root.addWidget(self.palette)

        self.grid.cardDropped.connect(self.on_card_dropped)
        self.grid.lessonMoved.connect(self.on_lesson_moved)
        self.grid.contextRequested.connect(self.on_context)
        self.grid.lessonActivated.connect(self.edit_lesson)
        self.grid.deleteRequested.connect(self.delete_lesson)
        self._pending_section = None

    # ------------------------------------------------------------ التحميل
    def focus_on(self, section_id: int | None = None, training_id: int | None = None, week: int | None = None):
        sec = self.s.get(Section, section_id) if section_id else None
        self._pending_section = sec
        if sec is not None:
            training_id = sec.training.id
        self.refresh()
        if training_id:
            self.training.setCurrentIndex(max(0, self.training.findData(training_id)))
        if sec is not None:
            self.view.setCurrentIndex(1)
            self.section.setCurrentIndex(max(0, self.section.findData(sec.id)))
        if week:
            self.week.setValue(week)
        self._pending_section = None
        self.reload()

    def refresh(self) -> None:
        self._loading = True
        cur = self.training.currentData()
        self.training.clear()
        for t in structure.trainings(self.s):
            self.training.addItem(t.name, t.id)
        self.training.setCurrentIndex(max(0, self.training.findData(cur)))
        self._loading = False
        if cur is None or self.training.currentData() != cur:
            self._training_changed()
        else:
            self.reload()

    def current_training(self) -> Training | None:
        tid = self.training.currentData()
        return self.s.get(Training, tid) if tid else None

    def _training_changed(self) -> None:
        if self._loading:
            return
        t = self.current_training()
        if not t:
            return
        self._loading = True
        self.week.setRange(1, max(1, t.weeks_count + 4))
        self.week.setValue(min(structure.current_week_number(t), t.weeks_count))
        self.level.clear()
        self.level.addItem("كل الأطوار", None)
        for lv in t.levels:
            self.level.addItem(lv.code, lv.id)
        self.section.clear()
        for sec in structure.all_sections(self.s, training_id=t.id):
            self.section.addItem(f"{sec.name} — {sec.specialty.level.code}", sec.id)
        self._loading = False
        self._view_changed()

    def _view_changed(self) -> None:
        single = self.view.currentData() == "single"
        self.section.setVisible(single)
        self.layout_box.setVisible(single)
        self.level.setVisible(not single)
        if not single:
            self.grid.rtl = True
        self.reload()

    def _layout_changed(self) -> None:
        cfg.put(self.s, "planner_layout", self.layout_box.currentData())
        self.reload()

    def current_week(self):
        t = self.current_training()
        return planner.get_week(self.s, t, self.week.value()) if t else None

    def shown_sections(self) -> list[Section]:
        t = self.current_training()
        if not t:
            return []
        if self.view.currentData() == "single":
            sid = self.section.currentData()
            sec = self.s.get(Section, sid) if sid else None
            return [sec] if sec else []
        return structure.all_sections(self.s, training_id=t.id, level_id=self.level.currentData())

    def reload(self) -> None:
        if self._loading:
            return
        t = self.current_training()
        if not t:
            return
        w = self.current_week()
        s = self.s
        start = w.start_date
        ph = structure.phase_for_week(t, w.number)
        self.week_lbl.setText(f"{start:%d/%m/%Y} – {start + dt.timedelta(days=6):%d/%m/%Y}"
                              + (f" — {ph.name}" if ph else " — خارج المخطط الزمني")
                              + (" — مستورد" if w.imported else ""))
        self.revert_btn.setVisible(bool(w.imported))
        sections = self.shown_sections()
        sec_ids = {x.id for x in sections}
        mode = MAIN if self.view.currentData() == MAIN else self.layout_box.currentData()
        days = [d for d in range(7) if d not in t.weekend_days]
        levels = {x.level.id: x.level for x in sections} or {lv.id: lv for lv in t.levels}
        t0 = min(lv.day_start for lv in levels.values())
        t1 = max(lv.day_end for lv in levels.values())
        m = GridModel(mode=mode, days=days, t0=t0, t1=t1)
        if mode == MAIN:
            m.lanes = [LaneVM(x.id, None, x.name, f"{x.level.code} · {x.specialty.name}") for x in sections]
        else:
            m.section_id = sections[0].id if sections else None
            for d in days:
                mins = planner.day_study_minutes(w, m.section_id, d) if m.section_id else 0
                m.lanes.append(LaneVM(m.section_id, d, DAY_NAMES[d], f"{mins / 60:g}/7 سا"))
        # الحصص والتعارضات
        self._conflicts = planner.week_conflicts(s, w)
        self._conflict_ids = {i for c in self._conflicts for i in c.lesson_ids}
        for les in w.lessons:
            if les.section_id not in sec_ids:
                continue
            full = les.kind in FULL_DAY_KINDS
            col = QColor(FULL_DAY_COLORS.get(les.kind)) if full and not les.subject else subject_color(les.subject)
            title = planner.lesson_title(les)
            if full and les.subject:
                title = f"{LESSON_KINDS[les.kind]}: {les.subject.name}"
            teacher = les.teacher.display_name if les.teacher else ""
            m.cards.append(CardVM(
                les.id, les.section_id, les.day, les.start, les.duration, title, teacher, col,
                LESSON_KINDS.get(les.kind, ""), les.id in self._conflict_ids, full,
                tooltip_for(title, les.teacher.full_name if les.teacher else "", les.start, les.duration,
                            les.section.name, les.note)))
        # الغداء والأحداث
        for sec in sections:
            lv = sec.level
            if lv.lunch_minutes:
                for d in days:
                    m.blocks.append(BlockVM(sec.id, d, sec.effective_lunch_start,
                                            sec.effective_lunch_start + lv.lunch_minutes, "lunch"))
        for ev in s.query(Event).filter(Event.date >= start, Event.date <= start + dt.timedelta(days=6)):
            day = (ev.date - start).days
            for sec in ev.sections:
                if sec.id in sec_ids:
                    m.blocks.append(BlockVM(sec.id, day, ev.start, ev.end, "event", ev.title))
        self.grid.default_duration = planner.default_duration(s)
        self.grid.avail_w = self.scroll.viewport().width() - 18
        self.grid.set_model(m)
        self._fill_conflicts()
        self._fill_palette(sections)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        if self.grid.m.mode != MAIN:
            self.grid.avail_w = self.scroll.viewport().width() - 18
            self.grid.relayout()

    def _fill_conflicts(self) -> None:
        self.conf_list.clear()
        self.conf_title.setText(f"التعارضات ({len(self._conflicts)})")
        for c in self._conflicts:
            it = QListWidgetItem(f"{c.label}\n{c.message}")
            it.setData(Qt.UserRole, c)
            it.setForeground(QColor(T["danger"]))
            self.conf_list.addItem(it)
        if not self._conflicts:
            self.conf_list.addItem("لا توجد تعارضات ✓")

    def _fill_palette(self, sections: list[Section]) -> None:
        subjects: dict[int, Subject] = {}
        for sec in sections:
            for subj in catalog.subjects_for_section(self.s, sec):
                subjects[subj.id] = subj
        remaining = None
        if len(sections) == 1:
            try:
                from dpp.services import progress
                remaining = progress.remaining_hours(self.s, sections[0])
            except Exception:  # noqa: BLE001
                remaining = None
        ordered = sorted(subjects.values(), key=lambda x: ({"military": 0, "specialized": 1}.get(x.kind, 2), x.name))
        self.palette.set_subjects(ordered, remaining)

    # ------------------------------------------------------------ التعارضات
    def _check(self, lessons: list[Lesson], snapshots: list[planner.Snapshot], auto_ignore_teacher=False) -> bool:
        """يعيد True إن بقي التعديل. يسأل المستخدم عند ظهور تعارض جديد."""
        self.s.flush()
        cs = planner.lesson_conflicts(self.s, lessons)
        if auto_ignore_teacher:
            teacher_cs = [c for c in cs if c.kind == "teacher"]
            planner.ignore_conflicts(self.s, teacher_cs)
            cs = [c for c in cs if c.kind != "teacher"]
        if not cs:
            self.s.commit()
            return True
        dlg = ConflictDialog(cs, self)
        dlg.exec()
        if dlg.choice == ConflictDialog.IGNORE:
            self.s.commit()
            planner.ignore_conflicts(self.s, cs)
            return True
        self.s.commit()
        for snap in snapshots:
            snap.restore(self.s)
        return False

    def _conflict_clicked(self, it) -> None:
        c = it.data(Qt.UserRole)
        if c:
            self.grid.selected_id = c.lesson_ids[0]
            self.grid.update()

    def _ignore_selected(self) -> None:
        it = self.conf_list.currentItem()
        c = it.data(Qt.UserRole) if it else None
        if c:
            planner.ignore_conflicts(self.s, [c])
            self.reload()

    # ------------------------------------------------------------ الإسقاط والنقل
    def on_card_dropped(self, payload: dict, section_id: int, day: int, minute: int) -> None:
        s = self.s
        w = self.current_week()
        sec = s.get(Section, section_id)
        subj = s.get(Subject, payload.get("subject_id")) if payload.get("subject_id") else None
        dur = planner.default_duration(s)
        pre = s.get(Teacher, payload["teacher_id"]) if payload.get("teacher_id") else None
        if pre is None and subj is not None:
            pre = planner.previous_teacher(s, sec, subj)
        dlg = TeacherDialog(s, w, sec, subj, day, minute, dur, preselect=pre, parent=self)
        if not dlg.exec():
            s.rollback()
            return
        les = planner.place_lesson(s, w, sec, day, minute, subj, dlg.result_teacher, dur)
        snap = planner.Snapshot(les.id, None)
        if self._check([les], [snap], auto_ignore_teacher=dlg.accepted_busy):
            self.palette.consume(payload.get("key"))
            self.main and self.main.status(f"أُضيفت حصة {subj.name if subj else ''} — اضغط بالزر الأيمن لتغيير المدة")
        self.reload()

    def on_lesson_moved(self, lesson_id: int, section_id: int, day: int, minute: int) -> None:
        s = self.s
        les = s.get(Lesson, lesson_id)
        if not les:
            return
        if (les.section_id, les.day, les.start) == (section_id, day, minute):
            return
        snap = planner.Snapshot.of(les)
        planner.move_lesson(les, s.get(Section, section_id), day, minute)
        self._check([les], [snap])  # النقل يحتفظ بالأستاذ ويسأل فقط عند التعارض
        self.reload()

    # ------------------------------------------------------------ القائمة
    def on_context(self, lesson_id: int, section_id: int, day: int, minute: int, gpos) -> None:
        menu = QMenu(self)
        if lesson_id:
            les = self.s.get(Lesson, lesson_id)
            head = menu.addAction(f"{planner.lesson_title(les)} — {fmt(les.start)}–{fmt(les.end)}")
            head.setEnabled(False)
            menu.addSeparator()
            if les.kind not in FULL_DAY_KINDS:
                dm = menu.addMenu("المدة")
                grp = QActionGroup(dm)
                for mins in duration_choices():
                    a = QAction(fmt_duration(mins), dm, checkable=True)
                    a.setChecked(mins == les.duration)
                    a.triggered.connect(lambda _=False, m=mins: self.set_duration(lesson_id, m))
                    grp.addAction(a)
                    dm.addAction(a)
                sm = menu.addMenu("اقتراحات الوقت")
                starts = planner.free_starts(self.s, les.week, les.section, les.day, les.duration, les.id)
                for st in starts:
                    sm.addAction(f"{fmt(st)} – {fmt(st + les.duration)}",
                                 lambda st=st: self.on_lesson_moved(lesson_id, les.section_id, les.day, st))
                if not starts:
                    sm.addAction("لا يوجد وقت فارغ بهذه المدة").setEnabled(False)
            menu.addAction("تغيير الأستاذ / بديل…", lambda: self.change_teacher(lesson_id))
            km = menu.addMenu("النوع")
            for k, v in LESSON_KINDS.items():
                a = km.addAction(v, lambda k=k: self.set_kind(lesson_id, k))
                a.setCheckable(True)
                a.setChecked(les.kind == k)
            menu.addAction("تعديل…", lambda: self.edit_lesson(lesson_id))
            if lesson_id in self._conflict_ids:
                menu.addAction("تجاهل تعارضات هذه الحصة", lambda: self.ignore_lesson(lesson_id))
            menu.addSeparator()
            menu.addAction("حذف الحصة", lambda: self.delete_lesson(lesson_id))
        else:
            sec = self.s.get(Section, section_id)
            menu.addAction(f"{sec.name} — {DAY_NAMES[day]} {fmt(minute)}").setEnabled(False)
            menu.addSeparator()
            menu.addAction("بطاقة مادة هنا…", lambda: self.add_here(section_id, day, minute))
            fm = menu.addMenu("نشاط يوم كامل")
            for k in ("exam", "guard", "service", "field"):
                fm.addAction(LESSON_KINDS[k], lambda k=k: self.add_full_day(section_id, day, k))
        menu.exec(gpos)

    def set_duration(self, lesson_id: int, minutes: int) -> None:
        les = self.s.get(Lesson, lesson_id)
        snap = planner.Snapshot.of(les)
        planner.set_duration(les, minutes)
        self._check([les], [snap])
        self.reload()

    def set_kind(self, lesson_id: int, kind: str) -> None:
        les = self.s.get(Lesson, lesson_id)
        snap = planner.Snapshot.of(les)
        les.kind = kind
        if kind in FULL_DAY_KINDS:
            lv = les.section.level
            les.start, les.duration = lv.day_start, lv.day_end - lv.day_start
        elif snap.values["kind"] in FULL_DAY_KINDS:
            les.duration = planner.default_duration(self.s)
        self._check([les], [snap])
        self.reload()

    def change_teacher(self, lesson_id: int) -> None:
        s = self.s
        les = s.get(Lesson, lesson_id)
        dlg = TeacherDialog(s, les.week, les.section, les.subject, les.day, les.start, les.duration,
                            preselect=les.teacher, exclude_ids={les.id}, show_all=True, parent=self)
        if not dlg.exec():
            s.rollback()
            return
        snap = planner.Snapshot.of(les)
        les.teacher = dlg.result_teacher
        self._check([les], [snap], auto_ignore_teacher=dlg.accepted_busy)
        self.reload()

    def edit_lesson(self, lesson_id: int) -> None:
        les = self.s.get(Lesson, lesson_id)
        subjects = catalog.subjects_for_section(self.s, les.section)
        dlg = LessonEditDialog(self.s, les, subjects, self)
        if dlg.exec():
            snap = planner.Snapshot.of(les)
            dlg.apply()
            self._check([les], [snap])
            self.reload()

    def delete_lesson(self, lesson_id: int) -> None:
        les = self.s.get(Lesson, lesson_id)
        if les:
            self.s.delete(les)
            self.s.commit()
            self.main and self.main.status("حُذفت الحصة")
            self.reload()

    def ignore_lesson(self, lesson_id: int) -> None:
        planner.ignore_conflicts(self.s, [c for c in self._conflicts if lesson_id in c.lesson_ids])
        self.reload()

    def add_here(self, section_id: int, day: int, minute: int) -> None:
        sec = self.s.get(Section, section_id)
        dlg = SubjectPicker(self.s, catalog.subjects_for_section(self.s, sec), with_teacher=False,
                            title="مادة للحصة", parent=self)
        if dlg.exec() and dlg.subject:
            self.on_card_dropped({"subject_id": dlg.subject.id}, section_id, day, minute)

    def add_full_day(self, section_id: int, day: int, kind: str) -> None:
        s = self.s
        sec = s.get(Section, section_id)
        subj = None
        if kind == "exam":
            dlg = SubjectPicker(s, catalog.subjects_for_section(s, sec), with_teacher=False,
                                title="مادة الامتحان (تُحسب في التقدم)", parent=self)
            if dlg.exec():
                subj = dlg.subject
        les = planner.place_lesson(s, self.current_week(), sec, day, 0, subj, None, kind=kind)
        self._check([les], [planner.Snapshot(les.id, None)])
        self.reload()

    def new_card(self) -> None:
        sections = self.shown_sections()
        subjects = {}
        for sec in sections:
            for subj in catalog.subjects_for_section(self.s, sec):
                subjects[subj.id] = subj
        dlg = SubjectPicker(self.s, sorted(subjects.values(), key=lambda x: x.name) or catalog.subjects(self.s),
                            parent=self)
        if dlg.exec() and dlg.subject:
            self.palette.add_custom(dlg.subject, dlg.teacher, dlg.pinned)
            if dlg.subject.id not in subjects:
                self.reload()

    # ------------------------------------------------------------ أدوات الأسبوع
    def copy_previous(self) -> None:
        t = self.current_training()
        n = self.week.value()
        if n <= 1:
            return
        src = planner.get_week(self.s, t, n - 1, create=False)
        if not src or not src.lessons:
            info(self, "الأسبوع السابق فارغ")
            return
        dst = self.current_week()
        if dst.lessons and not confirm(self, "الأسبوع الحالي يحتوي حصصاً. إضافة حصص الأسبوع السابق إليه؟"):
            return
        sections = {x.id for x in self.shown_sections()}
        k = planner.copy_week(self.s, src, dst, sections)
        self.main and self.main.status(f"نُسخت {k} حصة")
        self.reload()

    def revert_import(self) -> None:
        w = self.current_week()
        if w.imported and confirm(self, "الرجوع للنسخة المستوردة الأصلية لهذا الأسبوع؟ ستضيع التعديلات."):
            roz_import.revert_week(self.s, w)
            self.reload()
