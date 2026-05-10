"""HustlerOS FastAPI service."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI
from redis.asyncio import Redis

from api.commands import router as commands_router
from api.customers import router as customers_router
from api.deliveries import router as deliveries_router
from api.invoices import router as invoices_router
from api.orders import router as orders_router
from api.payments import router as payments_router
from api.webhooks import router as webhooks_router
from config import get_settings
from db.base import close_db, get_engine, init_db
from observability.alertengine import get_degradation_reasons, get_incident_counts_last_hour, health_score_contributor

logger = logging.getLogger(__name__)

try:
    from fastapi_alertengine import instrument
except Exception:  # noqa: BLE001

    def instrument(app: FastAPI) -> None:
        @app.get("/health/alerts")
        async def _health_alerts_fallback() -> dict[str, Any]:
            score = health_score_contributor()
            return {"status": "ok" if score >= 0.8 else "degraded", "health_score": score, "reasons": get_degradation_reasons()}


QUEUE_NAMES = [
    "hustleros:queue:default",
    "hustleros:queue:payments",
    "hustleros:queue:notifications",
    "hustleros:queue:reconciliation",
    "hustleros:dlq",
]


def _instrument_app(app: FastAPI) -> None:
    if getattr(app.state, "alertengine_instrumented", False):
        return
    instrument(app)
    app.state.alertengine_instrumented = True


class _RedisStub:
    async def ping(self) -> bool:
        return True

    async def llen(self, _name: str) -> int:
        return 0

    async def enqueue_job(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def aclose(self) -> None:
        return None


async def init_redis(redis_url: str) -> tuple[Redis | _RedisStub, bool, float]:
    """Initialize Redis client and run ping."""

    start = time.perf_counter()
    try:
        redis = Redis.from_url(redis_url)
        await redis.ping()
        ping_ms = (time.perf_counter() - start) * 1000
        return redis, True, ping_ms
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis initialization failed: %s", exc)
        return _RedisStub(), False, 0.0


async def init_arq(redis_url: str) -> Any:
    """Initialize Arq Redis pool, falling back to a local no-op stub."""

    try:
        return await create_pool(RedisSettings.from_dsn(redis_url))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Arq initialization failed: %s", exc)
        return _RedisStub()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and cleanup service resources."""

    settings = get_settings()
    app.state.settings = settings
    app.state.started_monotonic = time.monotonic()

    try:
        await init_db(settings.DATABASE_URL)
        app.state.db_connected = True
    except Exception as exc:  # noqa: BLE001
        logger.warning("Database initialization failed: %s", exc)
        app.state.db_connected = False

    redis, redis_connected, redis_ping_ms = await init_redis(settings.REDIS_URL)
    app.state.redis = redis
    app.state.redis_connected = redis_connected
    app.state.redis_ping_ms = redis_ping_ms
    app.state.arq_redis = await init_arq(settings.REDIS_URL)

    try:
        _instrument_app(app)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Alertengine instrumentation failed: %s", exc)
        app.state.alertengine_instrumented = False

    try:
        yield
    finally:
        try:
            await close_db()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Database shutdown failed: %s", exc)
        for resource_name in ("redis", "arq_redis"):
            try:
                resource = getattr(app.state, resource_name, None)
                if resource is not None:
                    await resource.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s shutdown failed: %s", resource_name, exc)


app = FastAPI(title="hustleros", version="0.2.0", lifespan=lifespan)

app.include_router(customers_router)
app.include_router(orders_router)
app.include_router(payments_router)
app.include_router(commands_router)
app.include_router(invoices_router)
app.include_router(deliveries_router)
app.include_router(webhooks_router)
_instrument_app(app)


@app.get("/")
async def root() -> dict[str, str]:
    settings = getattr(app.state, "settings", None)
    version = settings.APP_VERSION if settings else "0.2.0"
    return {"service": "hustleros", "version": version}


@app.get("/status")
async def status() -> dict[str, Any]:
    settings = getattr(app.state, "settings", None)
    environment = settings.ENVIRONMENT if settings else "development"
    version = settings.APP_VERSION if settings else "0.2.0"
    uptime_s = max(0.0, time.monotonic() - getattr(app.state, "started_monotonic", time.monotonic()))

    pool_size = 10
    checked_out = 0
    try:
        pool = get_engine().pool
        if hasattr(pool, "size"):
            pool_size = int(pool.size())
        if hasattr(pool, "checkedout"):
            checked_out = int(pool.checkedout())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Pool metrics unavailable: %s", exc)

    queue_status: dict[str, int] = {name: 0 for name in QUEUE_NAMES}
    redis = getattr(app.state, "redis", None)
    if redis is not None:
        for queue_name in QUEUE_NAMES:
            try:
                queue_status[queue_name] = int(await redis.llen(queue_name))
            except Exception as exc:  # noqa: BLE001
                logger.debug("Queue length unavailable for %s: %s", queue_name, exc)

    incident_counts = get_incident_counts_last_hour()
    business_incidents = {
        "last_1h": int(sum(incident_counts.values())),
        "payment_timeouts": int(incident_counts.get("payment_timeouts", 0)),
        "delivery_failures": int(incident_counts.get("delivery_failures", 0)),
        "webhook_drops": int(incident_counts.get("webhook_drops", 0)),
        "dlq_pushes": int(incident_counts.get("dlq_pushes", 0)),
        "order_creation_failures": int(incident_counts.get("order_creation_failures", 0)),
    }
    health_score = health_score_contributor()

    return {
        "service": "hustleros",
        "version": version,
        "environment": environment,
        "uptime_s": uptime_s,
        "database": {
            "connected": bool(getattr(app.state, "db_connected", False)),
            "pool_size": pool_size,
            "checked_out": checked_out,
        },
        "redis": {
            "connected": bool(getattr(app.state, "redis_connected", False)),
            "ping_ms": float(getattr(app.state, "redis_ping_ms", 0.0)),
        },
        "queues": queue_status,
        "business_incidents": business_incidents,
        "alertengine": {
            "instrumented": bool(getattr(app.state, "alertengine_instrumented", False)),
            "health_url": "/health/alerts",
            "health_score": health_score,
            "degraded": health_score < 0.8,
            "reasons": get_degradation_reasons(),
        },
    }
