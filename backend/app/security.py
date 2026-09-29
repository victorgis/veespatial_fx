"""Passwords, session tokens, and copier keys."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import Settings, User

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(value: str) -> bool:
    return bool(value) and len(value) <= 200 and _EMAIL.match(value) is not None


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_b64, dk_b64 = stored.split("$", 1)
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(dk_b64)
    except Exception:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 120_000)
    return hmac.compare_digest(dk, expected)


def make_token(user_id: int) -> str:
    payload = {"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(days=14)}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm="HS256")


def make_ea_key() -> tuple[str, str, str]:
    """Return (full key, sha256 hex, display prefix). The full key is shown once."""
    key = "fxk_" + secrets.token_urlsafe(32)
    digest = hashlib.sha256(key.encode()).hexdigest()
    return key, digest, key[:8]


def current_user(
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Sign in again.")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = jwt.decode(token, get_settings().jwt_secret, algorithms=["HS256"])
        uid = int(payload["sub"])
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Sign in again.") from exc
    user = db.get(User, uid)
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in again.")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Only the account that created this desk can change that.")
    return user


def current_ea_user(
    x_api_key: str | None = Header(None),
    authorization: str | None = Header(None),
    db: Session = Depends(get_db),
) -> User:
    key = (x_api_key or "").strip()
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization.split(" ", 1)[1].strip()
    if not key or len(key) > 200:
        raise HTTPException(status_code=401, detail="The copier key was rejected.")
    digest = hashlib.sha256(key.encode()).hexdigest()
    row = db.query(Settings).filter(Settings.ea_key_hash == digest).one_or_none()
    if row is None:
        raise HTTPException(status_code=401, detail="The copier key was rejected.")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="The copier key was rejected.")
    return user
