"""Arq WorkerSettings for Phase 2 queues."""

from __future__ import annotations

from arq.connections import RedisSettings

from config import get_settings
from db.base import close_db, init_db
from workers.tasks.outbox_publisher import publish_outbox_events
from workers.tasks.payment_tasks import verify_payment_timeout

QUEUE_NAMES = [
    "hustleros:queue:default",
    "hustleros:queue:payments",
    "hustleros:queue:notifications",
    "hustleros:queue:reconciliation",
]


async def startup(ctx: dict) -> None:
    settings = get_settings()
    await init_db(settings.DATABASE_URL)
    ctx["settings"] = settings


async def shutdown(_ctx: dict) -> None:
    await close_db()


class WorkerSettings:
    """Worker settings for payment timeout and outbox publication tasks."""

    functions = [verify_payment_timeout, publish_outbox_events]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().REDIS_URL)
    queue_name = "hustleros:queue:payments"
