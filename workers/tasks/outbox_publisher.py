"""Outbox publisher worker task that drains pending outbox events."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from db.session import get_session
from domain.events import OutboxPublishedEvent
from domain.models import OutboxEvent


async def publish_outbox_events(_ctx: dict | None = None, batch_size: int = 100) -> dict[str, int]:
    async with get_session() as session:
        result = await session.execute(
            select(OutboxEvent)
            .where(OutboxEvent.status == "PENDING")
            .order_by(OutboxEvent.created_at.asc())
            .limit(batch_size)
        )
        events = list(result.scalars().all())
        published_at = datetime.now(timezone.utc)
        published = 0

        for event in events:
            event.status = "PUBLISHED"
            event.published_at = published_at
            event.error = None
            published += 1

        await session.commit()

    return {
        "published": published,
        "remaining": max(0, batch_size - published),
        "event_type": OutboxPublishedEvent.__name__,
    }
