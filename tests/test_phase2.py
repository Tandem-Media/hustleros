from __future__ import annotations

import importlib
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from api.payments import derive_payment_balance, report_payment_event
from domain.schemas import PaymentReportRequest
from services.command_parser import CommandParser
from workers.tasks.payment_tasks import verify_payment_timeout


class DummyArq:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def enqueue_job(self, function: str, *args, **kwargs) -> None:
        self.calls.append({"function": function, "args": args, "kwargs": kwargs})


class FakeScalarResult:
    def __init__(self, items):
        self._items = items

    def all(self) -> list[object]:
        return list(self._items)


class FakeExecuteResult:
    def __init__(self, items):
        self._items = items

    def scalars(self) -> FakeScalarResult:
        return FakeScalarResult(self._items)


class FakeSession:
    def __init__(self, order, payments=None):
        self.order = order
        self.payments = list(payments or [])
        self.outbox = []
        self.commits = 0

    def add(self, item: object) -> None:
        if item.__class__.__name__ == "Payment":
            if getattr(item, "id", None) is None:
                item.id = uuid4()
            if getattr(item, "created_at", None) is None:
                item.created_at = datetime.now(timezone.utc)
            self.payments.append(item)
        else:
            self.outbox.append(item)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        return None

    async def flush(self):
        return None

    async def refresh(self, _item):
        return None

    async def get(self, model, key):
        if model.__name__ == "Order" and key == self.order.id:
            return self.order
        return None

    async def execute(self, _query):
        return FakeExecuteResult(self.payments)


@pytest.mark.asyncio
async def test_command_parser_parses_customer_and_payment_commands() -> None:
    parser = CommandParser()

    customer_command = parser.parse("create customer Alice phone +2348000000000", correlation_id="corr-1")
    payment_command = parser.parse("report payment order order-123 amount 49.99 method cash")

    assert customer_command.name == "Alice"
    assert customer_command.phone == "+2348000000000"
    assert payment_command.amount == Decimal("49.99")
    assert payment_command.method == "cash"


@pytest.mark.asyncio
async def test_report_payment_event_schedules_timeout_with_defer_until() -> None:
    order_id = uuid4()
    session = FakeSession(
        order=SimpleNamespace(id=order_id, total=Decimal("150.00")),
    )
    arq = DummyArq()

    payment = await report_payment_event(
        session,
        arq,
        PaymentReportRequest(
            tenant_id="tenant-1",
            order_id=order_id,
            amount=Decimal("40.00"),
            method="cash",
            reference="ref-1",
            reported_by="tester",
            correlation_id="corr-1",
            causation_id="cause-1",
        ),
    )

    assert payment.event_type == "REPORTED"
    assert arq.calls[0]["function"] == "verify_payment_timeout"
    assert "_defer_until" in arq.calls[0]["kwargs"]


@pytest.mark.asyncio
async def test_derive_payment_balance_uses_events_only() -> None:
    order_id = uuid4()
    payments = [
        SimpleNamespace(event_type="REPORTED", amount=Decimal("100.00"), order_id=order_id),
        SimpleNamespace(event_type="VERIFIED", amount=Decimal("25.00"), order_id=order_id),
        SimpleNamespace(event_type="DISPUTED", amount=Decimal("5.00"), order_id=order_id),
        SimpleNamespace(event_type="TIMEOUT", amount=Decimal("10.00"), order_id=order_id),
    ]
    session = FakeSession(order=SimpleNamespace(id=order_id, total=Decimal("150.00")), payments=payments)

    balance = await derive_payment_balance(session, order_id)

    assert balance["reported_total"] == Decimal("100.00")
    assert balance["verified_total"] == Decimal("25.00")
    assert balance["outstanding_balance"] == Decimal("130.00")


@pytest.mark.asyncio
async def test_verify_payment_timeout_appends_timeout_event() -> None:
    order_id = uuid4()
    reported_payment = SimpleNamespace(
        id=uuid4(),
        tenant_id="tenant-1",
        order_id=order_id,
        event_type="REPORTED",
        amount=Decimal("55.00"),
        method="transfer",
        reference="pay-1",
        reported_by="agent",
        correlation_id="corr-55",
        created_at=datetime.now(timezone.utc),
    )
    session = FakeSession(order=SimpleNamespace(id=order_id, total=Decimal("100.00")), payments=[reported_payment])

    result = await verify_payment_timeout({"db": session}, str(order_id), "tenant-1")

    assert result["status"] == "timed_out"
    assert any(event.event_type == "TIMEOUT" for event in session.payments)


@pytest.mark.asyncio
async def test_health_alerts_degrade_after_business_incident(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://user:pass@localhost/hustleros")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)

    config = importlib.import_module("config")
    config.reset_settings_cache()
    alertengine = importlib.import_module("observability.alertengine")
    alertengine.reset_incident_counts()
    main = importlib.import_module("main")

    async def _fake_init_db(_url: str):
        return SimpleNamespace(pool=SimpleNamespace(size=lambda: 10, checkedout=lambda: 0))

    async def _fake_init_redis(_url: str):
        redis = SimpleNamespace(llen=lambda _name: 0, aclose=lambda: None)
        return redis, True, 0.0

    monkeypatch.setattr(main, "init_db", _fake_init_db)
    monkeypatch.setattr(main, "init_redis", _fake_init_redis)

    await alertengine.emit_incident(type="payment_timeouts", severity="high")

    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        response = await client.get("/health/alerts")

    body = response.json()
    assert response.status_code == 200
    assert body["health_score"] < 1.0
