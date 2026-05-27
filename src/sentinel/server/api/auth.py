"""Auth endpoints: login, logout, current-user."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..auth import (
    SESSION_COOKIE,
    create_session,
    current_user,
    hash_password,
    revoke_session,
    verify_password,
)
from ..db import get_db
from ..models import User
from ..schemas import LoginRequest, UserOut


router = APIRouter(prefix="/api/auth", tags=["auth"])


def _set_session_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=token,
        max_age=60 * 60 * 24 * 7,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


@router.post("/login", response_model=UserOut)
def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    user = db.execute(
        select(User).where(User.email == body.email.lower())
    ).scalar_one_or_none()
    if user is None or not verify_password(user.hashed_password, body.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled"
        )
    sess = create_session(
        db,
        user=user,
        user_agent=request.headers.get("user-agent", ""),
        ip=(request.client.host if request.client else ""),
    )
    secure = request.url.scheme == "https"
    _set_session_cookie(response, sess.token, secure=secure)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_session(db, token)
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user
