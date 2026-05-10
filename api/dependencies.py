"""Centralized FastAPI dependencies for HustlerOS APIs."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from arq import ArqRedis
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import async_session


async def get_arq(request: Request) -> ArqRedis:
    """Return the app-scoped Arq Redis pool."""

    return request.app.state.arq_redis


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async database session for API handlers."""

    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
