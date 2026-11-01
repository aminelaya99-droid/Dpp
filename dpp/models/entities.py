"""كل جداول قاعدة البيانات (SQLAlchemy 2.0).

الهيكل: تكوين (Training) → طور/سنة (Level) → اختصاص (Specialty) → فرع (Section).
الأوقات تُخزن بالدقائق منذ منتصف الليل، والأيام بفهرس يبدأ من الأحد = 0.
"""
from __future__ import annotations

import datetime as dt
import json
from typing import Optional

from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer,
                        String, Table, Text, UniqueConstraint, Float)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# أنواع المواد
SUBJECT_MILITARY = "military"
SUBJECT_SPECIALIZED = "specialized"
SUBJECT_GENERAL = "general"
SUBJECT_KINDS = {
    SUBJECT_MILITARY: "عسكرية",
    SUBJECT_SPECIALIZED: "تخصصية",
    SUBJECT_GENERAL: "عامة",
}

# أنواع الحصص/الأنشطة
LESSON_NORMAL = "lesson"
LESSON_EXAM = "exam"
LESSON_GUARD = "guard"
LESSON_SERVICE = "service"
LESSON_FIELD = "field"
LESSON_KINDS = {
    LESSON_NORMAL: "حصة",
    LESSON_EXAM: "امتحان",
    LESSON_GUARD: "خفارة",
    LESSON_SERVICE: "خدمات",
    LESSON_FIELD: "تمرين ميداني",
}
FULL_DAY_KINDS = {LESSON_EXAM, LESSON_GUARD, LESSON_SERVICE, LESSON_FIELD}

# أنواع المراحل
PHASE_KINDS = {
    "reception": "استقبال",
    "common": "تكوين قاعدي مشترك",
    "holiday": "عطلة",
    "specialized": "تكوين تخصصي",
    "normal": "مرحلة دراسية",
}

DAY_NAMES = ["الأحد", "الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت"]


teacher_specialty = Table(
    "teacher_specialty", Base.metadata,
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
    Column("specialty_id", ForeignKey("specialties.id", ondelete="CASCADE"), primary_key=True),
)

teacher_subject = Table(
    "teacher_subject", Base.metadata,
    Column("teacher_id", ForeignKey("teachers.id", ondelete="CASCADE"), primary_key=True),
    Column("subject_id", ForeignKey("subjects.id", ondelete="CASCADE"), primary_key=True),
)

event_section = Table(
    "event_section", Base.metadata,
    Column("event_id", ForeignKey("events.id", ondelete="CASCADE"), primary_key=True),
    Column("section_id", ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True),
)

