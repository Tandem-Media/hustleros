"""Orders API router."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from domain.events import OrderCreatedEvent, OrderUpdatedEvent
from domain.models import Order
from domain.schemas import OrderPatchRequest, OrderRequest, OrderResponse
from services.event_publisher import EventPublisher

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _build_order_event_payload(order: Order) -> dict[str, str | dict[str, object]]:
    return {
        "order_id": str(order.id),
        "customer_id": str(order.customer_id),
        "status": order.status,
        "total": str(order.total),
        "items": jsonable_encoder(order.items),
    }


async def create_order_record(session: AsyncSession, payload: OrderRequest) -> Order:
    order = Order(**payload.model_dump())
    session.add(order)
    await session.flush()
    await EventPublisher().publish(
        OrderCreatedEvent(
            type="OrderCreated",
            tenant_id=order.tenant_id,
            correlation_id=order.correlation_id,
            causation_id=str(order.id),
            payload=_build_order_event_payload(order),
        ),
        session=session,
    )
    await session.commit()
    await session.refresh(order)
    return order


async def list_order_records(session: AsyncSession, tenant_id: str | None = None) -> list[Order]:
    query = select(Order).order_by(Order.created_at.asc())
    if tenant_id:
        query = query.where(Order.tenant_id == tenant_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_order_record(session: AsyncSession, order_id: UUID) -> Order:
    order = await session.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="order not found")
    return order


async def update_order_record(session: AsyncSession, order_id: UUID, payload: OrderPatchRequest) -> Order:
    order = await get_order_record(session, order_id)
    updates = payload.model_dump(exclude_none=True)
    if not updates:
        return order

    for field_name, value in updates.items():
        setattr(order, field_name, value)

    await session.flush()
    await EventPublisher().publish(
        OrderUpdatedEvent(
            type="OrderUpdated",
            tenant_id=order.tenant_id,
            correlation_id=order.correlation_id,
            causation_id=str(order.id),
            payload={
                "order_id": str(order.id),
                "updates": jsonable_encoder(updates),
            },
        ),
        session=session,
    )
    await session.commit()
    await session.refresh(order)
    return order


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    payload: OrderRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Order:
    return await create_order_record(session, payload)


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    session: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[str | None, Query()] = None,
) -> list[Order]:
    return await list_order_records(session, tenant_id=tenant_id)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Order:
    return await get_order_record(session, order_id)


@router.patch("/{order_id}", response_model=OrderResponse)
async def patch_order(
    order_id: UUID,
    payload: OrderPatchRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Order:
    return await update_order_record(session, order_id, payload)
