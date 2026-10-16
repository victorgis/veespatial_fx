"""Daily wipe of trade history. Accounts, settings, and the watchlist stay.

02:00 Africa/Lagos is 01:00 UTC. Nigeria does not use daylight saving time.
Rows strictly older than the latest 02:00 that has already arrived are removed,
so a host that slept through 2am still catches up, and trades opened after 2am stay.
The wipe forgets the desk's record of a trade. It does not close a ticket on the broker.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

from app.database import session_scope
from app.models import Delivery, ScanRun, Signal

log = logging.getLogger("desk.purge")

LAGOS = ZoneInfo("Africa/Lagos")
PURGE_HOUR = 2


def purge_cutoff(now: datetime | None = None) -> datetime:
    """The latest 02:00 in Africa/Lagos that is not still in the future, as UTC."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    local = current.astimezone(LAGOS)
    cutoff = local.replace(hour=PURGE_HOUR, minute=0, second=0, microsecond=0)
    if local < cutoff:
        cutoff -= timedelta(days=1)
    return cutoff.astimezone(timezone.utc)


def clear_trading_data(now: datetime | None = None) -> dict[str, int]:
    """Delete deliveries, signals, and scan runs from before the latest 02:00 Lagos.

    Users, settings, the watchlist, last prices, and broker specs are left as they are.
    An empty pass deletes nothing.
    """
    cutoff = purge_cutoff(now)
    db = session_scope()
    try:
        old_signal_ids = select(Signal.id).where(Signal.created_at < cutoff)
        deliveries = (
            db.query(Delivery)
            .filter(or_(Delivery.created_at < cutoff, Delivery.signal_id.in_(old_signal_ids)))
            .delete(synchronize_session=False)
        )
        signals = db.query(Signal).filter(Signal.created_at < cutoff).delete(synchronize_session=False)
        scan_runs = db.query(ScanRun).filter(ScanRun.started_at < cutoff).delete(synchronize_session=False)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    removed = {
        "deliveries": int(deliveries or 0),
        "signals": int(signals or 0),
        "scan_runs": int(scan_runs or 0),
    }
    if any(removed.values()):
        log.info(
            "Cleared trading data from before %s WAT: %s signals, %s deliveries, %s scan runs",
            cutoff.astimezone(LAGOS).strftime("%Y-%m-%d %H:%M"),
            removed["signals"],
            removed["deliveries"],
            removed["scan_runs"],
        )
    return removed
