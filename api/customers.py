"""Customers API for HustlerOS Phase 2."""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from domain.events import CustomerCreatedEvent
from domain.models import Customer
from domain.schemas import CustomerRequest, CustomerResponse
from services.event_publisher import EventPublisher

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/customers", tags=["customers"])
publisher = EventPublisher()


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(req: CustomerRequest, db: AsyncSession = Depends(get_db)) -> Customer:
    """Create a tenant-scoped customer and emit CustomerCreated to the outbox."""

    duplicate = await db.execute(select(Customer).where(Customer.tenant_id == req.tenant_id, Customer.phone == req.phone))
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer phone already exists for tenant")

    customer = Customer(tenant_id=req.tenant_id, name=req.name, phone=req.phone)
    db.add(customer)
    await db.flush()
    await publisher.publish(
        CustomerCreatedEvent(
            type="CUSTOMER_CREATED",
            tenant_id=customer.tenant_id,
            correlation_id=str(customer.id),
            causation_id=str(customer.id),
            payload={"customer_id": str(customer.id), "name": customer.name, "phone": customer.phone},
        ),
        db,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        logger.info("duplicate_customer_phone tenant_id=%s phone=%s error=%s", req.tenant_id, req.phone, exc)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Customer phone already exists for tenant") from exc
    await db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(customer_id: UUID, tenant_id: str = Query(...), db: AsyncSession = Depends(get_db)) -> Customer:
    """Return a single customer when tenant ownership matches."""

    result = await db.execute(select(Customer).where(Customer.id == customer_id, Customer.tenant_id == tenant_id))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
    return customer


@router.get("", response_model=list[CustomerResponse])
async def list_customers(
    tenant_id: str = Query(...),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[Customer]:
    """List tenant-scoped customers with pagination."""

    result = await db.execute(select(Customer).where(Customer.tenant_id == tenant_id).offset(skip).limit(limit))
    return list(result.scalars().all())
