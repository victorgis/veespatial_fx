"""Account preferences: manual or automatic, standard or micro, risk."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Delivery, Settings, Signal, User, utcnow
from app.present import settings_out
from app.schemas import KeyOut, SettingsIn, SettingsSaved
from app.security import current_user, make_ea_key
from app.validate import settings_error

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _apply(row: Settings, body: SettingsIn) -> None:
    row.trade_mode = body.trade_mode
    row.account_type = body.account_type
    row.platform = body.platform
    row.risk_percent = body.risk_percent
    row.max_lot = body.max_lot
    row.planning_balance = body.planning_balance
    row.enabled_symbols = ",".join(dict.fromkeys(body.enabled_symbols))
    row.alias_overrides = body.alias_overrides.strip()
    row.onboarding_done = body.onboarding_done
    row.risk_accepted = body.risk_accepted
    row.trust_platform_size = body.trust_platform_size


def _retarget_open_orders(db: Session, row: Settings) -> None:
    """Old signals stay where they were. Only still-waiting automatic orders move.

    Switching to signals-only must not leave a queued order that the copier
    could still place. Switching back to automatic does not revive it.
    """
    if row.trade_mode == "auto":
        return
    open_rows = (
        db.query(Delivery, Signal)
        .join(Signal, Signal.id == Delivery.signal_id)
        .filter(Delivery.user_id == row.user_id, Signal.status == "active", Delivery.status.in_(("queued", "paused")))
        .all()
    )
    for delivery, _signal in open_rows:
        delivery.status = "for_you"
        delivery.message = "Signals only. This one will not be sent to your platform."
        delivery.updated_at = utcnow()


@router.put("", response_model=SettingsSaved)
def save_settings(body: SettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> SettingsSaved:
    problem = settings_error(body)
    if problem:
        raise HTTPException(status_code=400, detail=problem)
    row = db.get(Settings, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account settings are missing.")
    _apply(row, body)
    _retarget_open_orders(db, row)
    fresh: str | None = None
    if row.trade_mode == "auto" and not row.ea_key_hash:
        fresh, digest, prefix = make_ea_key()
        row.ea_key_hash = digest
        row.ea_key_prefix = prefix
    db.commit()
    db.refresh(row)
    return SettingsSaved(settings=settings_out(row), ea_key=fresh)


@router.post("/ea-key", response_model=KeyOut)
def rotate_key(user: User = Depends(current_user), db: Session = Depends(get_db)) -> KeyOut:
    row = db.get(Settings, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account settings are missing.")
    fresh, digest, prefix = make_ea_key()
    row.ea_key_hash = digest
    row.ea_key_prefix = prefix
    db.commit()
    return KeyOut(ea_key=fresh, ea_key_prefix=prefix)
