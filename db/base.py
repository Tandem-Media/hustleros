"""Database engine and SQLAlchemy declarative base."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import DeclarativeBase

_engine: AsyncEngine | None = None


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""


async def init_db(database_url: str) -> AsyncEngine:
    """Initialize and cache the async SQLAlchemy engine."""

    global _engine
    if _engine is None:
        _engine = create_async_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_engine() -> AsyncEngine:
    """Return initialized async engine."""

    if _engine is None:
        raise RuntimeError("Database engine has not been initialized")
    return _engine


async def close_db() -> None:
    """Dispose the async engine if initialized."""

    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
