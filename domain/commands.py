"""Domain command dataclasses for HustlerOS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4


@dataclass
class Command:
    id: str = field(default_factory=lambda: str(uuid4()))
    tenant_id: str = "default"
    correlation_id: str = ""
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CreateCustomerCommand(Command):
    name: str = ""
    phone: str = ""


@dataclass
class CreateOrderCommand(Command):
    customer_id: UUID | str | None = None
    items: list[dict] = field(default_factory=list)
    total: Decimal = Decimal("0.00")


@dataclass
class UpdateOrderStatusCommand(Command):
    order_id: UUID | str | None = None
    status: str = ""


@dataclass
class CreateInvoiceCommand(Command):
    order_id: str = ""
    amount: Decimal = Decimal("0.00")
    due_date: date | None = None


@dataclass
class ReportPaymentCommand(Command):
    order_id: UUID | str | None = None
    amount: Decimal = Decimal("0.00")
    method: str = ""
    reference: str | None = None
    reported_by: str | None = None


@dataclass
class AssignDeliveryCommand(Command):
    order_id: str = ""
    courier_id: str = ""


@dataclass
class NotifyCustomerCommand(Command):
    customer_id: str = ""
    message: str = ""
    channel: str = ""


@dataclass
class UnknownCommand(Command):
    raw_input: str = ""
    reason: str = ""
