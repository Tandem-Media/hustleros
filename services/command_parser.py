"""Natural-language command parsing and intent routing."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Pattern

from domain.commands import (
    CreateCustomerCommand,
    CreateOrderCommand,
    ReportPaymentCommand,
    UnknownCommand,
    UpdateOrderStatusCommand,
)


class CommandParser:
    customer_pattern: Pattern[str] = re.compile(
        r"(?:create|add) customer (?P<name>.+?) phone (?P<phone>\+?[0-9][0-9\- ]+)",
        re.IGNORECASE,
    )
    order_pattern: Pattern[str] = re.compile(
        r"create order customer (?P<customer_id>[A-Za-z0-9\-]+) total (?P<total>[0-9]+(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    )
    payment_pattern: Pattern[str] = re.compile(
        r"report payment order (?P<order_id>[A-Za-z0-9\-]+) amount (?P<amount>[0-9]+(?:\.[0-9]{1,2})?)(?: method (?P<method>[a-z_]+))?",
        re.IGNORECASE,
    )
    order_status_pattern: Pattern[str] = re.compile(
        r"(?:update|patch) order (?P<order_id>[A-Za-z0-9\-]+) status (?P<status>[a-z_\-]+)",
        re.IGNORECASE,
    )

    def parse(self, text: str, tenant_id: str = "default", correlation_id: str = ""):
        normalized = text.strip()
        if not normalized:
            return UnknownCommand(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                raw_input=text,
                reason="empty command",
            )

        customer_match = self.customer_pattern.fullmatch(normalized)
        if customer_match:
            return CreateCustomerCommand(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                name=customer_match.group("name").strip(),
                phone=customer_match.group("phone").strip(),
            )

        order_match = self.order_pattern.fullmatch(normalized)
        if order_match:
            return CreateOrderCommand(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                customer_id=order_match.group("customer_id"),
                total=self._to_decimal(order_match.group("total")),
            )

        payment_match = self.payment_pattern.fullmatch(normalized)
        if payment_match:
            return ReportPaymentCommand(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                order_id=payment_match.group("order_id"),
                amount=self._to_decimal(payment_match.group("amount")),
                method=(payment_match.group("method") or "cash").lower(),
            )

        order_status_match = self.order_status_pattern.fullmatch(normalized)
        if order_status_match:
            return UpdateOrderStatusCommand(
                tenant_id=tenant_id,
                correlation_id=correlation_id,
                order_id=order_status_match.group("order_id"),
                status=order_status_match.group("status").upper(),
            )

        return UnknownCommand(
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            raw_input=text,
            reason="no parser matched",
        )

    @staticmethod
    def _to_decimal(value: str) -> Decimal:
        try:
            return Decimal(value).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            return Decimal("0.00")
