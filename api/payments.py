"""Payments API router."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_arq, get_db
from domain.events import PaymentReportedEvent
from domain.models import Payment
from domain.schemas import PaymentBalanceResponse, PaymentReportRequest, PaymentResponse
from services.event_publisher import EventPublisher
from services.payment_reporting import derive_payment_balance, get_order_or_404, list_payment_events

router = APIRouter(prefix="/api/payments", tags=["payments"])
PAYMENT_TIMEOUT_HOURS = 24


async def report_payment_event(
    session: AsyncSession,
    arq: ArqRedis | Any,
    payload: PaymentReportRequest,
) -> Payment:
    await get_order_or_404(session, payload.order_id)

    payment = Payment(
        tenant_id=payload.tenant_id,
        order_id=payload.order_id,
        event_type="REPORTED",
        amount=payload.amount,
        method=payload.method,
        reference=payload.reference,
        reported_by=payload.reported_by,
        verified_by=None,
        correlation_id=payload.correlation_id,
        causation_id=payload.causation_id,
    )
    session.add(payment)
    await session.flush()

    await EventPublisher().publish(
        PaymentReportedEvent(
            type="PaymentReported",
            tenant_id=payment.tenant_id,
            correlation_id=payment.correlation_id,
            causation_id=str(payment.id),
            payload={
                "order_id": str(payment.order_id),
                "payment_id": str(payment.id),
                "amount": str(payment.amount),
                "method": payment.method,
                "reference": payment.reference,
            },
        ),
        session=session,
    )
    await session.commit()
    await session.refresh(payment)

    defer_until = payment.created_at + timedelta(hours=PAYMENT_TIMEOUT_HOURS)
    await arq.enqueue_job(
        "verify_payment_timeout",
        str(payment.order_id),
        payment.tenant_id,
        _defer_until=defer_until,
    )
    return payment


@router.post("/report", response_model=PaymentResponse, status_code=status.HTTP_202_ACCEPTED)
async def report_payment(
    payload: PaymentReportRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    arq: Annotated[ArqRedis | Any, Depends(get_arq)],
) -> Payment:
    return await report_payment_event(session, arq, payload)


@router.get("/{order_id}", response_model=list[PaymentResponse])
async def get_payments(
    order_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> list[Payment]:
    await get_order_or_404(session, order_id)
    return await list_payment_events(session, order_id)


@router.get("/{order_id}/balance", response_model=PaymentBalanceResponse)
async def get_payment_balance(
    order_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, Decimal | UUID]:
    return await derive_payment_balance(session, order_id)
