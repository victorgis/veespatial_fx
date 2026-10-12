"""Home screen payload."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Delivery, Settings, Signal, User
from app.present import me_out, scan_out, signal_out
from app.schemas import DashboardOut, MeOut
from app.security import current_user

router = APIRouter(prefix="/api", tags=["dashboard"])

_OPEN = ("queued", "for_you", "paused", "placed", "not_placed", "capped")


def _load(db: Session, user: User) -> Settings:
    row = db.get(Settings, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account settings are missing.")
    return row


@router.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)) -> MeOut:
    return me_out(db, user, _load(db, user))


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)) -> DashboardOut:
    row = _load(db, user)
    from app.models import BrokerSpec
    from app.quotes import converters

    rates = converters(db)
    specs = db.query(BrokerSpec).filter(BrokerSpec.user_id == user.id).all()

    active_pairs = (
        db.query(Signal, Delivery)
        .join(Delivery, Delivery.signal_id == Signal.id)
        .filter(Delivery.user_id == user.id, Signal.status == "active", Delivery.status.in_(_OPEN))
        .order_by(Signal.created_at.desc())
        .limit(20)
        .all()
    )
    recent_pairs = (
        db.query(Signal, Delivery)
        .join(Delivery, Delivery.signal_id == Signal.id)
        .filter(Delivery.user_id == user.id, Signal.status != "active")
        .order_by(Signal.created_at.desc())
        .limit(8)
        .all()
    )
    signals = []
    for signal, delivery in active_pairs:
        view = signal_out(db, row, signal, delivery, rates=rates, broker_specs=specs)
        if view is not None:
            signals.append(view)
    recent = []
    for signal, delivery in recent_pairs:
        view = signal_out(db, row, signal, delivery, rates=rates, broker_specs=specs)
        if view is not None:
            recent.append(view)
    return DashboardOut(me=me_out(db, user, row), scan=scan_out(db), signals=signals, recent=recent)
