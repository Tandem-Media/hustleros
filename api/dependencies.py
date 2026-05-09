"""Shared FastAPI dependencies for database and arq access."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from arq.connections import ArqRedis, RedisSettings, create_pool
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from db.session import get_session

logger = logging.getLogger(__name__)


class _ArqStub:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []

    async def enqueue_job(self, function: str, *args: Any, **kwargs: Any) -> None:
        self.enqueued.append({"function": function, "args": args, "kwargs": kwargs})
        return None

    async def aclose(self) -> None:
        return None


async def get_db() -> AsyncIterator[AsyncSession]:
    """Yield an async database session."""

    async with get_session() as session:
        yield session


async def get_arq(request: Request) -> ArqRedis | _ArqStub:
    """Return a cached arq pool for the current app."""

    cached_pool = getattr(request.app.state, "arq", None)
    if cached_pool is not None:
        return cached_pool

    settings = get_settings()
    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Arq pool initialization failed: %s", exc)
        pool = _ArqStub()

    request.app.state.arq = pool
    return pool
