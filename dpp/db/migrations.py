"""ترحيلات مخطط قاعدة البيانات (تُطبق تلقائياً عند فتح قاعدة قديمة)."""
from __future__ import annotations

import sqlite3

# الإصدار 2: تكوين ← طور ← اختصاص ← دورة ← قسم، الفترات، أنواع المواد، التعارضات المتجاهلة، الاستيراد التاريخي
V2_TABLES = """
CREATE TABLE IF NOT EXISTS specialties (
    id INTEGER PRIMARY KEY,
    level_id INTEGER NOT NULL REFERENCES levels(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    short TEXT,
    decree TEXT,
    decree_date TEXT,
    hours REAL DEFAULT 0,
    activities_hours REAL DEFAULT 0,
    weeks INTEGER DEFAULT 0,
    UNIQUE(level_id, name)
);

CREATE TABLE IF NOT EXISTS cohorts (
    id INTEGER PRIMARY KEY,
    level_id INTEGER NOT NULL REFERENCES levels(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    week_mode TEXT DEFAULT 'start',      -- start | first_full
    week_offset INTEGER DEFAULT 0
);

-- ملفات الفترات: standard (5 فترات والغداء فترة)، basic (القاعدي المشترك)، basic_night (+ فترة ليلية)
CREATE TABLE IF NOT EXISTS periods (
    id INTEGER PRIMARY KEY,
    profile TEXT NOT NULL,
    idx INTEGER NOT NULL,
    label TEXT NOT NULL,
    start_min INTEGER NOT NULL,
    end_min INTEGER NOT NULL,
    kind TEXT DEFAULT 'day',             -- day | night
    UNIQUE(profile, idx)
);

CREATE TABLE IF NOT EXISTS conflict_ignores (
    key TEXT PRIMARY KEY,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    note TEXT
);

CREATE TABLE IF NOT EXISTS timeline (
    id INTEGER PRIMARY KEY,
    row_label TEXT NOT NULL,
    level_code TEXT,
    specialty_like TEXT,
    week_no INTEGER NOT NULL,
    week_start TEXT NOT NULL,
    kind TEXT NOT NULL                    -- reception | basic | specialized | leave | partial_exam | final_exam
);
"""

V2_COLUMNS = [
    ("levels", "code", "TEXT"), ("levels", "color", "TEXT DEFAULT '#5B8DEF'"), ("levels", "lunch_period", "INTEGER DEFAULT 3"),
    ("levels", "profile", "TEXT DEFAULT 'standard'"), ("levels", "sort", "INTEGER DEFAULT 0"),
    ("levels", "footer_note", "TEXT"), ("levels", "full_name", "TEXT"),
    ("sections", "specialty_id", "INTEGER REFERENCES specialties(id) ON DELETE SET NULL"),
    ("sections", "cohort_id", "INTEGER REFERENCES cohorts(id) ON DELETE SET NULL"),
    ("sections", "lunch_period", "INTEGER"), ("sections", "profile", "TEXT"),
    ("sections", "room_id", "INTEGER REFERENCES rooms(id) ON DELETE SET NULL"),
    ("sections", "asc_index", "INTEGER"), ("sections", "color", "TEXT"), ("sections", "sort", "INTEGER DEFAULT 0"),
    ("subjects", "kind", "TEXT DEFAULT 'teach'"), ("subjects", "category", "TEXT DEFAULT 'specialty'"),
    ("sessions", "imported", "INTEGER DEFAULT 0"),
    ("timetables", "imported_week", "INTEGER"), ("timetables", "source", "TEXT"),
    ("calendar_events", "level_id", "INTEGER REFERENCES levels(id) ON DELETE CASCADE"),
    ("calendar_events", "specialty_like", "TEXT"),
    ("requirements", "span_periods", "INTEGER"),
]

