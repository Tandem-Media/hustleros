"""Arq worker settings and lifecycle hooks for HustlerOS."""

from __future__ import annotations

import logging
from typing import Any

from arq import cron, create_pool
from arq.connections import RedisSettings

from config import get_settings
from db.base import close_db, init_db
from db.session import async_session
from workers.tasks.outbox_publisher import publish_outbox_events
from workers.tasks.payment_tasks import verify_payment_timeout

logger = logging.getLogger(__name__)
settings = get_settings()

QUEUE_NAMES = [
    "hustleros:queue:default",
    "hustleros:queue:payments",
    "hustleros:queue:notifications",
    "hustleros:queue:reconciliation",
]


async def startup(ctx: dict[str, Any]) -> None:
    """Initialize worker database and Redis resources."""

    await init_db(settings.DATABASE_URL)
    ctx["db"] = async_session()
    ctx["redis"] = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
    logger.info("arq_worker_started queue=%s", WorkerSettings.queue_name)


async def shutdown(ctx: dict[str, Any]) -> None:
    """Close worker resources."""

    db = ctx.get("db")
    if db is not None:
        await db.close()
    redis = ctx.get("redis")
    if redis is not None:
        await redis.aclose()
    await close_db()
    logger.info("arq_worker_stopped queue=%s", WorkerSettings.queue_name)


class WorkerSettings:
    """Arq worker settings for HustlerOS Phase 2 background processing."""

    functions = [
        verify_payment_timeout,
        publish_outbox_events,
    ]
    cron_jobs = [
        cron(publish_outbox_events, second={0, 30}),
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    queue_name = "hustleros:queue:default"
    max_jobs = 10
    job_timeout = 300
    retry_jobs = True
    max_tries = 3
    on_startup = startup
    on_shutdown = shutdown
