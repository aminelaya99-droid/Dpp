"""نوافذ المخطط: تعيين الأستاذ، التعارضات، اختيار المادة، تعديل الحصة."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QVBoxLayout)

from dpp.models import DAY_NAMES, LESSON_KINDS, SUBJECT_KINDS, Subject, Teacher
from dpp.services import catalog, planner
from dpp.services.textnorm import normalize
from dpp.services.timeutil import duration_choices, fmt, fmt_duration
from dpp.ui.theme import T
from dpp.ui.widgets import button, warn

NEW_TEACHER = -1


class TeacherDialog(QDialog):
    """تعيين أستاذ: اقتراح أساتذة الاختصاص، بحث في الكل، وإدخال اسم حر (أستاذ جديد)."""

    def __init__(self, s, week, section, subject, day, start, duration, preselect: Teacher | None = None,
                 exclude_ids: set | None = None, show_all: bool = False, parent=None):
        super().__init__(parent)
        self.s, self.week, self.section, self.subject = s, week, section, subject
        self.day, self.start, self.duration = day, start, duration
        self.exclude_ids = exclude_ids or set()
        self.result_teacher: Teacher | None = None
        self.accepted_busy = False
        self.setWindowTitle("تعيين أستاذ")
        self.resize(460, 520)
        lay = QVBoxLayout(self)
        head = QLabel(f"<b>{subject.name if subject else 'نشاط'}</b> — {section.name}<br>"
                      f"{DAY_NAMES[day]} {fmt(start)}–{fmt(start + duration)}")
        lay.addWidget(head)
        self.search = QLineEdit()
        self.search.setPlaceholderText("ابحث باللقب أو الاسم، أو اكتب اسماً جديداً…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.fill)
        lay.addWidget(self.search)
        self.all_box = QCheckBox("عرض كل الأساتذة (منتقي البديل)")
        self.all_box.setChecked(show_all)
        self.all_box.toggled.connect(self.fill)
        lay.addWidget(self.all_box)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda *_: self.choose())
        lay.addWidget(self.list, 1)
        new_row = QHBoxLayout()
        self.new_last = QLineEdit()
        self.new_last.setPlaceholderText("اللقب")
        self.new_first = QLineEdit()
        self.new_first.setPlaceholderText("الاسم (اختياري)")
        new_row.addWidget(self.new_last)
        new_row.addWidget(self.new_first)
        new_row.addWidget(button("إضافة أستاذ جديد", self.add_new))
        lay.addLayout(new_row)
        row = QHBoxLayout()
        row.addWidget(button("تعيين", self.choose, primary=True))
        row.addWidget(button("بدون أستاذ", self.no_teacher))
        row.addStretch(1)
        row.addWidget(button("إلغاء", self.reject))
        lay.addLayout(row)
        self.preselect = preselect
        self.fill()

    def _candidates(self) -> list[Teacher]:
        q = normalize(self.search.text())
        spec = self.section.specialty
        if self.all_box.isChecked() or q:
            pool = catalog.teachers(self.s)
        else:
            pool = list(spec.teachers)
            if self.preselect and self.preselect not in pool:
                pool.append(self.preselect)
        if q:
            pool = [t for t in pool if q in normalize(f"{t.last_name} {t.first_name} {t.rank}")]

        def rank(t: Teacher):
            return (0 if self.subject and self.subject in t.subjects else 1,
                    0 if spec in t.specialties else 1, t.last_name)
        return sorted(pool, key=rank)

    def fill(self) -> None:
        self.list.clear()
        text = self.search.text().strip()
        cands = self._candidates()
        if text and not any(normalize(t.last_name) == normalize(text) for t in cands):
            it = QListWidgetItem(f"＋ إضافة «{text}» كأستاذ جديد")
            it.setData(Qt.UserRole, NEW_TEACHER)
            it.setForeground(QColor(T["accent"]))
            self.list.addItem(it)
        for t in cands:
            busy = planner.teacher_busy(self.s, self.week, t, self.day, self.start, self.start + self.duration,
                                        self.exclude_ids, self.subject)
            label = t.last_name + (f" {t.first_name}" if t.first_name else "")
            if t.rank:
                label = f"{t.rank} {label}"
            tags = []
            if self.subject and self.subject in t.subjects:
                tags.append("يدرّس المادة")
            if busy:
                b = busy[0]
                tags.append(f"مشغول: {b.section.name} {fmt(b.start)}–{fmt(b.end)}")
            it = QListWidgetItem(label + (f"   — {'، '.join(tags)}" if tags else ""))
            it.setData(Qt.UserRole, t.id)
            it.setData(Qt.UserRole + 1, bool(busy))
            if busy:
                it.setForeground(QColor(T["danger"]))
            self.list.addItem(it)
            if self.preselect and t.id == self.preselect.id:
                self.list.setCurrentItem(it)
        if self.list.currentRow() < 0 and self.list.count():
            self.list.setCurrentRow(0)

    def _create(self, last: str, first: str = "") -> Teacher:
        t = catalog.get_or_create_teacher(self.s, last, first, self.section.specialty)
        if self.subject:
            catalog.link_teacher_subject(t, self.subject)
        self.s.flush()
        return t

    def add_new(self) -> None:
        last = self.new_last.text().strip()
        if not last:
            warn(self, "اكتب لقب الأستاذ")
            return
        self.result_teacher = self._create(last, self.new_first.text().strip())
        self.accept()

    def choose(self) -> None:
        it = self.list.currentItem()
        if not it:
            return
        tid = it.data(Qt.UserRole)
        if tid == NEW_TEACHER:
            words = self.search.text().strip()
            self.result_teacher = self._create(words)
            self.accept()
            return
        t = self.s.get(Teacher, tid)
        if it.data(Qt.UserRole + 1):
            r = QMessageBox.warning(self, "أستاذ مشغول",
                                    f"الأستاذ {t.last_name} مبرمج في نفس الوقت. اختياره رغم ذلك؟",
                                    QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
            self.accepted_busy = True
        # ربط الأستاذ بالاختصاص والمادة
        if self.section.specialty not in t.specialties:
            t.specialties.append(self.section.specialty)
        if self.subject:
            catalog.link_teacher_subject(t, self.subject)
        self.result_teacher = t
        self.accept()

    def no_teacher(self) -> None:
        self.result_teacher = None
        self.accept()


class ConflictDialog(QDialog):
    """عند ظهور تعارض جديد: التجاهل أو التصحيح."""
    IGNORE, FIX = "ignore", "fix"

    def __init__(self, conflicts, parent=None):
        super().__init__(parent)
        self.choice = self.FIX
        self.setWindowTitle("تعارض")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lbl = QLabel("<b>هذا التعديل يُحدث التعارضات التالية:</b>")
        lay.addWidget(lbl)
        lst = QListWidget()
        for c in conflicts:
            it = QListWidgetItem(f"{c.label}: {c.message}")
            it.setForeground(QColor(T["danger"]))
            lst.addItem(it)
        lay.addWidget(lst)
        row = QHBoxLayout()
        row.addWidget(button("تصحيح (التراجع عن التعديل)", self._fix, primary=True))
        row.addWidget(button("تجاهل التعارض", self._ignore))
        lay.addLayout(row)

    def _fix(self) -> None:
        self.choice = self.FIX
        self.accept()

    def _ignore(self) -> None:
        self.choice = self.IGNORE
        self.accept()

    def reject(self) -> None:  # الإغلاق = تصحيح
        self.choice = self.FIX
        super().reject()


class SubjectPicker(QDialog):
    """اختيار مادة (مع بحث) أو إنشاء مادة جديدة، وأستاذ مقترح اختياري — لبطاقة جديدة."""

    def __init__(self, s, subjects: list[Subject], with_teacher: bool = True, title="بطاقة جديدة", parent=None):
        super().__init__(parent)
        self.s = s
        self.subject: Subject | None = None
        self.teacher: Teacher | None = None
        self.pinned = False
        self.setWindowTitle(title)
        self.resize(440, 480)
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("بحث عن مادة…")
        self.search.textChanged.connect(self.fill)
        lay.addWidget(self.search)
        self.list = QListWidget()
        lay.addWidget(self.list, 1)
        self.subjects = subjects
        form = QFormLayout()
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText("أو اسم مادة جديدة")
        self.new_kind = QComboBox()
        for k, v in SUBJECT_KINDS.items():
            self.new_kind.addItem(v, k)
        form.addRow("مادة جديدة", self.new_name)
        form.addRow("نوعها", self.new_kind)
        self.teacher_box = QComboBox()
        self.teacher_box.addItem("— بدون —", None)
        for t in catalog.teachers(s):
            self.teacher_box.addItem(t.last_name + (f" {t.first_name}" if t.first_name else ""), t.id)
        self.pin = QCheckBox("تثبيت البطاقة (تبقى في الشريط بعد وضعها)")
        if with_teacher:
            form.addRow("أستاذ مقترح", self.teacher_box)
            form.addRow("", self.pin)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("موافق")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self._ok)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.fill()

    def fill(self) -> None:
        q = normalize(self.search.text())
        self.list.clear()
        for subj in self.subjects:
            if q and q not in normalize(subj.name):
                continue
            it = QListWidgetItem(f"{subj.name}  ({SUBJECT_KINDS.get(subj.kind, '')})")
            it.setData(Qt.UserRole, subj.id)
            self.list.addItem(it)

    def _ok(self) -> None:
        name = self.new_name.text().strip()
        if name:
            self.subject = catalog.get_or_create_subject(self.s, name, kind=self.new_kind.currentData())
            self.s.commit()
        else:
            it = self.list.currentItem()
            if not it:
                warn(self, "اختر مادة أو اكتب اسم مادة جديدة")
                return
            self.subject = self.s.get(Subject, it.data(Qt.UserRole))
        tid = self.teacher_box.currentData()
        self.teacher = self.s.get(Teacher, tid) if tid else None
        self.pinned = self.pin.isChecked()
        self.accept()


class LessonEditDialog(QDialog):
    def __init__(self, s, lesson, subjects, parent=None):
        super().__init__(parent)
        self.setWindowTitle("تعديل الحصة")
        self.lesson = lesson
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.subject = QComboBox()
        self.subject.addItem("— بدون مادة —", None)
        for subj in subjects:
            self.subject.addItem(subj.name, subj.id)
        self.subject.setCurrentIndex(max(0, self.subject.findData(lesson.subject_id)))
        self.teacher = QComboBox()
        self.teacher.addItem("— بدون أستاذ —", None)
        for t in catalog.teachers(s):
            self.teacher.addItem(t.last_name + (f" {t.first_name}" if t.first_name else ""), t.id)
        self.teacher.setCurrentIndex(max(0, self.teacher.findData(lesson.teacher_id)))
        self.day = QComboBox()
        for i, d in enumerate(DAY_NAMES):
            self.day.addItem(d, i)
        self.day.setCurrentIndex(lesson.day)
        self.start = QComboBox()
        lv = lesson.section.level
        for m in range(lv.day_start, lv.day_end, 30):
            self.start.addItem(fmt(m), m)
        i = self.start.findData(lesson.start)
        if i < 0:
            self.start.addItem(fmt(lesson.start), lesson.start)
            i = self.start.count() - 1
        self.start.setCurrentIndex(i)
        self.duration = QComboBox()
        for m in duration_choices():
            self.duration.addItem(fmt_duration(m), m)
        j = self.duration.findData(lesson.duration)
        if j < 0:
            self.duration.addItem(fmt_duration(lesson.duration), lesson.duration)
            j = self.duration.count() - 1
        self.duration.setCurrentIndex(j)
        self.kind = QComboBox()
        for k, v in LESSON_KINDS.items():
            self.kind.addItem(v, k)
        self.kind.setCurrentIndex(max(0, self.kind.findData(lesson.kind)))
        self.note = QLineEdit(lesson.note)
        form.addRow("المادة", self.subject)
        form.addRow("الأستاذ", self.teacher)
        form.addRow("اليوم", self.day)
        form.addRow("البداية", self.start)
        form.addRow("المدة", self.duration)
        form.addRow("النوع", self.kind)
        form.addRow("ملاحظة", self.note)
        lay.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("حفظ")
        bb.button(QDialogButtonBox.Cancel).setText("إلغاء")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def apply(self) -> None:
        les = self.lesson
        les.subject_id = self.subject.currentData()
        les.teacher_id = self.teacher.currentData()
        les.day = self.day.currentData()
        les.start = self.start.currentData()
        les.duration = self.duration.currentData()
        les.kind = self.kind.currentData()
        les.note = self.note.text().strip()
        if les.origin == "import":
            les.origin = "manual"
