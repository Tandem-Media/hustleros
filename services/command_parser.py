"""Deterministic WhatsApp command parser for HustlerOS Phase 2."""

from __future__ import annotations

import logging
import re
from decimal import Decimal

from domain.commands import Command, CreateInvoiceCommand, CreateOrderCommand, ReportPaymentCommand, UnknownCommand

logger = logging.getLogger(__name__)


class CommandParser:
    """Parse WhatsApp text into typed domain command objects without raising."""

    _order_re = re.compile(r"(?P<qty>\d+)\s+(?P<item>.+?)\s+for\s+(?P<name>[A-Za-z][\w\s'-]*)", re.IGNORECASE)
    _invoice_re = re.compile(r"^(invoice|bill)\s+(?P<body>.+)$", re.IGNORECASE)
    _amount_re = re.compile(r"(?:\$|usd\s*)?(?P<amount>\d+(?:\.\d{1,2})?)", re.IGNORECASE)

    async def parse(self, message: str, tenant_id: str = "default") -> Command:
        """Return a typed command for known deterministic patterns or UnknownCommand."""

        try:
            raw = message.strip()
            lowered = raw.lower()

            order_match = self._order_re.search(raw)
            if order_match is not None and "for" in lowered:
                quantity = int(order_match.group("qty"))
                item_name = order_match.group("item").strip()
                customer_name = order_match.group("name").strip()
                return CreateOrderCommand(
                    tenant_id=tenant_id,
                    confidence=1.0,
                    items=[{"name": item_name, "quantity": quantity}],
                    customer_name=customer_name,
                    raw_input=raw,
                )

            invoice_match = self._invoice_re.match(raw)
            if invoice_match is not None:
                body = invoice_match.group("body").strip()
                customer_name = body.split(" for ")[0].strip() if " for " in body.lower() else body.split()[0]
                return CreateInvoiceCommand(
                    tenant_id=tenant_id,
                    confidence=1.0,
                    customer_name=customer_name,
                    raw_input=raw,
                )

            if any(token in lowered for token in ("paid", "payment", "collected", "cash")):
                amount_match = self._amount_re.search(raw)
                amount = Decimal(amount_match.group("amount")) if amount_match is not None else Decimal("0")
                method = "CASH" if "cash" in lowered else "OTHER"
                return ReportPaymentCommand(
                    tenant_id=tenant_id,
                    confidence=1.0,
                    amount=amount,
                    method=method,
                    raw_input=raw,
                )

            logger.warning("unknown_command tenant_id=%s message=%s", tenant_id, raw)
            return UnknownCommand(tenant_id=tenant_id, raw_input=raw, reason="No deterministic parser matched", confidence=0.0)
        except Exception as exc:
            logger.warning("command_parser_failed tenant_id=%s error=%s", tenant_id, exc)
            return UnknownCommand(tenant_id=tenant_id, raw_input=message, reason=str(exc), confidence=0.0)
