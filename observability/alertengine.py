"""Business incident counters and AlertEngine health helpers."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_counters = {
    "payment_timeouts": 0,
    "delivery_failures": 0,
    "webhook_drops": 0,
    "dlq_pushes": 0,
    "order_creation_failures": 0,
}
_recent_events: deque[dict[str, Any]] = deque(maxlen=1000)

_TYPE_TO_COUNTER = {
    "PAYMENT_TIMEOUT": "payment_timeouts",
    "payment_timeout": "payment_timeouts",
    "DELIVERY_FAILED": "delivery_failures",
    "delivery_failure": "delivery_failures",
    "WEBHOOK_DROP": "webhook_drops",
    "webhook_drop": "webhook_drops",
    "DLQ_PUSH": "dlq_pushes",
    "dlq_push": "dlq_pushes",
    "ORDER_CREATION_FAILED": "order_creation_failures",
    "order_creation_failed": "order_creation_failures",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _events_since(window: timedelta) -> list[dict[str, Any]]:
    cutoff = _utcnow() - window
    return [event for event in _recent_events if event["timestamp"] >= cutoff]


async def _emit(type: str, severity: str, service: str, metadata: dict | None = None) -> None:
    try:
        counter = _TYPE_TO_COUNTER.get(type, type if type in _counters else None)
        if counter in _counters:
            _counters[counter] += 1
        event = {
            "type": type,
            "severity": severity,
            "service": service,
            "metadata": metadata or {},
            "timestamp": _utcnow(),
        }
        _recent_events.append(event)
        logger.info(
            "incident_emitted type=%s severity=%s service=%s metadata=%s",
            type,
            severity,
            service,
            metadata or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to emit incident: %s", exc)


async def emit_incident(
    type: str,
    severity: str,
    service: str = "hustleros",
    metadata: dict | None = None,
) -> None:
    """Fire-and-forget incident emission. Never raises."""

    try:
        asyncio.create_task(_emit(type, severity, service, metadata))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to schedule incident emission: %s", exc)


def get_incident_counts() -> dict:
    """Return all-time in-memory business incident counters."""

    return dict(_counters)


def get_incident_counts_last_hour() -> dict[str, int]:
    """Return incident counters scoped to the last hour."""

    counts = {key: 0 for key in _counters}
    for event in _events_since(timedelta(hours=1)):
        counter = _TYPE_TO_COUNTER.get(str(event["type"]), str(event["type"]))
        if counter in counts:
            counts[counter] += 1
    return counts


def get_degradation_reasons() -> list[str]:
    """Return human-readable reasons contributing to degraded health."""

    counts = get_incident_counts_last_hour()
    reasons: list[str] = []
    if counts["payment_timeouts"] > 5:
        reasons.append("payment_timeouts_gt_5_last_hour")
    if counts["delivery_failures"] > 10:
        reasons.append("delivery_failures_gt_10_last_hour")
    if counts["order_creation_failures"] > 5:
        reasons.append("order_creation_failures_gt_5_last_hour")
    if counts["webhook_drops"] > 0:
        reasons.append("webhook_drops_present")
    if counts["dlq_pushes"] > 0:
        reasons.append("dlq_pushes_present")
    return reasons


def health_score_contributor() -> float:
    """Returns a 0.0-1.0 degradation factor for AlertEngine health."""

    counts = get_incident_counts_last_hour()
    penalty = 0.0
    if counts["payment_timeouts"] > 5:
        penalty += 0.30
    if counts["delivery_failures"] > 10:
        penalty += 0.30
    if counts["order_creation_failures"] > 5:
        penalty += 0.20
    penalty += min(0.20, counts["webhook_drops"] * 0.05)
    penalty += min(0.20, counts["dlq_pushes"] * 0.05)
    return max(0.0, min(1.0, 1.0 - penalty))
