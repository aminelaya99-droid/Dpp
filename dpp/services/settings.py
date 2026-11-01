from __future__ import annotations

from sqlalchemy.orm import Session

from dpp.models import Setting


def get(s: Session, key: str, default: str = "") -> str:
    row = s.get(Setting, key)
    return row.value if row else default


def get_int(s: Session, key: str, default: int) -> int:
    try:
        return int(get(s, key, str(default)))
    except ValueError:
        return default


def put(s: Session, key: str, value) -> None:
    row = s.get(Setting, key)
    if row is None:
        s.add(Setting(key=key, value=str(value)))
    else:
        row.value = str(value)
    s.commit()
