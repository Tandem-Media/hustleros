"""Phase 1 smoke tests without live infrastructure."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_app_imports() -> None:
    importlib.import_module("main")


@pytest.mark.asyncio
async def test_config_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/hustleros")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)

    config = importlib.import_module("config")
    config.reset_settings_cache()
    settings = config.get_settings()

    assert settings.DATABASE_URL.startswith("postgresql+asyncpg://")
    assert settings.REDIS_URL.startswith("redis://")
    assert settings.SECRET_KEY == "x" * 32


@pytest.mark.asyncio
async def test_models_import() -> None:
    models = importlib.import_module("domain.models")

    assert all(
        hasattr(models, name)
        for name in [
            "Customer",
            "Order",
            "Invoice",
            "Payment",
            "Delivery",
            "BusinessEvent",
            "OutboxEvent",
            "WebhookReceipt",
        ]
    )


@pytest.mark.asyncio
async def test_events_import() -> None:
    events = importlib.import_module("domain.events")

    assert all(
        hasattr(events, name)
        for name in [
            "DomainEvent",
            "OrderCreatedEvent",
            "InvoiceSentEvent",
            "PaymentReportedEvent",
            "PaymentVerifiedEvent",
            "PaymentDisputedEvent",
            "PaymentTimeoutEvent",
            "DeliveryAssignedEvent",
            "DeliveryFailedEvent",
            "CustomerNotifiedEvent",
        ]
    )


@pytest.mark.asyncio
async def test_commands_import() -> None:
    commands = importlib.import_module("domain.commands")

    assert all(
        hasattr(commands, name)
        for name in [
            "Command",
            "CreateOrderCommand",
            "CreateInvoiceCommand",
            "ReportPaymentCommand",
            "AssignDeliveryCommand",
            "NotifyCustomerCommand",
            "UnknownCommand",
        ]
    )


async def _build_app(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/hustleros")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)

    config = importlib.import_module("config")
    config.reset_settings_cache()
    main = importlib.import_module("main")

    async def _fake_init_db(_url: str) -> SimpleNamespace:
        return SimpleNamespace(pool=SimpleNamespace(size=lambda: 10, checkedout=lambda: 0))

    fake_redis = SimpleNamespace(
        ping=AsyncMock(return_value=True),
        llen=AsyncMock(return_value=0),
        aclose=AsyncMock(return_value=None),
    )

    async def _fake_init_redis(_url: str):
        return fake_redis, True, 0.0

    monkeypatch.setattr(main, "init_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis", _fake_init_redis)

    return main.app


@pytest.mark.asyncio
async def test_health_alerts_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    app = await _build_app(monkeypatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health/alerts")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_status_returns_200(monkeypatch: pytest.MonkeyPatch) -> None:
    app = await _build_app(monkeypatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/status")

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_emit_incident_does_not_raise() -> None:
    alertengine = importlib.import_module("observability.alertengine")

    await alertengine.emit_incident(type="payment_timeouts", severity="high")


@pytest.mark.asyncio
async def test_event_publisher_does_not_raise() -> None:
    events = importlib.import_module("domain.events")
    publisher_module = importlib.import_module("services.event_publisher")

    session = SimpleNamespace(add=Mock(), flush=AsyncMock())
    publisher = publisher_module.EventPublisher()

    event = events.DomainEvent(
        type="PaymentReported",
        tenant_id="default",
        correlation_id="corr-1",
        causation_id="cause-1",
        payload={"amount": "10.00"},
    )
    await publisher.publish(event=event, session=session)

    assert session.flush.await_count == 1


@pytest.mark.asyncio
async def test_status_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    app = await _build_app(monkeypatch)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/status")

    body = response.json()
    assert {
        "service",
        "version",
        "environment",
        "uptime_s",
        "database",
        "redis",
        "queues",
        "business_incidents",
        "alertengine",
    }.issubset(body.keys())
