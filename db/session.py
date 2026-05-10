"""Async session factory and helpers."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from db.base import get_engine

_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return initialized async session factory."""

    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


class _AsyncSessionProxy:
    """Lazy callable proxy matching SQLAlchemy sessionmaker usage."""

    def __call__(self) -> AsyncSession:
        return get_session_factory()()


async_session = _AsyncSessionProxy()


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session with guaranteed cleanup."""

    async with async_session() as session:
        yield session
