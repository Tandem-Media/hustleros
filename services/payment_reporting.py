"""Shared payment reporting helpers for API and workers."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.models import Order, Payment


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


async def derive_payment_balance(session: AsyncSession, order_id: UUID) -> dict[str, Decimal | UUID]:
    order = await get_order_or_404(session, order_id)
    events = await list_payment_events(session, order_id)

    reported_total = _sum_amounts(events, "REPORTED")
    verified_total = _sum_amounts(events, "VERIFIED")
    disputed_total = _sum_amounts(events, "DISPUTED")
    timed_out_total = _sum_amounts(events, "TIMEOUT")
    verified_after_disputes = max(Decimal("0.00"), verified_total - disputed_total)
    pending_verification = max(Decimal("0.00"), reported_total - verified_total - timed_out_total)
    outstanding_balance = max(Decimal(order.total) - verified_after_disputes, Decimal("0.00"))

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
