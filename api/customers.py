"""Customers API router."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from domain.models import Customer
from domain.schemas import CustomerRequest, CustomerResponse

router = APIRouter(prefix="/api/customers", tags=["customers"])


async def create_customer_record(session: AsyncSession, payload: CustomerRequest) -> Customer:
    customer = Customer(**payload.model_dump())
    session.add(customer)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="customer already exists") from exc
    await session.refresh(customer)
    return customer


async def list_customer_records(session: AsyncSession, tenant_id: str | None = None) -> list[Customer]:
    query = select(Customer).order_by(Customer.created_at.asc())
    if tenant_id:
        query = query.where(Customer.tenant_id == tenant_id)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_customer_record(session: AsyncSession, customer_id: UUID) -> Customer:
    customer = await session.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="customer not found")
    return customer


@router.post('', response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Customer:
    return await create_customer_record(session, payload)


@router.get('', response_model=list[CustomerResponse])
async def list_customers(
    session: Annotated[AsyncSession, Depends(get_db)],
    tenant_id: Annotated[str | None, Query()] = None,
) -> list[Customer]:
    return await list_customer_records(session, tenant_id=tenant_id)


@router.get('/{customer_id}', response_model=CustomerResponse)
async def get_customer(
    customer_id: UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Customer:
    return await get_customer_record(session, customer_id)
