"""محرك SQLite وجلسة التطبيق الوحيدة (تطبيق سطح مكتب لمستخدم واحد)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from dpp.models import Base

_engine: Optional[Engine] = None
_factory: Optional[sessionmaker] = None
_session: Optional[Session] = None
_path: Optional[str] = None


def _fk_pragma(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.close()


def init_db(path: str | Path | None = None, seed: bool = True) -> Session:
    """يفتح قاعدة البيانات (":memory:" للاختبارات) وينشئ الجداول والبيانات الأولية."""
    global _engine, _factory, _session, _path
    reset_engine()
    if path is None:
        from dpp.config import db_path
        path = db_path()
    _path = str(path)
    url = "sqlite://" if _path == ":memory:" else f"sqlite:///{_path}"
    _engine = create_engine(url, future=True)
    event.listen(_engine, "connect", _fk_pragma)
    Base.metadata.create_all(_engine)
    _factory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    _session = _factory()
    if seed:
        from dpp.db.seed import seed_if_empty
        seed_if_empty(_session)
    return _session


def get_session() -> Session:
    if _session is None:
        return init_db()
    return _session


def current_db_path() -> Optional[str]:
    return _path


def reset_engine() -> None:
    global _engine, _factory, _session
    if _session is not None:
        _session.close()
    if _engine is not None:
        _engine.dispose()
    _engine = _factory = _session = None
