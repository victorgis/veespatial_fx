"""In-process scan timer. A sleeping host should also call POST /api/system/scan."""

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app.config import get_settings
from app.purge import LAGOS, PURGE_HOUR, clear_trading_data
from app.scan import run_scan


def start_scheduler() -> BackgroundScheduler:
    cfg = get_settings()
    interval = max(60, int(cfg.scan_interval_seconds))
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        run_scan,
        "interval",
        seconds=interval,
        id="scan",
        max_instances=1,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=20),
    )
    # 02:00 Africa/Lagos. A missed wake is covered again from startup and from each scan.
    scheduler.add_job(
        clear_trading_data,
        "cron",
        hour=PURGE_HOUR,
        minute=0,
        timezone=LAGOS,
        id="purge-trading-data",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=12 * 60 * 60,
    )
    scheduler.start()
    return scheduler
