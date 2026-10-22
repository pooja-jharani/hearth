"""SQLite engine management. Path comes from HEARTH_DB (default: ./hearth.db)."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine

_engine = None


def init(path: str | None = None, reset: bool = False):
    """Create (or reuse) the engine and make sure tables exist."""
    global _engine
    path = path or os.getenv("HEARTH_DB", "hearth.db")
    if reset and path != ":memory:" and Path(path).exists():
        Path(path).unlink()
    _engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False}
    )
    from . import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(_engine)
    return _engine


def engine():
    return _engine if _engine is not None else init()


@contextmanager
def session():
    with Session(engine(), expire_on_commit=False) as s:
        yield s
