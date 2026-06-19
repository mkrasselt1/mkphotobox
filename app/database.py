"""SQLite database engine with WAL mode, optimized for RPi3."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event as sa_event
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_config

_engine = None


def get_engine():
    global _engine
    if _engine is not None:
        return _engine

    cfg = get_config()
    db_path = cfg["database"]["path"]

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
        pool_size=1,
        pool_pre_ping=True,
    )

    @sa_event.listens_for(_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA cache_size=-8000")  # 8 MB
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA temp_store=MEMORY")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return _engine


def create_db():
    """Create all tables from SQLModel metadata."""
    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_session():
    """Dependency for FastAPI: yields a DB session."""
    engine = get_engine()
    with Session(engine) as session:
        yield session
