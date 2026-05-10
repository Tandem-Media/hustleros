"""Payment reporting API for HustlerOS Phase 2."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from arq import ArqRedis
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_arq, get_db
from domain.events import PaymentReportedEvent
from domain.models import Order, Payment
from domain.schemas import PaymentBalanceResponse, PaymentReportRequest, PaymentReportResponse, PaymentResponse
from services.event_publisher import EventPublisher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])
publisher = EventPublisher()

_PAYMENT_METHODS = {"CASH", "ECOCASH", "INNBUCKS", "OMARI", "OTHER"}


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


@router.post("/report", response_model=PaymentReportResponse, status_code=status.HTTP_201_CREATED)
async def report_payment(
    req: PaymentReportRequest,
    db: AsyncSession = Depends(get_db),
    arq: ArqRedis = Depends(get_arq),
) -> Payment:
    """Append a reported payment event and schedule 24-hour timeout verification."""

    method = req.method.upper()
    if method not in _PAYMENT_METHODS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported payment method")

    order_result = await db.execute(select(Order).where(Order.id == req.order_id, Order.tenant_id == req.tenant_id))
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    if req.reference is not None:
        duplicate_result = await db.execute(
            select(Payment).where(Payment.order_id == req.order_id, Payment.reference == req.reference, Payment.event_type == "REPORTED")
        )
        if duplicate_result.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Payment reference already reported for order")

    payment_id = uuid4()
    correlation_id = str(uuid4())
    payment = Payment(
        id=payment_id,
        tenant_id=req.tenant_id,
        order_id=req.order_id,
        event_type="REPORTED",
        amount=_money(req.amount),
        method=method,
        reference=req.reference,
        reported_by=req.reported_by,
        verified_by=None,
        correlation_id=correlation_id,
        causation_id=str(order.id),
    )
    db.add(payment)
    await db.flush()
    await publisher.publish(
        PaymentReportedEvent(
            type="PAYMENT_REPORTED",
            tenant_id=req.tenant_id,
            correlation_id=correlation_id,
            causation_id=str(payment_id),
            payload={
                "payment_id": str(payment_id),
                "order_id": str(req.order_id),
                "amount": str(payment.amount),
                "method": method,
                "reference": req.reference,
                "reported_by": req.reported_by,
            },
        ),
        db,
    )
    await db.commit()
    await arq.enqueue_job(
        "verify_payment_timeout",
        order_id=str(req.order_id),
        payment_id=str(payment_id),
        tenant_id=req.tenant_id,
        _defer_until=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    await db.refresh(payment)
    return payment


@router.get("/{order_id}", response_model=list[PaymentResponse])
async def get_payment_history(order_id: UUID, tenant_id: str = Query(...), db: AsyncSession = Depends(get_db)) -> list[Payment]:
    """Return append-only payment event history for an order."""

    order_result = await db.execute(select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id))
    if order_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    result = await db.execute(
        select(Payment).where(Payment.order_id == order_id, Payment.tenant_id == tenant_id).order_by(Payment.created_at.asc())
    )
    return list(result.scalars().all())


@router.get("/{order_id}/balance", response_model=PaymentBalanceResponse)
async def get_payment_balance(order_id: UUID, tenant_id: str = Query(...), db: AsyncSession = Depends(get_db)) -> PaymentBalanceResponse:
    """Compute derived payment balance from the append-only event log."""

    order_result = await db.execute(select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id))
    order = order_result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    events_result = await db.execute(
        select(Payment).where(Payment.order_id == order_id, Payment.tenant_id == tenant_id).order_by(Payment.created_at.asc())
    )
    events = list(events_result.scalars().all())

    total_reported = _money(sum((_money(event.amount) for event in events if event.event_type == "REPORTED"), Decimal("0.00")))
    total_verified = _money(sum((_money(event.amount) for event in events if event.event_type == "VERIFIED"), Decimal("0.00")))
    total_disputed = _money(sum((_money(event.amount) for event in events if event.event_type == "DISPUTED"), Decimal("0.00")))
    outstanding = _money(_money(order.total) - total_verified)
    return PaymentBalanceResponse(
        order_id=order_id,
        total_reported=total_reported,
        total_verified=total_verified,
        total_disputed=total_disputed,
        outstanding=outstanding,
        events=[PaymentResponse.model_validate(event) for event in events],
    )
