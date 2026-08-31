"""
Scheduled tasks (APScheduler) — opt-in background jobs.

Jobs registered at app startup (main.py lifespan):
- update check: every UPDATE_CHECK_INTERVAL_HOURS (opt-out via env)
- license ping: daily (Enterprise; silently skipped in Community)

All jobs are non-blocking for requests and fail silently offline.
"""

from __future__ import annotations

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def update_check_job() -> None:
    """Periodic opt-in update check; result is only logged/UI-pollable."""
    from app.core.updates import check_for_updates

    info = await check_for_updates()
    if info and info.is_update_available:
        logger.info(
            "Update available: %s (current %s)",
            info.latest_version,
            info.current_version,
        )
    else:
        logger.debug("Update check: up to date.")


async def license_ping_job() -> None:
    """Daily license validation (Enterprise; no-op without a key)."""
    if not settings.license_key:
        return  # Community — nothing to do, zero phone-home.

    from app.core.license import validate_license_online

    info = await validate_license_online()
    logger.info("License ping: edition=%s valid=%s", info.edition, info.valid)


async def monthly_depreciation_job() -> None:
    """Monthly depreciation batch for all active entities (Module 7).

    Runs on day 1 of each month and depreciates the PREVIOUS
    month, mirroring the PRD's Inngest cron. One entity failing
    never blocks the others.
    """
    from sqlalchemy import text

    from app.db.session import async_session_factory

    async with async_session_factory() as session:
            now = date.today()
            year = now.year - 1 if now.month == 1 else now.year
            month = 12 if now.month == 1 else now.month - 1

            entities = (await session.execute(
                text("SELECT id FROM entities WHERE is_active")
            )).fetchall()

            for (entity_id,) in entities:
                try:
                    await session.execute(
                        text(
                            "SELECT fn_run_monthly_depreciation_batch("
                            "CAST(:e AS uuid), "
                            "CAST(:y AS smallint), "
                            "CAST(:m AS smallint))"
                        ),
                        {"e": str(entity_id), "y": year, "m": month},
                    )
                    await session.commit()
                    logger.info(
                        "Depreciation batch OK: entity=%s %s-%s",
                        entity_id, year, month,
                    )
                except Exception:  # noqa: BLE001
                    await session.rollback()
                    logger.exception(
                        "Depreciation batch FAILED: entity=%s "
                        "(other entities continue)",
                        entity_id,
                    )


def register_jobs() -> AsyncIOScheduler:
    """Register background jobs and start the scheduler."""
    if settings.update_check_enabled:
        scheduler.add_job(
            update_check_job,
            IntervalTrigger(hours=settings.update_check_interval_hours),
            id="update_check",
            replace_existing=True,
        )

    scheduler.add_job(
        license_ping_job,
        IntervalTrigger(hours=24),
        id="license_ping",
        replace_existing=True,
    )

    # Module 7: monthly depreciation, day 1 at 01:00.
    scheduler.add_job(
        monthly_depreciation_job,
        CronTrigger(day=1, hour=1, minute=0),
        id="monthly_depreciation",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("Scheduler started: %s", scheduler.get_jobs())
    return scheduler
