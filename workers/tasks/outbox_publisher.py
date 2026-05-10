"""Outbox publisher worker task for HustlerOS Phase 2."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domain.models import OutboxEvent

logger = logging.getLogger(__name__)


def _session_from_ctx(ctx: dict) -> AsyncSession:
    session = ctx.get("db")
    if session is None:
        raise RuntimeError("worker database session is not initialized")
    return session


async def publish_outbox_events(ctx: dict) -> None:
    """
    Poll PENDING outbox events and mark them as PUBLISHED.

    Uses SELECT FOR UPDATE SKIP LOCKED so concurrent workers do not process the
    same event rows.
    """

    db = _session_from_ctx(ctx)
    try:
        stmt = (
            select(OutboxEvent)
            .where(OutboxEvent.status == "PENDING")
            .order_by(OutboxEvent.created_at.asc())
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        result = await db.execute(stmt)
        events = list(result.scalars().all())
        for event in events:
            try:
                logger.info(
                    "outbox_event_published event_id=%s event_type=%s tenant_id=%s correlation_id=%s",
                    event.id,
                    event.event_type,
                    event.tenant_id,
                    event.correlation_id,
                )
                event.status = "PUBLISHED"
                event.published_at = datetime.now(timezone.utc)
                event.error = None
            except Exception as exc:
                event.status = "FAILED"
                event.error = str(exc)[:500]
                logger.warning("outbox_event_failed event_id=%s error=%s", event.id, exc)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("outbox_publish_failed error=%s", exc)
        raise


# FIXME Phase 3: Add reconciliation job for payments
# that were reported but neither verified nor timed out
# correctly. Mismatched state detection across the
# payment event log belongs in a separate
# payment_reconciliation_job.
