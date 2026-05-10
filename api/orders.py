"""Orders API for HustlerOS Phase 2."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from domain.events import OrderCreatedEvent, OrderStatusChangedEvent
from domain.models import Customer, Order
from domain.schemas import OrderRequest, OrderResponse, OrderStatusRequest, OrderWithCustomerResponse
from observability.alertengine import emit_incident
from services.event_publisher import EventPublisher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/orders", tags=["orders"])
publisher = EventPublisher()

_ALLOWED_TRANSITIONS = {
    "PENDING": {"CONFIRMED", "CANCELLED"},
    "CONFIRMED": {"DELIVERED", "CANCELLED"},
}


def _normalize_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _order_payload(order: Order) -> dict[str, str]:
    return {
        "order_id": str(order.id),
        "tenant_id": order.tenant_id,
        "customer_id": str(order.customer_id),
        "status": order.status,
        "total": str(order.total),
    }


async def _emit_order_failure(req: OrderRequest, reason: str) -> None:
    await emit_incident(
        type="ORDER_CREATION_FAILED",
        severity="high",
        service="hustleros",
        metadata={"tenant_id": req.tenant_id, "customer_id": str(req.customer_id), "reason": reason},
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(req: OrderRequest, db: AsyncSession = Depends(get_db)) -> Order:
    """Create an order after validating tenant-owned customer and totals."""

    try:
        customer_result = await db.execute(select(Customer).where(Customer.id == req.customer_id, Customer.tenant_id == req.tenant_id))
        customer = customer_result.scalar_one_or_none()
        if customer is None:
            await _emit_order_failure(req, "customer_not_found")
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")

        expected_total = _normalize_money(sum((_normalize_money(item.total) for item in req.items), Decimal("0.00")))
        requested_total = _normalize_money(req.total)
        if expected_total != requested_total:
            await _emit_order_failure(req, "total_mismatch")
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Order total does not match item totals")

        correlation_id = req.correlation_id or str(uuid4())
        order = Order(
            tenant_id=req.tenant_id,
            customer_id=req.customer_id,
            items=[item.model_dump(mode="json") for item in req.items],
            status="PENDING",
            total=requested_total,
            correlation_id=correlation_id,
        )
        db.add(order)
        await db.flush()
        await publisher.publish(
            OrderCreatedEvent(
                type="ORDER_CREATED",
                tenant_id=order.tenant_id,
                correlation_id=order.correlation_id,
                causation_id=str(order.id),
                payload=_order_payload(order),
            ),
            db,
        )
        await db.commit()
        await db.refresh(order)
        return order
    except HTTPException:
        raise
    except Exception as exc:
        await db.rollback()
        logger.warning("order_creation_failed tenant_id=%s customer_id=%s error=%s", req.tenant_id, req.customer_id, exc)
        asyncio.create_task(
            emit_incident(
                type="ORDER_CREATION_FAILED",
                severity="high",
                service="hustleros",
                metadata={"tenant_id": req.tenant_id, "customer_id": str(req.customer_id), "reason": str(exc)},
            )
        )
        raise


@router.get("/{order_id}", response_model=OrderWithCustomerResponse)
async def get_order(order_id: UUID, tenant_id: str = Query(...), db: AsyncSession = Depends(get_db)) -> OrderWithCustomerResponse:
    """Return a single order with customer name when tenant ownership matches."""

    result = await db.execute(
        select(Order, Customer.name).join(Customer, Customer.id == Order.customer_id).where(Order.id == order_id, Order.tenant_id == tenant_id)
    )
    row = result.one_or_none()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    order, customer_name = row
    return OrderWithCustomerResponse.model_validate({**OrderResponse.model_validate(order).model_dump(), "customer_name": customer_name})


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    tenant_id: str = Query(...),
    status_filter: str | None = Query(None, alias="status"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[Order]:
    """List tenant-scoped orders with optional status filtering."""

    stmt = select(Order).where(Order.tenant_id == tenant_id)
    if status_filter is not None:
        stmt = stmt.where(Order.status == status_filter)
    result = await db.execute(stmt.offset(skip).limit(limit))
    return list(result.scalars().all())


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: UUID,
    req: OrderStatusRequest,
    tenant_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
) -> Order:
    """Validate and apply a safe order status transition."""

    result = await db.execute(select(Order).where(Order.id == order_id, Order.tenant_id == tenant_id))
    order = result.scalar_one_or_none()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    new_status = req.status.upper()
    allowed = _ALLOWED_TRANSITIONS.get(order.status, set())
    if new_status not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid order status transition")

    old_status = order.status
    order.status = new_status
    await db.flush()
    await publisher.publish(
        OrderStatusChangedEvent(
            type="ORDER_STATUS_CHANGED",
            tenant_id=order.tenant_id,
            correlation_id=order.correlation_id,
            causation_id=str(order.id),
            payload={**_order_payload(order), "old_status": old_status, "new_status": new_status},
        ),
        db,
    )
    await db.commit()
    await db.refresh(order)
    return order
