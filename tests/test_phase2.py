"""Phase 2 smoke tests for HustlerOS workflows without live infrastructure."""

from __future__ import annotations

from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_command_parser_order_pattern() -> None:
    from domain.commands import CreateOrderCommand
    from services.command_parser import CommandParser

    command = await CommandParser().parse("2 airtime bundles for Rudo", tenant_id="tenant-a")

    assert isinstance(command, CreateOrderCommand)
    assert command.tenant_id == "tenant-a"
    assert command.customer_name == "Rudo"
    assert command.items == [{"name": "airtime bundles", "quantity": 2}]
    assert command.confidence == 1.0


@pytest.mark.asyncio
async def test_command_parser_payment_pattern() -> None:
    from domain.commands import ReportPaymentCommand
    from services.command_parser import CommandParser

    command = await CommandParser().parse("Paid cash $15", tenant_id="tenant-a")

    assert isinstance(command, ReportPaymentCommand)
    assert command.amount == Decimal("15")
    assert command.method == "CASH"
    assert command.confidence == 1.0


@pytest.mark.asyncio
async def test_commands_parse_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/hustleros")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)

    import config

    config.reset_settings_cache()
    from main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/commands/parse", json={"message": "Paid cash $15", "tenant_id": "tenant-a"})

    assert response.status_code == 200
    body = response.json()
    assert body["command_type"] == "ReportPaymentCommand"
    assert body["confidence"] == 1.0
    assert body["raw"] == "Paid cash $15"


@pytest.mark.asyncio
async def test_alertengine_degrades_after_payment_timeouts() -> None:
    import observability.alertengine as alertengine

    for _ in range(6):
        await alertengine._emit(type="PAYMENT_TIMEOUT", severity="high", service="hustleros", metadata={})

    assert alertengine.get_incident_counts_last_hour()["payment_timeouts"] >= 6
    assert alertengine.health_score_contributor() < 1.0
    assert "payment_timeouts_gt_5_last_hour" in alertengine.get_degradation_reasons()


def test_phase2_modules_import(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/hustleros")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)

    import config

    config.reset_settings_cache()
    import api.commands  # noqa: F401
    import api.customers  # noqa: F401
    import api.orders  # noqa: F401
    import api.payments  # noqa: F401
    import worker  # noqa: F401
    import workers.tasks.outbox_publisher  # noqa: F401
    import workers.tasks.payment_tasks  # noqa: F401