DEFAULT_PERIODS = {
    "standard": [(1, "الحصة الأولى", 480, 600), (2, "الحصة الثانية", 600, 720), (3, "الحصة الثالثة", 720, 780),
                 (4, "الحصة الرابعة", 780, 840), (5, "الحصة الخامسة", 840, 960)],
    "basic": [(1, "الحصة الأولى", 480, 600), (2, "الحصة الثانية", 600, 720), (3, "الحصة الثالثة", 720, 780),
              (4, "الحصة الرابعة", 780, 870), (5, "الحصة الخامسة", 870, 960)],
    "basic_night": [(1, "الحصة الأولى", 480, 600), (2, "الحصة الثانية", 600, 720), (3, "الحصة الثالثة", 720, 780),
                    (4, "الحصة الرابعة", 780, 870), (5, "الحصة الخامسة", 870, 960),
                    (6, "الفترة الليلية", 1020, 1440, "night")],
}
PROFILE_LABELS = {"standard": "عادي (5 فترات)", "basic": "القاعدي المشترك", "basic_night": "القاعدي المشترك + فترة ليلية"}


def _columns(conn, table) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def migrate(conn: sqlite3.Connection, current: int) -> int:
    if current < 2:
        conn.executescript(V2_TABLES)
        for table, col, decl in V2_COLUMNS:
            if col not in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        for prof, rows in DEFAULT_PERIODS.items():
            for row in rows:
                idx, label, s, e = row[:4]
                kind = row[4] if len(row) > 4 else "day"
                conn.execute("INSERT OR IGNORE INTO periods(profile, idx, label, start_min, end_min, kind) VALUES (?,?,?,?,?,?)",
                             (prof, idx, label, s, e, kind))
        conn.execute("CREATE INDEX IF NOT EXISTS ix_sg_group ON session_groups(group_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS ix_sessions_teacher ON sessions(teacher_id, date)")
        current = 2
    if current < 3:
        # المقرر (الحجم الساعي) لكل مادة حسب الطور والاختصاص والمرحلة؛ specialty_id=0 = كل اختصاصات الطور
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS curriculum (
            id INTEGER PRIMARY KEY,
            level_id INTEGER NOT NULL REFERENCES levels(id) ON DELETE CASCADE,
            specialty_id INTEGER NOT NULL DEFAULT 0,
            subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            phase TEXT NOT NULL DEFAULT 'all',
            hours REAL NOT NULL DEFAULT 0,
            source TEXT DEFAULT 'manual',
            UNIQUE(level_id, specialty_id, subject_id, phase)
        );
        """)
        current = 3
    if current < 4:
        # تصحيح الحجم الساعي الأسبوعي (قسم × مادة × أسبوع) دون لمس الحصص — لأخطاء الاستيراد
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS hours_adjust (
            id INTEGER PRIMARY KEY,
            section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
            subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
            week_start TEXT NOT NULL,
            hours REAL NOT NULL DEFAULT 0,
            note TEXT,
            UNIQUE(section_id, subject_id, week_start)
        );
        """)
        current = 4
    if current < 5:
        # الاختصارات العربية الملتصقة المولّدة آلياً («فتم») تصبح مفصولة بفراغات («ف ت م»)
        from ..utils import make_abbrev, space_arabic_initials
        for table, cut in (("specialties", 20), ("groups_", 8), ("subjects", 10), ("levels", 10)):
            cols = _columns(conn, table)
            if "short" not in cols:
                continue
            taken = {r[0] for r in conn.execute(f"SELECT short FROM {table} WHERE short IS NOT NULL")}
            for rid, name, short in conn.execute(f"SELECT id, name, short FROM {table}").fetchall():
                if not short or " " in short:
                    continue
                old = make_abbrev(name or "", spaced=False)
                if short not in (old, old[:cut], old[:10]):
                    continue
                new = space_arabic_initials(short)
                if new != short and (table != "subjects" or new not in taken):
                    conn.execute(f"UPDATE {table} SET short=? WHERE id=?", (new, rid))
                    taken.add(new)
        current = 5
    if current < 6:
        # مواد المقرر التي لم تُعرف عند الاستيراد: تُعدّل وتُدخل يدوياً (resolved: 0 مفتوحة، 1 أُدخلت، 2 تُجوهلت)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS curriculum_issues (
            id INTEGER PRIMARY KEY,
            level_id INTEGER REFERENCES levels(id) ON DELETE CASCADE,
            specialty_id INTEGER,
            block TEXT,
            name TEXT NOT NULL,
            hours REAL DEFAULT 0,
            reason TEXT,
            guess_subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
            resolved INTEGER DEFAULT 0
        );
        """)
        current = 6
    if current < 7:
        # الإصدار 1.4: تنبيهات البيانات الدائمة، الأقسام المعنية بالأحداث، الشهادة والسنة في شجرة التكوين،
        # نوع التربص ومدته لكل اختصاص، ومراحل التكوين بالأسابيع.
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS data_alerts (
            id INTEGER PRIMARY KEY,
            key TEXT UNIQUE,
            kind TEXT NOT NULL,                 -- curriculum_file | curriculum | data | progress
            severity TEXT DEFAULT 'medium',     -- high | medium | low
            title TEXT NOT NULL,
            details TEXT,
            level_id INTEGER,
            specialty_id INTEGER,
            subject_id INTEGER,
            target TEXT,                        -- أين يُصلح (صفحة/سطر)
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            resolved INTEGER DEFAULT 0          -- 0 مفتوح، 1 تم التأكيد
        );
        CREATE TABLE IF NOT EXISTS calendar_event_sections (
            event_id INTEGER NOT NULL REFERENCES calendar_events(id) ON DELETE CASCADE,
            section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
            PRIMARY KEY (event_id, section_id)
        );
        CREATE TABLE IF NOT EXISTS formation_phases (
            id INTEGER PRIMARY KEY,
            formation_id INTEGER NOT NULL REFERENCES formations(id) ON DELETE CASCADE,
            idx INTEGER NOT NULL,
            kind TEXT NOT NULL,                 -- reception | basic | leave | specialized
            label TEXT NOT NULL,
            weeks INTEGER NOT NULL DEFAULT 1,   -- للتخصصي: المدة الافتراضية، والاختصاص يحدد مدته
            UNIQUE(formation_id, idx)
        );
        """)
        for table, col, decl in (("levels", "certificate", "TEXT"), ("levels", "year_no", "INTEGER"),
                                 ("specialties", "internship", "TEXT")):
            if col not in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        # مواد غير دراسية سُجّلت دراسية في قواعد قديمة (مثل «عطلة نهاية الأسبوع»): لا تُحتسب في التقدم
        from ..services.structure import subject_category
        for sid, name, kind in conn.execute("SELECT id, name, COALESCE(kind,'teach') FROM subjects").fetchall():
            if kind != "nonteach" and subject_category(name or "") == "nonteach":
                conn.execute("UPDATE subjects SET kind='nonteach', category='nonteach' WHERE id=?", (sid,))
        current = 7
    if current < 8:
        # الإصدار 1.5: الخفارة والخدمات (نظام منفصل عن الجدول، يُدرج فيه عند الطلب فقط)
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS duty_types (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            per_day INTEGER NOT NULL DEFAULT 1,      -- عدد الأقسام في اليوم
            days TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
            scope TEXT NOT NULL DEFAULT '{}',        -- {"sections": [...], "levels": [...], "years": [...]}
            color TEXT DEFAULT '#CDB89B',
            subject_id INTEGER REFERENCES subjects(id) ON DELETE SET NULL,
            active INTEGER NOT NULL DEFAULT 1,
            sort INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS duty_assignments (
            id INTEGER PRIMARY KEY,
            type_id INTEGER NOT NULL REFERENCES duty_types(id) ON DELETE CASCADE,
            date TEXT NOT NULL,
            slot INTEGER NOT NULL DEFAULT 0,
            section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
            manual INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            session_id INTEGER,                       -- الحصة المُدرجة في الجدول (إن أُدرجت)
            UNIQUE(type_id, date, slot)
        );
        CREATE INDEX IF NOT EXISTS ix_duty_date ON duty_assignments(date);
        """)
        current = 8
    return current
