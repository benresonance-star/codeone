from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _database_url() -> str:
    if os.getenv("DATABASE_URL"):
        url = os.environ["DATABASE_URL"]
        return url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url
    if os.getenv("POSTGRES_URL"):
        url = os.environ["POSTGRES_URL"]
        return url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url

    root = Path(__file__).resolve()
    for parent in root.parents:
        if (parent / "backend").exists() or (parent / "Spec").exists():
            return f"sqlite:///{(parent / 'runtime-data' / 'ncc_ingestion.db').as_posix()}"
    return "sqlite:///./runtime-data/ncc_ingestion.db"


DATABASE_URL = _database_url()
CONNECT_ARGS = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, future=True, connect_args=CONNECT_ARGS)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def prepare_storage() -> None:
    if DATABASE_URL.startswith("sqlite:///"):
        db_path = DATABASE_URL.replace("sqlite:///", "", 1)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)


def init_db() -> None:
    from app.models import persistence  # noqa: F401

    prepare_storage()
    Base.metadata.create_all(bind=engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
