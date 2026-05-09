"""Outbox-only event publisher."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from domain.events import DomainEvent
from domain.models import OutboxEvent

logger = logging.getLogger(__name__)


class EventPublisher:
    async def publish(
        self,
        event: DomainEvent,
        session: AsyncSession,
    ) -> None:
        """
        Persist to outbox_events only.
        Never publishes to broker directly.
        Never raises.
        """

        try:
            session.add(
                OutboxEvent(
                    tenant_id=event.tenant_id,
                    event_type=event.type,
                    payload=event.payload,
                    status="PENDING",
                    correlation_id=event.correlation_id,
                    causation_id=event.causation_id,
                )
            )
            await session.flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist outbox event: %s", exc)
