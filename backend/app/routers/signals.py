"""Signal list, one signal, and the manual trader's placed / skipped marks."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Delivery, Settings, Signal, User, utcnow
from app.present import signal_out
from app.schemas import MarkIn, SignalOut
from app.security import current_user

router = APIRouter(prefix="/api/signals", tags=["signals"])


def _settings(db: Session, user: User) -> Settings:
    row = db.get(Settings, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account settings are missing.")
    return row


@router.get("", response_model=list[SignalOut])
def list_signals(user: User = Depends(current_user), db: Session = Depends(get_db)) -> list[SignalOut]:
    row = _settings(db, user)
    pairs = (
        db.query(Signal, Delivery)
        .join(Delivery, Delivery.signal_id == Signal.id)
        .filter(Delivery.user_id == user.id)
        .order_by(Signal.created_at.desc())
        .limit(100)
        .all()
    )
    out = []
    for signal, delivery in pairs:
        view = signal_out(db, row, signal, delivery)
        if view is not None:
            out.append(view)
    return out


@router.get("/{signal_id}", response_model=SignalOut)
def one_signal(signal_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)) -> SignalOut:
    row = _settings(db, user)
    signal = db.get(Signal, signal_id)
    if signal is None:
        raise HTTPException(status_code=404, detail="That signal is not on your desk.")
    delivery = db.query(Delivery).filter(Delivery.signal_id == signal_id, Delivery.user_id == user.id).one_or_none()
    if delivery is None:
        raise HTTPException(status_code=404, detail="That signal is not on your desk.")
    view = signal_out(db, row, signal, delivery)
    if view is None:
        raise HTTPException(status_code=404, detail="That signal is not on your desk.")
    return view


@router.post("/{signal_id}/mark", response_model=SignalOut)
def mark(signal_id: int, body: MarkIn, user: User = Depends(current_user), db: Session = Depends(get_db)) -> SignalOut:
    if body.action not in ("you_placed", "you_skipped"):
        raise HTTPException(status_code=400, detail="Choose placed or skipped.")
    row = _settings(db, user)
    signal = db.get(Signal, signal_id)
    delivery = (
        db.query(Delivery).filter(Delivery.signal_id == signal_id, Delivery.user_id == user.id).one_or_none()
        if signal is not None
        else None
    )
    if signal is None or delivery is None:
        raise HTTPException(status_code=404, detail="That signal is not on your desk.")
    if delivery.status == "placed":
        raise HTTPException(status_code=400, detail="Your platform already placed this. The record stays as placed.")
    delivery.status = body.action
    delivery.message = "You marked this as placed." if body.action == "you_placed" else "You skipped this."
    delivery.updated_at = utcnow()
    db.commit()
    view = signal_out(db, row, signal, delivery)
    if view is None:
        raise HTTPException(status_code=404, detail="That signal is not on your desk.")
    return view
