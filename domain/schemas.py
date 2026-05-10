"""Pydantic v2 schemas for API request/response models."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CustomerRequest(BaseSchema):
    tenant_id: str = "default"
    name: str
    phone: str


class CustomerResponse(BaseSchema):
    id: UUID
    tenant_id: str
    name: str
    phone: str
    created_at: datetime


class CustomerInternalResponse(CustomerResponse):
    updated_at: datetime


class OrderItem(BaseSchema):
    name: str
    quantity: int = Field(gt=0)
    unit_price: Decimal
    total: Decimal


class OrderRequest(BaseSchema):
    customer_id: UUID
    items: list[OrderItem]
    total: Decimal
    tenant_id: str = "default"
    correlation_id: str | None = None


class OrderResponse(BaseSchema):
    id: UUID
    tenant_id: str
    customer_id: UUID
    items: list[dict[str, Any]]
    status: str
    total: Decimal
    correlation_id: str
    created_at: datetime


class OrderWithCustomerResponse(OrderResponse):
    customer_name: str


class OrderStatusRequest(BaseSchema):
    status: str


class InvoiceRequest(BaseSchema):
    tenant_id: str
    order_id: UUID
    amount: Decimal
    due_date: date
    version: int = 1
    status: str
    sent_at: datetime | None = None


class InvoiceResponse(BaseSchema):
    id: UUID
    tenant_id: str
    order_id: UUID
    amount: Decimal
    due_date: date
    version: int
    status: str
    sent_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PaymentRequest(BaseSchema):
    tenant_id: str
    order_id: UUID
    event_type: str
    amount: Decimal
    method: str
    reference: str | None = None
    reported_by: str | None = None
    verified_by: str | None = None
    correlation_id: str
    causation_id: str


class PaymentResponse(BaseSchema):
    id: UUID
    tenant_id: str
    order_id: UUID
    event_type: str
    amount: Decimal
    method: str
    reference: str | None
    reported_by: str | None
    verified_by: str | None
    correlation_id: str
    causation_id: str
    created_at: datetime


class PaymentReportRequest(BaseSchema):
    order_id: UUID
    amount: Decimal
    method: str
    reference: str | None = None
    reported_by: str
    tenant_id: str = "default"


class PaymentReportResponse(BaseSchema):
    id: UUID
    order_id: UUID
    event_type: str
    amount: Decimal
    method: str
    reference: str | None
    reported_by: str | None
    created_at: datetime


class PaymentBalanceResponse(BaseSchema):
    order_id: UUID
    total_reported: Decimal
    total_verified: Decimal
    total_disputed: Decimal
    outstanding: Decimal
    events: list[PaymentResponse]


class DeliveryRequest(BaseSchema):
    tenant_id: str
    order_id: UUID
    courier_id: str
    status: str


class DeliveryResponse(BaseSchema):
    id: UUID
    tenant_id: str
    order_id: UUID
    courier_id: str
    status: str
    collected_at: datetime | None
    delivered_at: datetime | None
    failed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime


class BusinessEventRequest(BaseSchema):
    tenant_id: str
    event_type: str
    entity_id: str
    entity_type: str
    payload: dict[str, Any]
    correlation_id: str
    causation_id: str


class BusinessEventResponse(BaseSchema):
    id: UUID
    tenant_id: str
    event_type: str
    entity_id: str
    entity_type: str
    payload: dict[str, Any]
    correlation_id: str
    causation_id: str
    created_at: datetime


class OutboxEventRequest(BaseSchema):
    tenant_id: str
    event_type: str
    payload: dict[str, Any]
    status: str
    correlation_id: str
    causation_id: str


class OutboxEventResponse(BaseSchema):
    id: UUID
    tenant_id: str
    event_type: str
    payload: dict[str, Any]
    status: str
    correlation_id: str
    causation_id: str
    created_at: datetime
    published_at: datetime | None
    error: str | None


class WebhookReceiptRequest(BaseSchema):
    tenant_id: str
    provider: str
    idempotency_key: str
    payload: dict[str, Any]
    status: str


class WebhookReceiptResponse(BaseSchema):
    id: UUID
    tenant_id: str
    provider: str
    idempotency_key: str
    payload: dict[str, Any]
    status: str
    received_at: datetime
    processed_at: datetime | None
    error: str | None

class ParseRequest(BaseModel):
    message: str
    tenant_id: str = "default"


class ParseResponse(BaseModel):
    command_type: str
    confidence: float
    parsed: dict
    raw: str

