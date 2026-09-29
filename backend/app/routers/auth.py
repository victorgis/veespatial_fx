"""Create an account and sign in."""

import time

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, new_settings
from app.schemas import LoginIn, RegisterIn, TokenOut
from app.present import user_out
from app.security import hash_password, make_token, valid_email, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

_fails: dict[str, list[float]] = {}


def _locked(email: str) -> bool:
    now = time.time()
    recent = [t for t in _fails.get(email, []) if now - t < 600]
    _fails[email] = recent
    return len(recent) >= 8


def _fail(email: str) -> None:
    _fails.setdefault(email, []).append(time.time())


@router.post("/register", response_model=TokenOut)
def register(body: RegisterIn, db: Session = Depends(get_db)) -> TokenOut:
    email = body.email.strip().lower()
    name = body.name.strip()
    if not valid_email(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if not name or len(name) > 80:
        raise HTTPException(status_code=400, detail="Enter your name, up to 80 characters.")
    if len(body.password) < 8:
        raise HTTPException(status_code=400, detail="Use at least 8 characters for the password.")
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="That email already has an account. Sign in instead.")
    is_first = db.query(User).count() == 0
    user = User(email=email, name=name, password_hash=hash_password(body.password), is_admin=is_first)
    db.add(user)
    db.flush()
    db.add(new_settings(user.id))
    db.commit()
    db.refresh(user)
    return TokenOut(token=make_token(user.id), user=user_out(user))


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    email = body.email.strip().lower()
    if _locked(email):
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Wait a few minutes and try again.")
    user = db.query(User).filter(User.email == email).one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        _fail(email)
        raise HTTPException(status_code=401, detail="That email and password do not match.")
    _fails.pop(email, None)
    return TokenOut(token=make_token(user.id), user=user_out(user))
