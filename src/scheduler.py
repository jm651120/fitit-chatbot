"""APScheduler background jobs: weekly schedule refresh (Mon 07:00) and
monthly full re-crawl (1st of the month, 06:00), Europe/Lisbon time.

Started inside the Streamlit app so updates run while the app is up."""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from src.config import TIMEZONE
from src.updater import full_recrawl, update_schedule

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def start_scheduler() -> BackgroundScheduler:
    """Start (once) and return the background scheduler."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    sched = BackgroundScheduler(timezone=TIMEZONE)
    sched.add_job(
        update_schedule,
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=TIMEZONE),
        id="weekly_schedule_update",
        name="Weekly FIT IT schedule refresh",
        coalesce=True,
        misfire_grace_time=6 * 3600,  # still runs if the app wakes up late
        max_instances=1,
    )
    sched.add_job(
        full_recrawl,
        CronTrigger(day=1, hour=6, minute=0, timezone=TIMEZONE),
        id="monthly_full_recrawl",
        name="Monthly FIT IT full site re-crawl",
        coalesce=True,
        misfire_grace_time=12 * 3600,
        max_instances=1,
    )
    sched.start()
    logger.info("Background scheduler started (weekly Mon 07:00, monthly 1st 06:00)")
    _scheduler = sched
    return sched


def next_run_times() -> dict:
    if _scheduler is None:
        return {}
    return {
        job.id: job.next_run_time.strftime("%d/%m/%Y %H:%M")
        for job in _scheduler.get_jobs()
        if job.next_run_time
    }
