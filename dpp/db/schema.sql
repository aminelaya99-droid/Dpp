PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    pw_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- التكوينات: rest_days = أرقام أيام الراحة مفصولة بفواصل (0=الأحد … 6=السبت)
CREATE TABLE IF NOT EXISTS formations (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    short TEXT,
    start_date TEXT,
    end_date TEXT,
    rest_days TEXT DEFAULT '5,6',
    archived INTEGER DEFAULT 0,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS levels (
    id INTEGER PRIMARY KEY,
    formation_id INTEGER NOT NULL REFERENCES formations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    short TEXT
);

CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY,
    formation_id INTEGER NOT NULL REFERENCES formations(id) ON DELETE CASCADE,
    level_id INTEGER REFERENCES levels(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    short TEXT,
    size INTEGER DEFAULT 0,
    UNIQUE(formation_id, short)
);

-- الأفواج: الفوج الكامل (is_whole=1) يتعارض مع كل مجموعاته الفرعية
CREATE TABLE IF NOT EXISTS groups_ (
    id INTEGER PRIMARY KEY,
    section_id INTEGER NOT NULL REFERENCES sections(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    short TEXT,
    is_whole INTEGER DEFAULT 0,
    size INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS subjects (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    short TEXT UNIQUE,
    color TEXT DEFAULT '#4F7CAC',
    shareable INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    short TEXT,
    capacity INTEGER DEFAULT 0,
    kind TEXT
);

CREATE TABLE IF NOT EXISTS teacher_categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    military INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS teachers (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    rank TEXT,
    category_id INTEGER REFERENCES teacher_categories(id) ON DELETE SET NULL,
    specialty TEXT,
    max_week_hours REAL DEFAULT 0,
    active INTEGER DEFAULT 1,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS teacher_subjects (
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    PRIMARY KEY (teacher_id, subject_id)
);

-- المتطلبات: ما يجب تدريسه لكل فوج (الحجم الساعي ومدة الحصة)
-- share_code: متطلبات بنفس الرمز والمادة والأستاذ تُبرمج كحصة مشتركة واحدة
CREATE TABLE IF NOT EXISTS requirements (
    id INTEGER PRIMARY KEY,
    formation_id INTEGER NOT NULL REFERENCES formations(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups_(id) ON DELETE CASCADE,
    subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    room_id INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    total_hours REAL DEFAULT 0,
    weekly_hours REAL DEFAULT 0,
    session_minutes INTEGER DEFAULT 120,
    needs_room INTEGER DEFAULT 0,
    share_code TEXT,
    priority INTEGER DEFAULT 0
);

-- عدم التوفر: kind = teacher | room | group ؛ weekday 0..6 أو date محدد
CREATE TABLE IF NOT EXISTS unavailability (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    ref_id INTEGER NOT NULL,
    weekday INTEGER,
    date TEXT,
    start_min INTEGER NOT NULL,
    end_min INTEGER NOT NULL,
    hard INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS calendar_events (
    id INTEGER PRIMARY KEY,
    formation_id INTEGER REFERENCES formations(id) ON DELETE CASCADE,
    section_id INTEGER REFERENCES sections(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    kind TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    description TEXT,
    importance INTEGER DEFAULT 1,
    blocks_scheduling INTEGER DEFAULT 0,
    remind_days TEXT DEFAULT '7,3,1'
);

CREATE TABLE IF NOT EXISTS timetables (
    id INTEGER PRIMARY KEY,
    formation_id INTEGER NOT NULL REFERENCES formations(id) ON DELETE CASCADE,
    week_start TEXT NOT NULL,
    status TEXT DEFAULT 'draft',
    version INTEGER DEFAULT 1,
    note TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- الحصص: status = planned | done | postponed | cancelled
-- teacher_id = الأستاذ المكلف أصلاً ؛ substitute_id = المستخلف إن وُجد
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    timetable_id INTEGER REFERENCES timetables(id) ON DELETE CASCADE,
    requirement_id INTEGER REFERENCES requirements(id) ON DELETE SET NULL,
    date TEXT NOT NULL,
    start_min INTEGER NOT NULL,
    end_min INTEGER NOT NULL,
    subject_id INTEGER NOT NULL REFERENCES subjects(id),
    teacher_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    substitute_id INTEGER REFERENCES teachers(id) ON DELETE SET NULL,
    room_id INTEGER REFERENCES rooms(id) ON DELETE SET NULL,
    status TEXT DEFAULT 'planned',
    is_makeup INTEGER DEFAULT 0,
    makeup_of INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    manual INTEGER DEFAULT 0,
    note TEXT
);
CREATE INDEX IF NOT EXISTS ix_sessions_date ON sessions(date);
CREATE INDEX IF NOT EXISTS ix_sessions_tt ON sessions(timetable_id);

CREATE TABLE IF NOT EXISTS session_groups (
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups_(id) ON DELETE CASCADE,
    PRIMARY KEY (session_id, group_id)
);

CREATE TABLE IF NOT EXISTS absences (
    id INTEGER PRIMARY KEY,
    teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS timetable_snapshots (
    id INTEGER PRIMARY KEY,
    timetable_id INTEGER NOT NULL REFERENCES timetables(id) ON DELETE CASCADE,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    label TEXT,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS templates (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    data TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts TEXT DEFAULT CURRENT_TIMESTAMP,
    username TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    details TEXT
);
