"""Password hashing and session management.

Auth model:
- Passwords hashed with argon2id (memory-hard, current recommended default).
- Sessions are opaque random tokens stored in a cookie + the user_sessions
  table. Server-side revocable; no JWT.
- Cookie is HttpOnly, SameSite=Lax. Secure flag is on when the request
  came in over HTTPS.

Session lifetime: 7 days, slid on each use. Configurable later.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import User, UserSession


SESSION_COOKIE = "sentinel_session"
SESSION_TTL = timedelta(days=7)

_hasher = PasswordHasher()


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    if not plain or len(plain) < 8:
        raise ValueError("Password must be at least 8 characters")
    return _hasher.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    try:
        _hasher.verify(hashed, plain)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo on roundtrip; coerce back to UTC for comparison."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def create_session(
    db: Session,
    *,
    user: User,
    user_agent: str = "",
    ip: str = "",
) -> UserSession:
    token = secrets.token_urlsafe(48)
    sess = UserSession(
        token=token,
        user_id=user.id,
        expires_at=_now() + SESSION_TTL,
        user_agent=user_agent[:255],
        ip=ip[:64],
    )
    db.add(sess)
    user.last_login_at = _now()
    db.commit()
    db.refresh(sess)
    return sess


def revoke_session(db: Session, token: str) -> None:
    sess = db.get(UserSession, token)
    if sess is not None:
        db.delete(sess)
        db.commit()


def get_session(db: Session, token: str) -> Optional[UserSession]:
    sess = db.get(UserSession, token)
    if sess is None:
        return None
    if _as_aware_utc(sess.expires_at) <= _now():
        db.delete(sess)
        db.commit()
        return None
    # Slide expiry on use so active users stay logged in.
    sess.expires_at = _now() + SESSION_TTL
    db.commit()
    return sess


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


def current_user(
    request: Request,
    db: Session = Depends(get_db),
    session_cookie: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE),
) -> User:
    """Resolve the authenticated user from the session cookie. 401 if none."""
    if not session_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Cookie"},
        )
    sess = get_session(db, session_cookie)
    if sess is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid",
        )
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User inactive"
        )
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin required"
        )
    return user


def require_member_or_admin(user: User = Depends(current_user)) -> User:
    if user.role not in ("admin", "member"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Member or admin required"
        )
    return user
