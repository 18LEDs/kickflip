"""
Async tasks called by the scheduler and grant router.
"""

import logging
from datetime import datetime

from sqlalchemy import select

from app.clients.datadog import apply_active_grants
from app.clients.datadog_index import apply_active_grants_to_index
from app.database import AsyncSessionLocal
from app.models import Grant

log = logging.getLogger(__name__)


async def _active_car_ids(session) -> list[str]:
    result = await session.execute(
        select(Grant.car_id).where(Grant.status == "active")
    )
    return [row[0] for row in result.all()]


async def revert_grant(grant_id: int, car_id: str) -> None:
    """Mark a grant reverted and push updated filter to all pipelines."""
    log.info("Reverting grant %d (CAR %s)", grant_id, car_id)
    async with AsyncSessionLocal() as session:
        grant = await session.get(Grant, grant_id)
        if grant is None:
            log.warning("Grant %d not found — already deleted?", grant_id)
            return
        if grant.status != "active":
            log.info("Grant %d already in status %s — nothing to do", grant_id, grant.status)
            return

        grant.status = "reverted"
        grant.reverted_at = datetime.utcnow()
        await session.commit()

        remaining = await _active_car_ids(session)

    await apply_active_grants(remaining)
    await apply_active_grants_to_index(remaining)
    log.info("Grant %d reverted. Active CAR IDs remaining: %s", grant_id, remaining)


async def recover_on_startup() -> None:
    """
    On startup: expire any grants whose window already passed but were never reverted
    (e.g. the app was down during the scheduled revert window).
    Then push the correct filter state to all pipelines.
    """
    log.info("Running startup grant recovery check...")
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Grant).where(Grant.status == "active")
        )
        active_grants = result.scalars().all()

        expired = [g for g in active_grants if g.expires_at <= now]
        for g in expired:
            g.status = "expired"
            g.reverted_at = now
            log.warning("Expired missed grant %d (CAR %s, was due %s)", g.id, g.car_id, g.expires_at)

        await session.commit()
        remaining = await _active_car_ids(session)

    await apply_active_grants(remaining)
    await apply_active_grants_to_index(remaining)
    log.info("Startup recovery complete. Active grants: %s", remaining)
