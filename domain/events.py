"""Domain event dataclasses for HustlerOS."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import uuid4


@dataclass
class DomainEvent:
    id: str = field(default_factory=lambda: str(uuid4()))
    type: str = ""
    tenant_id: str = "default"
    correlation_id: str = ""
    causation_id: str = ""
    payload: dict = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CustomerCreatedEvent(DomainEvent):
    pass


@dataclass
class OrderCreatedEvent(DomainEvent):
    pass


@dataclass
class OrderStatusChangedEvent(DomainEvent):
    pass


@dataclass
class InvoiceSentEvent(DomainEvent):
    pass


@dataclass
class PaymentReportedEvent(DomainEvent):
    pass


@dataclass
class PaymentVerifiedEvent(DomainEvent):
    pass


@dataclass
class PaymentDisputedEvent(DomainEvent):
    pass


@dataclass
class PaymentTimeoutEvent(DomainEvent):
    pass


@dataclass
class DeliveryAssignedEvent(DomainEvent):
    pass


@dataclass
class DeliveryFailedEvent(DomainEvent):
    pass


@dataclass
class CustomerNotifiedEvent(DomainEvent):
    pass
