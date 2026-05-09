"""Payments API router."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from arq.connections import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_arq, get_db
from domain.events import PaymentReportedEvent
from domain.models import Order, Payment
from domain.schemas import PaymentBalanceResponse, PaymentReportRequest, PaymentResponse
from services.event_publisher import EventPublisher

router = APIRouter(prefix="/api/payments", tags=["payments"])
PAYMENT_TIMEOUT_HOURS = 24


def _sum_amounts(events: list[Payment], event_type: str) -> Decimal:
    total = Decimal("0.00")
    for event in events:
        if event.event_type == event_type:
            total += Decimal(event.amount)
    return total


async def list_payment_events(session: AsyncSession, order_id: UUID) -> list[Payment]:
    result = await session.execute(
        select(Payment).where(Payment.order_id == order_id).order_by(Payment.created_at.asc())
    )
    return list(result.scalars().all())


async def get_order_or_404(session: AsyncSession, order_id: UUID) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    return order


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


async def derive_payment_balance(session: AsyncSession, order_id: UUID) -> dict[str, Decimal | UUID]:
    order = await get_order_or_404(session, order_id)
    events = await list_payment_events(session, order_id)

    reported_total = _sum_amounts(events, "REPORTED")
    verified_total = _sum_amounts(events, "VERIFIED")
    disputed_total = _sum_amounts(events, "DISPUTED")
    timed_out_total = _sum_amounts(events, "TIMEOUT")
    net_verified_total = max(Decimal("0.00"), verified_total - disputed_total)
    pending_verification = max(Decimal("0.00"), reported_total - verified_total - timed_out_total)
    outstanding_balance = max(Decimal(order.total) - net_verified_total, Decimal("0.00"))

    return {
        "order_id": order.id,
        "order_total": Decimal(order.total),
        "reported_total": reported_total,
        "verified_total": verified_total,
        "disputed_total": disputed_total,
        "timed_out_total": timed_out_total,
        "pending_verification": pending_verification,
        "outstanding_balance": outstanding_balance,
    }


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