shooting_section = Table(
    "shooting_section", Base.metadata,
    Column("shooting_id", ForeignKey("shooting_sessions.id", ondelete="CASCADE"), primary_key=True),
    Column("section_id", ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")


class Training(Base):
    """تكوين (فئة): BMP، ESOC، الاحتياط."""
    __tablename__ = "trainings"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    certificate_name: Mapped[str] = mapped_column(String(200), default="")
    start_date: Mapped[dt.date] = mapped_column(Date)
    weeks_count: Mapped[int] = mapped_column(Integer, default=36)
    weekend_days_json: Mapped[str] = mapped_column(String(40), default="[5, 6]")
    order: Mapped[int] = mapped_column(Integer, default=0)

    levels: Mapped[list["Level"]] = relationship(back_populates="training", cascade="all, delete-orphan",
                                                 order_by="Level.order")
    phases: Mapped[list["Phase"]] = relationship(back_populates="training", cascade="all, delete-orphan",
                                                 order_by="Phase.start_week")
    weeks: Mapped[list["Week"]] = relationship(back_populates="training", cascade="all, delete-orphan",
                                               order_by="Week.number")

    @property
    def weekend_days(self) -> list[int]:
        try:
            return list(json.loads(self.weekend_days_json or "[]"))
        except ValueError:
            return []

    @weekend_days.setter
    def weekend_days(self, days: list[int]) -> None:
        self.weekend_days_json = json.dumps(sorted(set(int(d) for d in days)))

    def week_start(self, number: int) -> dt.date:
        """تاريخ بداية الأسبوع رقم number (يبدأ الأحد)."""
        return self.start_date + dt.timedelta(days=7 * (number - 1))

    def week_number_for(self, day: dt.date) -> int:
        return (day - self.start_date).days // 7 + 1


class Level(Base):
    """سنة/طور: BMP1، ESOC 1، OF-R ..."""
    __tablename__ = "levels"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(200))
    order: Mapped[int] = mapped_column(Integer, default=0)
    day_start: Mapped[int] = mapped_column(Integer, default=8 * 60)
    day_end: Mapped[int] = mapped_column(Integer, default=16 * 60)
    lunch_start: Mapped[int] = mapped_column(Integer, default=12 * 60)
    lunch_minutes: Mapped[int] = mapped_column(Integer, default=60)
    study_minutes: Mapped[int] = mapped_column(Integer, default=7 * 60)
    has_night: Mapped[bool] = mapped_column(Boolean, default=False)
    # "phase": المقرر لكل مرحلة، "training": لكامل التكوين
    curriculum_scope: Mapped[str] = mapped_column(String(20), default="phase")

    training: Mapped[Training] = relationship(back_populates="levels")
    specialties: Mapped[list["Specialty"]] = relationship(back_populates="level", cascade="all, delete-orphan",
                                                         order_by="Specialty.order")


class Specialty(Base):
    __tablename__ = "specialties"
    id: Mapped[int] = mapped_column(primary_key=True)
    level_id: Mapped[int] = mapped_column(ForeignKey("levels.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(40), default="")
    order: Mapped[int] = mapped_column(Integer, default=0)
    # مدة التكوين التخصصي (أسابيع) إن اختلفت حسب نوع التربص
    specialized_weeks: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    level: Mapped[Level] = relationship(back_populates="specialties")
    sections: Mapped[list["Section"]] = relationship(back_populates="specialty", cascade="all, delete-orphan",
                                                     order_by="Section.order")
    teachers: Mapped[list["Teacher"]] = relationship(secondary=teacher_specialty, back_populates="specialties")


class Section(Base):
    """فرع (قسم)."""
    __tablename__ = "sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialties.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(60), default="")
    headcount: Mapped[int] = mapped_column(Integer, default=0)
    order: Mapped[int] = mapped_column(Integer, default=0)
    lunch_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # يتجاوز وقت غداء الطور

    specialty: Mapped[Specialty] = relationship(back_populates="sections")

    @property
    def level(self) -> Level:
        return self.specialty.level

    @property
    def training(self) -> Training:
        return self.specialty.level.training

    @property
    def effective_lunch_start(self) -> int:
        return self.lunch_start if self.lunch_start is not None else self.level.lunch_start


class Phase(Base):
    """مرحلة في المخطط الزمني للتكوين (المرجع عند التعارض مع الرزنامة الرسمية)."""
    __tablename__ = "phases"
    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id", ondelete="CASCADE"))
    level_id: Mapped[Optional[int]] = mapped_column(ForeignKey("levels.id", ondelete="CASCADE"), nullable=True)
    specialty_id: Mapped[Optional[int]] = mapped_column(ForeignKey("specialties.id", ondelete="CASCADE"),
                                                        nullable=True)
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20), default="normal")
    start_week: Mapped[int] = mapped_column(Integer, default=1)
    weeks_count: Mapped[int] = mapped_column(Integer, default=1)

    training: Mapped[Training] = relationship(back_populates="phases")

    @property
    def end_week(self) -> int:
        return self.start_week + self.weeks_count - 1

    def contains(self, week_number: int) -> bool:
        return self.start_week <= week_number <= self.end_week


class Subject(Base):
    __tablename__ = "subjects"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(250))
    short_name: Mapped[str] = mapped_column(String(60), default="")
    kind: Mapped[str] = mapped_column(String(20), default=SUBJECT_GENERAL)
    color: Mapped[str] = mapped_column(String(9), default="")  # درجة اللون الخاصة بالمادة
    level_id: Mapped[Optional[int]] = mapped_column(ForeignKey("levels.id", ondelete="SET NULL"), nullable=True)
    specialty_id: Mapped[Optional[int]] = mapped_column(ForeignKey("specialties.id", ondelete="SET NULL"),
                                                        nullable=True)
    allow_shared: Mapped[bool] = mapped_column(Boolean, default=False)  # رمي/تربية بدنية/نظام منظم/محاضرات
    is_shooting: Mapped[bool] = mapped_column(Boolean, default=False)
    is_night: Mapped[bool] = mapped_column(Boolean, default=False)  # تدريب ليلي (ESOC 1)

    teachers: Mapped[list["Teacher"]] = relationship(secondary=teacher_subject, back_populates="subjects")


