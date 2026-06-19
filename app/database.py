"""SQLite database engine with WAL mode, optimized for RPi3."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import event as sa_event, inspect as sa_inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import get_config

logger = logging.getLogger(__name__)

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
    """Create missing tables, then additively migrate missing columns.

    SQLModel's create_all only creates *missing tables* — it never adds new
    columns to an existing table. _auto_migrate() closes that gap for the common
    case (new model fields), so the box self-heals across app updates without a
    manual migration step. (Renames/drops/type-changes still need Alembic.)
    """
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    _auto_migrate(engine)


def _auto_migrate(engine) -> None:
    insp = sa_inspect(engine)
    existing_tables = set(insp.get_table_names())
    for table in SQLModel.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # freshly created by create_all
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            coltype = col.type.compile(dialect=engine.dialect)
            default_clause = ""
            d = col.default
            if d is not None and getattr(d, "is_scalar", False):
                val = d.arg
                if isinstance(val, bool):
                    default_clause = f" DEFAULT {1 if val else 0}"
                elif isinstance(val, (int, float)):
                    default_clause = f" DEFAULT {val}"
                elif isinstance(val, str):
                    default_clause = " DEFAULT '" + val.replace("'", "''") + "'"
            # Add as NULLable (no NOT NULL) so existing rows stay valid.
            ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {coltype}{default_clause}'
            try:
                with engine.begin() as conn:
                    conn.execute(text(ddl))
                logger.info("auto-migrate: added column %s.%s", table.name, col.name)
            except Exception:
                logger.exception("auto-migrate: could not add %s.%s", table.name, col.name)


def get_session():
    """Dependency for FastAPI: yields a DB session."""
    engine = get_engine()
    with Session(engine) as session:
        yield session
