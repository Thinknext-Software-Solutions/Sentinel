"""SQLAlchemy engine + session factory.

SQLite at server_home()/studio.db. Foreign keys turned on per connection
(SQLite default is off, which silently breaks FK constraints).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from .paths import db_path, ensure_dirs


class UtcDateTime(TypeDecorator):
    """SQLite-friendly DateTime that always roundtrips as aware UTC.

    SQLite's native datetime support is naive strings. SQLAlchemy
    DateTime(timezone=True) on SQLite returns naive datetimes on read,
    which then serialize without a tz suffix and get misinterpreted by
    JS as local time. This decorator stores everything as UTC and tags
    incoming values from the DB with timezone.utc so consumers see
    aware datetimes.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: Optional[datetime], dialect
    ) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            # Caller passed a naive datetime; we assume UTC.
            return value
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(
        self, value: Optional[datetime], dialect
    ) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    """Base class for all ORM models."""


_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        ensure_dirs()
        url = f"sqlite:///{db_path()}"
        _engine = create_engine(
            url,
            future=True,
            echo=False,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(_engine, "connect")
        def _fk_on(dbapi_connection, _conn_record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            bind=get_engine(), autoflush=False, autocommit=False, future=True
        )
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Open a transactional session, commit on success, rollback on error."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a Session and closes it after."""
    factory = get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        session.close()


def reset_for_tests() -> None:
    """Test hook: drop the cached engine/factory so a fresh DB URL takes effect."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