class Teacher(Base):
    __tablename__ = "teachers"
    id: Mapped[int] = mapped_column(primary_key=True)
    last_name: Mapped[str] = mapped_column(String(120))  # اللقب: يظهر على البطاقات
    first_name: Mapped[str] = mapped_column(String(120), default="")
    rank: Mapped[str] = mapped_column(String(80), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    asc_id: Mapped[str] = mapped_column(String(80), default="")

    specialties: Mapped[list[Specialty]] = relationship(secondary=teacher_specialty, back_populates="teachers")
    subjects: Mapped[list[Subject]] = relationship(secondary=teacher_subject, back_populates="teachers")

    @property
    def display_name(self) -> str:
        return self.last_name or self.first_name

    @property
    def full_name(self) -> str:
        parts = [self.rank, self.last_name, self.first_name]
        return " ".join(p for p in parts if p)


class Week(Base):
    __tablename__ = "weeks"
    __table_args__ = (UniqueConstraint("training_id", "number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id", ondelete="CASCADE"))
    number: Mapped[int] = mapped_column(Integer)
    imported: Mapped[bool] = mapped_column(Boolean, default=False)
    source_file: Mapped[str] = mapped_column(String(400), default="")
    imported_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime, nullable=True)

    training: Mapped[Training] = relationship(back_populates="weeks")
    lessons: Mapped[list["Lesson"]] = relationship(back_populates="week", cascade="all, delete-orphan")

    @property
    def start_date(self) -> dt.date:
        return self.training.week_start(self.number)


class Lesson(Base):
    """حصة في الجدول الأسبوعي (أو نشاط يوم كامل)."""
    __tablename__ = "lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id", ondelete="CASCADE"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"),
                                                      nullable=True)
    teacher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"),
                                                      nullable=True)
    day: Mapped[int] = mapped_column(Integer)  # 0 = الأحد
    start: Mapped[int] = mapped_column(Integer)  # دقائق منذ منتصف الليل
    duration: Mapped[int] = mapped_column(Integer, default=60)
    kind: Mapped[str] = mapped_column(String(20), default=LESSON_NORMAL)
    origin: Mapped[str] = mapped_column(String(20), default="manual")  # import / manual / auto
    note: Mapped[str] = mapped_column(String(400), default="")

    week: Mapped[Week] = relationship(back_populates="lessons")
    section: Mapped[Section] = relationship()
    subject: Mapped[Optional[Subject]] = relationship()
    teacher: Mapped[Optional[Teacher]] = relationship()

    @property
    def end(self) -> int:
        return self.start + self.duration


class ImportedLesson(Base):
    """النسخة الأصلية المستوردة من ملف .roz (للرجوع إليها)."""
    __tablename__ = "imported_lessons"
    id: Mapped[int] = mapped_column(primary_key=True)
    week_id: Mapped[int] = mapped_column(ForeignKey("weeks.id", ondelete="CASCADE"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"),
                                                      nullable=True)
    teacher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"),
                                                      nullable=True)
    day: Mapped[int] = mapped_column(Integer)
    start: Mapped[int] = mapped_column(Integer)
    duration: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(20), default=LESSON_NORMAL)


