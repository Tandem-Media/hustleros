"""Payment worker tasks for timeout verification."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from domain.events import PaymentTimeoutEvent
from domain.models import Payment
from observability.alertengine import emit_incident
from services.event_publisher import EventPublisher


async def _verify_payment_timeout_with_session(
    session: AsyncSession,
    order_id: str,
    tenant_id: str,
) -> dict[str, str]:
    from api.payments import derive_payment_balance, list_payment_events

    order_uuid = UUID(order_id)
    events = await list_payment_events(session, order_uuid)
    balance = await derive_payment_balance(session, order_uuid)
    pending = Decimal(balance["pending_verification"])

    if pending <= Decimal("0.00"):
        return {"status": "skipped", "reason": "no pending payment verification"}

    if any(event.event_type == "TIMEOUT" for event in events):
        return {"status": "skipped", "reason": "timeout already recorded"}

    last_report = next((event for event in reversed(events) if event.event_type == "REPORTED"), None)
    if last_report is None:
        return {"status": "skipped", "reason": "no reported payment found"}

    timeout_event = Payment(
        tenant_id=tenant_id,
        order_id=last_report.order_id,
        event_type="TIMEOUT",
        amount=pending,
        method=last_report.method,
        reference=last_report.reference,
        reported_by=last_report.reported_by,
        verified_by=None,
        correlation_id=last_report.correlation_id,
        causation_id=str(last_report.id),
    )
    session.add(timeout_event)
    await session.flush()

    await EventPublisher().publish(
        PaymentTimeoutEvent(
            type="PaymentTimeout",
            tenant_id=timeout_event.tenant_id,
            correlation_id=timeout_event.correlation_id,
            causation_id=str(timeout_event.id),
            payload={
                "order_id": str(timeout_event.order_id),
                "amount": str(timeout_event.amount),
                "reference": timeout_event.reference,
            },
        ),
        session=session,
    )
    await session.commit()
    await emit_incident(
        type="payment_timeouts",
        severity="high",
        metadata={"order_id": order_id, "tenant_id": tenant_id},
    )
    return {"status": "timed_out", "order_id": order_id}


async def verify_payment_timeout(
    ctx: dict | None,
    order_id: str,
    tenant_id: str = "default",
) -> dict[str, str]:
    if ctx and ctx.get("db") is not None:
        return await _verify_payment_timeout_with_session(ctx["db"], order_id, tenant_id)

    from db.session import get_session

    async with get_session() as session:
        return await _verify_payment_timeout_with_session(session, order_id, tenant_id)
