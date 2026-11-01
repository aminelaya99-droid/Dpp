"""حساب المسؤول الوحيد: تشفير كلمة السر بـ PBKDF2-SHA256 مع ملح عشوائي."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from dpp.models import User

ITERATIONS = 200_000


def hash_password(password: str, salt: bytes | None = None, iterations: int = ITERATIONS) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, it, salt_b64, dk_b64 = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt_b64), int(it))
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except (ValueError, TypeError):
        return False


def has_admin(s: Session) -> bool:
    return s.scalar(select(User.id).limit(1)) is not None


def create_admin(s: Session, username: str, password: str) -> User:
    if has_admin(s):
        raise ValueError("حساب المسؤول موجود مسبقاً")
    if len(password) < 4:
        raise ValueError("كلمة السر قصيرة جداً (4 أحرف على الأقل)")
    if not username.strip():
        raise ValueError("اسم المستخدم مطلوب")
    u = User(username=username.strip(), password_hash=hash_password(password))
    s.add(u)
    s.commit()
    return u


def authenticate(s: Session, username: str, password: str) -> User | None:
    u = s.scalar(select(User).where(User.username == username.strip()))
    if u and verify_password(password, u.password_hash):
        return u
    return None


def admin(s: Session) -> User | None:
    return s.scalar(select(User).limit(1))


def check_admin_password(s: Session, password: str) -> bool:
    u = admin(s)
    return bool(u and verify_password(password, u.password_hash))


def change_password(s: Session, old: str, new: str) -> None:
    u = admin(s)
    if not u or not verify_password(old, u.password_hash):
        raise ValueError("كلمة السر الحالية غير صحيحة")
    if len(new) < 4:
        raise ValueError("كلمة السر الجديدة قصيرة جداً")
    u.password_hash = hash_password(new)
    s.commit()