class ConflictIgnore(Base):
    """تعارض اختار المستخدم تجاهله (بصمة ثابتة للتعارض)."""
    __tablename__ = "conflict_ignores"
    id: Mapped[int] = mapped_column(primary_key=True)
    signature: Mapped[str] = mapped_column(String(300), unique=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class Event(Base):
    """حدث (محاضرة عامة، زيارة، حفل ...) مع الفروع الحاضرة."""
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(250))
    date: Mapped[dt.date] = mapped_column(Date)
    start: Mapped[int] = mapped_column(Integer, default=8 * 60)
    end: Mapped[int] = mapped_column(Integer, default=16 * 60)
    location: Mapped[str] = mapped_column(String(200), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    blocks_lessons: Mapped[bool] = mapped_column(Boolean, default=True)

    sections: Mapped[list[Section]] = relationship(secondary=event_section)


class CurriculumItem(Base):
    """المقرر: حجم ساعي لمادة في اختصاص (لمرحلة أو لكامل التكوين)."""
    __tablename__ = "curriculum_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    specialty_id: Mapped[int] = mapped_column(ForeignKey("specialties.id", ondelete="CASCADE"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    phase_id: Mapped[Optional[int]] = mapped_column(ForeignKey("phases.id", ondelete="CASCADE"), nullable=True)
    hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)  # فارغ = ناقص في ملف المنهاج
    source_name: Mapped[str] = mapped_column(String(250), default="")

    specialty: Mapped[Specialty] = relationship()
    subject: Mapped[Subject] = relationship()
    phase: Mapped[Optional[Phase]] = relationship()


class Alert(Base):
    """تنبيهات داخل البرنامج (نواقص المنهاج، مطابقات مشكوك فيها ...)."""
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(40))  # curriculum / import / match
    severity: Mapped[str] = mapped_column(String(10), default="warning")  # info / warning / error
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[str] = mapped_column(Text, default="")
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=dt.datetime.now)


class PrintTemplate(Base):
    __tablename__ = "print_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    level_id: Mapped[Optional[int]] = mapped_column(ForeignKey("levels.id", ondelete="CASCADE"), nullable=True)
    section_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"),
                                                      nullable=True)
    layout_json: Mapped[str] = mapped_column(Text, default="{}")


class Weapon(Base):
    __tablename__ = "weapons"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    category: Mapped[str] = mapped_column(String(80), default="")
    caliber: Mapped[str] = mapped_column(String(40), default="")
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


class ShootingRange(Base):
    __tablename__ = "shooting_ranges"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    lanes: Mapped[int] = mapped_column(Integer, default=10)
    max_distance: Mapped[int] = mapped_column(Integer, default=100)


class ShootingSession(Base):
    """حصة رمي مبرمجة (على مستوى الفوج لا الطالب)."""
    __tablename__ = "shooting_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date)
    start: Mapped[int] = mapped_column(Integer, default=8 * 60)
    duration: Mapped[int] = mapped_column(Integer, default=240)
    weapon_id: Mapped[Optional[int]] = mapped_column(ForeignKey("weapons.id", ondelete="SET NULL"), nullable=True)
    range_id: Mapped[Optional[int]] = mapped_column(ForeignKey("shooting_ranges.id", ondelete="SET NULL"),
                                                    nullable=True)
    teacher_id: Mapped[Optional[int]] = mapped_column(ForeignKey("teachers.id", ondelete="SET NULL"),
                                                      nullable=True)
    exercise: Mapped[str] = mapped_column(String(200), default="")
    ammo_planned: Mapped[int] = mapped_column(Integer, default=0)
    ammo_used: Mapped[int] = mapped_column(Integer, default=0)
    notes: Mapped[str] = mapped_column(Text, default="")

    weapon: Mapped[Optional[Weapon]] = relationship()
    range: Mapped[Optional[ShootingRange]] = relationship()
    teacher: Mapped[Optional[Teacher]] = relationship()
    sections: Mapped[list[Section]] = relationship(secondary=shooting_section)


__all__ = [n for n in dir() if not n.startswith("_")]
