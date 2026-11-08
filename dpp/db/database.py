"""طبقة الاتصال بقاعدة بيانات SQLite."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA_VERSION = 8
SCHEMA_FILE = Path(__file__).with_name("schema.sql")

DEFAULT_SETTINGS = {
    "institution_name": "",
    "institution_short": "",
    "day_start": "480",      # 08:00 بالدقائق
    "day_end": "990",        # 16:30
    "lunch_start": "720",    # 12:00
    "lunch_end": "780",      # 13:00
    "slot_minutes": "30",
    "theme": "auto",
    "backup_dir": "",
    "backup_keep": "10",
    "backup_auto": "1",
    "w_spread": "5",
    "w_compact": "1",
    "w_teacher_pref": "3",
}

DEFAULT_CATEGORIES = [("عسكري", 1), ("مدني", 0), ("م م م", 0), ("م م ش", 0), ("أ ت ج", 0),
                      ("أستاذ توقيت جزئي", 0)]


def default_data_dir() -> Path:
    base = os.environ.get("DPP_DATA_DIR")
    if base:
        return Path(base)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home())) / "DPP"
    return Path.home() / ".dpp"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000)
    return h.hex(), salt


class Database:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.current_user = "admin"
        self._init_schema()

    # ------------------------------------------------------------------
    def _init_schema(self):
        self.conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        cur = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'")
        if cur.fetchone() is None:
            with self.tx():
                self.conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
                for k, v in DEFAULT_SETTINGS.items():
                    self.conn.execute("INSERT OR IGNORE INTO settings VALUES (?, ?)", (k, v))
                for name, mil in DEFAULT_CATEGORIES:
                    self.conn.execute("INSERT OR IGNORE INTO teacher_categories(name, military) VALUES (?, ?)",
                                      (name, mil))
        from .migrations import migrate
        cur_v = int(self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0])
        if cur_v < SCHEMA_VERSION:
            new_v = migrate(self.conn, cur_v)
            self.conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(new_v),))

    def close(self):
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self.conn.close()

    @contextmanager
    def tx(self):
        """معاملة: كل شيء أو لا شيء (تدعم التداخل)."""
        if self.conn.in_transaction:
            yield self.conn
            return
        try:
            self.conn.execute("BEGIN")
            yield self.conn
            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # ------------------------------------------------------------------
    def q(self, sql: str, params=()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params=()):
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params=(), default=None):
        r = self.conn.execute(sql, params).fetchone()
        return default if r is None or r[0] is None else r[0]

    def execute(self, sql: str, params=()) -> int:
        """تنفيذ مع حفظ فوري (خارج المعاملات الصريحة)."""
        return self.conn.execute(sql, params).lastrowid

    def insert(self, table: str, **values) -> int:
        cols = ", ".join(values)
        ph = ", ".join("?" for _ in values)
        return self.conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({ph})", tuple(values.values())).lastrowid

    def update(self, table: str, row_id: int, **values):
        sets = ", ".join(f"{k}=?" for k in values)
        self.conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", (*values.values(), row_id))

    def commit(self):
        if self.conn.in_transaction:
            self.conn.commit()

    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: str = "") -> str:
        r = self.one("SELECT value FROM settings WHERE key=?", (key,))
        return r[0] if r and r[0] is not None else DEFAULT_SETTINGS.get(key, default)

    def get_int(self, key: str) -> int:
        try:
            return int(float(self.get_setting(key)))
        except ValueError:
            return int(DEFAULT_SETTINGS.get(key, "0"))

    def set_setting(self, key: str, value):
        self.conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
        self.commit()

    def log(self, action: str, entity: str = "", entity_id: int | None = None, details=None):
        if details is not None and not isinstance(details, str):
            details = json.dumps(details, ensure_ascii=False, default=str)
        self.conn.execute("INSERT INTO audit_log(username, action, entity, entity_id, details) VALUES (?,?,?,?,?)",
                          (self.current_user, action, entity, entity_id, details))

    # ------------------------------------------------------------------ users
    def has_users(self) -> bool:
        return bool(self.scalar("SELECT COUNT(*) FROM users", default=0))

    def create_admin(self, username: str, password: str):
        if len(password) < 6:
            raise ValueError("كلمة المرور يجب أن تتكون من 6 أحرف على الأقل.")
        if self.has_users():
            raise ValueError("يوجد حساب مدير بالفعل؛ البرنامج يدعم حساباً واحداً.")
        h, s = hash_password(password)
        self.conn.execute("INSERT INTO users(username, pw_hash, salt) VALUES (?,?,?)", (username, h, s))
        self.commit()

    def check_login(self, username: str, password: str) -> bool:
        r = self.one("SELECT pw_hash, salt FROM users WHERE username=?", (username,))
        if not r:
            return False
        ok = secrets.compare_digest(hash_password(password, r["salt"])[0], r["pw_hash"])
        if ok:
            self.current_user = username
        return ok

    def change_password(self, username: str, old: str, new: str):
        if not self.check_login(username, old):
            raise ValueError("كلمة المرور الحالية غير صحيحة.")
        if len(new) < 6:
            raise ValueError("كلمة المرور الجديدة قصيرة جداً.")
        h, s = hash_password(new)
        self.conn.execute("UPDATE users SET pw_hash=?, salt=? WHERE username=?", (h, s, username))
        self.commit()
