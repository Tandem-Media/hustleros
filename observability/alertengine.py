"""Business incident counters and alert helpers."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping

logger = logging.getLogger(__name__)

_counters = {
    "payment_timeouts": 0,
    "delivery_failures": 0,
    "webhook_drops": 0,
    "dlq_pushes": 0,
}


async def _emit(type: str, severity: str, service: str, metadata: dict | None = None) -> None:
    try:
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
    """Fire-and-forget. Never raises. Always create_task."""

    try:
        asyncio.create_task(_emit(type, severity, service, metadata))
        if type in _counters:
            _counters[type] += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to schedule incident emission: %s", exc)


def get_incident_counts() -> dict[str, int]:
    """Return current counters."""

    return dict(_counters)


def reset_incident_counts(counts: Mapping[str, int] | None = None) -> None:
    """Reset counters for tests."""

    for key in _counters:
        _counters[key] = int((counts or {}).get(key, 0))


def health_score_contributor() -> float:
    """Returns 0.0-1.0 degradation factor."""

    total = sum(_counters.values())
    return max(0.0, min(1.0, 1.0 - (total * 0.05)))
