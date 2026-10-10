"""
SQLAlchemy engine + session factory.

Works against SQL Server (mssql+pyodbc) in production or SQLite in dev/
tests, controlled entirely by `settings.database_url` -- no code branches
needed for the two backends since SQLAlchemy abstracts the dialect.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from api.config import settings
from api.db.models import Base

_connect_args = {}
if settings.database_url.startswith("sqlite"):
    # Needed for SQLite when used from FastAPI's threaded background tasks.
    _connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Creates all tables if they don't exist. Fine for a case-study /
    early-stage project; swap for Alembic migrations before any schema
    change needs to preserve production data (see README_PHASE2.md)."""
    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
