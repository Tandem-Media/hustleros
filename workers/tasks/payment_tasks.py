"""Payment worker tasks for HustlerOS Phase 2."""

from __future__ import annotations

import logging
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.events import PaymentTimeoutEvent
from domain.models import Payment
from observability.alertengine import emit_incident
from services.event_publisher import EventPublisher

logger = logging.getLogger(__name__)
publisher = EventPublisher()


def _session_from_ctx(ctx: dict) -> AsyncSession:
    session = ctx.get("db")
    if session is None:
        raise RuntimeError("worker database session is not initialized")
    return session


async def verify_payment_timeout(ctx: dict, order_id: str, payment_id: str, tenant_id: str) -> None:
    """
    Verify a reported payment 24 hours later and append TIMEOUT if still unverified.

    The task is retry-safe. Idempotency key is payment_id + TIMEOUT, represented by
    the generated timeout event's causation_id and a pre-insert existence check.
    """

    db = _session_from_ctx(ctx)
    timeout_causation_id = f"{payment_id}:TIMEOUT"
    try:
        existing_timeout = await db.execute(
            select(Payment).where(
                Payment.order_id == order_id,
                Payment.tenant_id == tenant_id,
                Payment.event_type == "TIMEOUT",
                Payment.causation_id == timeout_causation_id,
            )
        )
        if existing_timeout.scalar_one_or_none() is not None:
            logger.info("payment_timeout_already_recorded payment_id=%s tenant_id=%s", payment_id, tenant_id)
            return

        verified = await db.execute(
            select(Payment).where(
                Payment.order_id == order_id,
                Payment.tenant_id == tenant_id,
                Payment.event_type == "VERIFIED",
                Payment.causation_id == payment_id,
            )
        )
        if verified.scalar_one_or_none() is not None:
            logger.info("payment_timeout_skipped_verified payment_id=%s tenant_id=%s", payment_id, tenant_id)
            return

        reported = await db.execute(
            select(Payment).where(Payment.id == payment_id, Payment.tenant_id == tenant_id, Payment.event_type == "REPORTED")
        )
        reported_payment = reported.scalar_one_or_none()
        if reported_payment is None:
            logger.warning("payment_timeout_reported_event_missing payment_id=%s tenant_id=%s", payment_id, tenant_id)
            return

        timeout_payment = Payment(
            id=uuid4(),
            tenant_id=tenant_id,
            order_id=reported_payment.order_id,
            event_type="TIMEOUT",
            amount=Decimal("0.00"),
            method=reported_payment.method,
            reference=reported_payment.reference,
            reported_by=reported_payment.reported_by,
            verified_by=None,
            correlation_id=reported_payment.correlation_id,
            causation_id=timeout_causation_id,
        )
        db.add(timeout_payment)
        await db.flush()
        await publisher.publish(
            PaymentTimeoutEvent(
                type="PAYMENT_TIMEOUT",
                tenant_id=tenant_id,
                correlation_id=reported_payment.correlation_id,
                causation_id=timeout_causation_id,
                payload={"order_id": order_id, "payment_id": payment_id, "tenant_id": tenant_id, "timeout_after_s": 86400},
            ),
            db,
        )
        await db.commit()
        await emit_incident(
            type="PAYMENT_TIMEOUT",
            severity="high",
            service="hustleros",
            metadata={
                "order_id": order_id,
                "payment_id": payment_id,
                "tenant_id": tenant_id,
                "timeout_after_s": 86400,
            },
        )
        logger.info("payment_timeout_recorded payment_id=%s tenant_id=%s", payment_id, tenant_id)
    except Exception as exc:
        await db.rollback()
        logger.warning("payment_timeout_failed payment_id=%s tenant_id=%s error=%s", payment_id, tenant_id, exc)
        raise
