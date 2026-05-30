"""
APScheduler wired to a SQLite jobstore so scheduled reverts survive restarts.
"""

import logging
from datetime import datetime

from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import settings

log = logging.getLogger(__name__)

# Use a sync SQLite URL for APScheduler (it handles its own connection)
_SYNC_DB_URL = settings.database_url.replace("sqlite+aiosqlite", "sqlite")

scheduler = AsyncIOScheduler(
    jobstores={"default": SQLAlchemyJobStore(url=_SYNC_DB_URL)},
    executors={"default": AsyncIOExecutor()},
    job_defaults={"coalesce": True, "max_instances": 1},
)


def schedule_revert(grant_id: int, car_id: str, run_at: datetime) -> None:
    from app.tasks import revert_grant  # local import avoids circular deps

    scheduler.add_job(
        revert_grant,
        "date",
        run_date=run_at,
        args=[grant_id, car_id],
        id=f"revert-{grant_id}",
        replace_existing=True,
    )
    log.info("Revert for grant %d (CAR %s) scheduled at %s", grant_id, car_id, run_at)


def start_expiry_sweep() -> None:
    """Periodic safety-net: revert any active grants whose window has passed."""
    from app.tasks import recover_on_startup  # same logic — expire & push

    scheduler.add_job(
        recover_on_startup,
        "interval",
        seconds=30,
        id="expiry-sweep",
        replace_existing=True,
    )
    log.info("Expiry sweep scheduled every 30s")


def cancel_revert(grant_id: int) -> None:
    job_id = f"revert-{grant_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        log.info("Cancelled scheduled revert %s", job_id)
