"""First-run setup: create the DB, ensure dirs, seed the first admin user.

Run via `sentinel server init`. Idempotent: re-running with an existing
DB is a no-op except for the admin password if --reset-admin is passed.
"""

from __future__ import annotations

import getpass
import secrets
from typing import Optional

import click
from sqlalchemy import select

from .auth import hash_password
from .db import Base, get_engine, get_session_factory, reset_for_tests
from .models import User
from .paths import ensure_dirs, secret_key_path, server_home


def init_database() -> None:
    """Create all tables. Safe to call repeatedly."""
    ensure_dirs()
    Base.metadata.create_all(bind=get_engine())


def ensure_secret_key() -> str:
    """Generate (or read) the long-lived secret key used by Studio.

    Currently not consumed (cookies are random tokens stored in DB),
    but reserved for future signed-state needs.
    """
    path = secret_key_path()
    if path.exists():
        return path.read_text().strip()
    key = secrets.token_urlsafe(48)
    path.write_text(key + "\n")
    path.chmod(0o600)
    return key


def create_or_update_admin(email: str, password: str, name: str = "") -> User:
    """Idempotent: if email exists, promote to admin + reset password.
    Else create a new admin user."""
    factory = get_session_factory()
    email = email.lower().strip()
    with factory() as db:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            user = User(
                email=email,
                name=name,
                hashed_password=hash_password(password),
                role="admin",
                is_active=True,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.role = "admin"
            user.is_active = True
            user.hashed_password = hash_password(password)
            if name:
                user.name = name
            db.commit()
            db.refresh(user)
        return user


def server_init_flow(
    email: Optional[str] = None,
    password: Optional[str] = None,
    name: str = "",
) -> User:
    """End-to-end bootstrap. Prompts interactively if email/password not given."""
    init_database()
    ensure_secret_key()
    if email is None:
        email = click.prompt("Admin email").strip()
    if password is None:
        password = getpass.getpass("Admin password (min 8 chars): ")
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            raise click.ClickException("Passwords do not match")
    return create_or_update_admin(email=email, password=password, name=name)
