"""Engine and sessions. Postgres when DATABASE_URL says so, otherwise SQLite."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.config import get_settings

_engine = None


class Base(DeclarativeBase):
    pass


def normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        return "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


def postgres_connect_args(url: str) -> dict:
    """Neon’s pooled host is PgBouncer. Prepared statements collide there, so they stay off."""
    host = url.split("@")[-1].split("/")[0].split("?")[0]
    if "-pooler." in host or host.startswith("pooler."):
        return {"prepare_threshold": None}
    return {}


def get_engine():
    global _engine
    if _engine is not None:
        return _engine
    url = normalize_db_url(get_settings().database_url)
    if url.startswith("sqlite"):
        # Relative sqlite paths are from the process working directory.
        if url.startswith("sqlite:///./"):
            Path("data").mkdir(parents=True, exist_ok=True)
        engine = create_engine(
            url,
            connect_args={"check_same_thread": False, "timeout": 30},
            poolclass=NullPool,
        )

        @event.listens_for(engine, "connect")
        def _fk(dbapi_connection, _record):  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        _engine = engine
        return engine
    _engine = create_engine(url, pool_pre_ping=True, connect_args=postgres_connect_args(url))
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def get_db() -> Iterator[Session]:
    maker = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    db = maker()
    try:
        yield db
    finally:
        db.close()


def session_scope() -> Session:
    maker = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False)
    return maker()


def _ensure_max_open_trades() -> None:
    """create_all does not add columns to a table that already exists."""
    from sqlalchemy import inspect, text

    engine = get_engine()
    insp = inspect(engine)
    if "settings" not in insp.get_table_names():
        return
    columns = {column["name"] for column in insp.get_columns("settings")}
    if "max_open_trades" in columns:
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE settings ADD COLUMN max_open_trades INTEGER NOT NULL DEFAULT 3"))


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(get_engine())
    _ensure_max_open_trades()
    db = session_scope()
    try:
        models.ensure_bot_config(db)
        db.commit()
    finally:
        db.close()
