"""The copier inside MT4 or MT5 calls these. The body is plain text."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.ea_proto import OrderOut, format_orders, parse_execution, parse_heartbeat
from app.models import BrokerSpec, Delivery, Settings, Signal, User, utcnow
from app.quotes import account_mismatch, anchor_levels, build_quote
from app.security import current_ea_user
from app.sizing import ANCHORED_GROUPS
from app.symbols import SYMBOLS, aliases_for, get_symbol

_ANCHORED_IDS = tuple(spec.id for spec in SYMBOLS if spec.group in ANCHORED_GROUPS)
# These rejects were the commodity failures: Yahoo vs MT5 price, the old
# symbol name, a wide spread, or a stop the broker called too close.
_RETRY_REASONS = (
    "Price moved away from the signal.",
    "None of the symbol names are on this platform.",
    "Spread is wider than the copier allows.",
    "Stop or target is closer than the broker allows.",
    "The size is below this symbol's minimum.",
    "Spread is too wide to price the stop.",
)

router = APIRouter(prefix="/api/ea", tags=["ea"])


def _settings(db: Session, user: User) -> Settings:
    row = db.get(Settings, user.id)
    if row is None:
        raise HTTPException(status_code=404, detail="Account settings are missing.")
    return row


@router.post("/heartbeat")
async def heartbeat(request: Request, user: User = Depends(current_ea_user), db: Session = Depends(get_db)) -> Response:
    raw = await request.body()
    if len(raw) > 100_000:
        raise HTTPException(status_code=413, detail="Heartbeat is too large.")
    beat = parse_heartbeat(raw.decode("utf-8", errors="replace"))
    row = _settings(db, user)
    row.ea_last_seen = utcnow()
    row.ea_platform = beat.platform or row.ea_platform
    row.account_login = beat.login or row.account_login
    row.broker = beat.broker or row.broker
    row.balance = beat.balance
    row.equity = beat.equity
    row.account_currency = beat.currency or row.account_currency
    if beat.fx_contract:
        row.fx_contract = beat.fx_contract
        row.fx_symbol = (beat.fx_symbol or "")[:32] or row.fx_symbol
    db.query(BrokerSpec).filter(BrokerSpec.user_id == user.id).delete()
    now = utcnow()
    seen: set[str] = set()
    for spec in beat.specs:
        key = spec.broker_symbol.upper()
        if not spec.broker_symbol or key in seen or spec.tick_size <= 0 or spec.contract_size <= 0:
            continue
        seen.add(key)
        db.add(
            BrokerSpec(
                user_id=user.id,
                broker_symbol=spec.broker_symbol,
                contract_size=spec.contract_size,
                tick_size=spec.tick_size,
                tick_value=spec.tick_value,
                min_lot=spec.min_lot,
                max_lot=spec.max_lot,
                lot_step=spec.lot_step,
                digits=spec.digits,
                bid=spec.bid,
                ask=spec.ask,
                updated_at=now,
            )
        )
    db.commit()
    mismatch, message = account_mismatch(row)
    warn = message or ""
    body = f"ok\nmismatch={'1' if mismatch else '0'}\nwarn={warn}\n"
    return Response(content=body, media_type="text/plain")


@router.get("/orders")
def orders(user: User = Depends(current_ea_user), db: Session = Depends(get_db)) -> Response:
    row = _settings(db, user)
    if row.trade_mode != "auto" or row.platform == "xm":
        text = format_orders(row.trade_mode, row.account_type, "", [])
        return Response(content=text, media_type="text/plain")
    closes = _close_orders(db, user.id, row)
    mismatch, message = account_mismatch(row)
    if mismatch and not row.trust_platform_size:
        _mark(db, user.id, "paused", message or "Account type does not match the platform.")
        db.commit()
        text = format_orders(row.trade_mode, row.account_type, message or "paused", closes)
        return Response(content=text, media_type="text/plain")

    failed = (
        db.query(Delivery, Signal)
        .join(Signal, Signal.id == Delivery.signal_id)
        .filter(
            Delivery.user_id == user.id,
            Delivery.status == "not_placed",
            Signal.status == "active",
            Signal.symbol_id.in_(_ANCHORED_IDS),
        )
        .all()
    )
    now = utcnow()
    for delivery, _signal in failed:
        if any(reason in (delivery.message or "") for reason in _RETRY_REASONS):
            delivery.status = "queued"
            delivery.message = "Waiting for your platform."
            delivery.updated_at = now
    db.flush()

    queued = (
        db.query(Delivery, Signal)
        .join(Signal, Signal.id == Delivery.signal_id)
        .filter(Delivery.user_id == user.id, Delivery.status == "queued", Signal.status == "active")
        .order_by(Signal.id.asc())
        .with_for_update()
        .all()
    )
    outgoing: list[OrderOut] = list(closes)
    waiting_specs = False
    for delivery, signal in queued:
        spec = get_symbol(signal.symbol_id)
        if spec is None:
            continue
        specs = db.query(BrokerSpec).filter(BrokerSpec.user_id == user.id).all()
        entry, sl, tp = anchor_levels(spec, signal.side, signal.entry, signal.sl, signal.tp, specs, row)
        quote = build_quote(db, row, spec, signal.side, entry, sl, tp, broker_specs=specs)
        if quote.blocked:
            delivery.status = "paused"
            delivery.message = quote.reason or "Paused."
            delivery.updated_at = utcnow()
            continue
        if quote.lots is None:
            delivery.status = "not_placed"
            delivery.message = quote.reason or "No size was safe for this account."
            delivery.updated_at = utcnow()
            continue
        names = list(aliases_for(spec, row.alias_overrides))
        if quote.broker_symbol:
            names = [quote.broker_symbol] + [name for name in names if name != quote.broker_symbol]
        outgoing.append(
            OrderOut(
                delivery_id=delivery.id,
                side=signal.side,
                symbols=names,
                entry=entry,
                sl=sl,
                tp=tp,
                lots=quote.lots,
                chase=quote.chase,
                comment=f"fx{delivery.id}",
            )
        )
        delivery.status = "dispatched"
        delivery.updated_at = utcnow()
    db.commit()
    warn = ""
    return Response(content=format_orders(row.trade_mode, row.account_type, warn, outgoing), media_type="text/plain")


def _close_orders(db: Session, user_id: int, row: Settings) -> list[OrderOut]:
    """Flatten copier trades whose ICWR signal has flipped."""
    closing = (
        db.query(Delivery, Signal)
        .join(Signal, Signal.id == Delivery.signal_id)
        .filter(Delivery.user_id == user_id, Delivery.status == "close_queued")
        .order_by(Signal.id.asc())
        .all()
    )
    orders: list[OrderOut] = []
    for delivery, signal in closing:
        spec = get_symbol(signal.symbol_id)
        if spec is None:
            continue
        names = list(aliases_for(spec, row.alias_overrides))
        orders.append(
            OrderOut(
                delivery_id=delivery.id,
                side="close",
                symbols=names or [spec.display],
                entry=0.0,
                sl=0.0,
                tp=0.0,
                lots=0.0,
                chase=0.0,
                comment=f"fx{delivery.id}",
            )
        )
    return orders


def _mark(db: Session, user_id: int, status: str, message: str) -> None:
    rows = (
        db.query(Delivery)
        .join(Signal, Signal.id == Delivery.signal_id)
        .filter(Delivery.user_id == user_id, Delivery.status == "queued", Signal.status == "active")
        .all()
    )
    now = utcnow()
    for delivery in rows:
        delivery.status = status
        delivery.message = message
        delivery.updated_at = now


@router.post("/executions")
async def executions(request: Request, user: User = Depends(current_ea_user), db: Session = Depends(get_db)) -> Response:
    raw = await request.body()
    if len(raw) > 20_000:
        raise HTTPException(status_code=413, detail="Report is too large.")
    report = parse_execution(raw.decode("utf-8", errors="replace"))
    delivery = db.get(Delivery, report.delivery_id)
    if delivery is None or delivery.user_id != user.id:
        raise HTTPException(status_code=404, detail="That order is not on this account.")
    if report.status == "sl_to_entry":
        delivery.message = report.message or "Profit reached $4. Stop loss moved to entry."
        delivery.updated_at = utcnow()
        signal = db.get(Signal, delivery.signal_id)
        if signal and signal.status == "active":
            signal.sl = signal.entry
            if "[SL moved to entry]" not in (signal.rationale or ""):
                signal.rationale = f"{signal.rationale} [SL moved to entry]"
    elif report.status == "sl_lock":
        delivery.message = report.message or "Profit reached $5. Stop loss moved to lock $1."
        delivery.updated_at = utcnow()
        signal = db.get(Signal, delivery.signal_id)
        if signal and signal.status == "active" and report.fill_price:
            signal.sl = report.fill_price
            if "[SL locked $1]" not in (signal.rationale or ""):
                signal.rationale = f"{signal.rationale} [SL locked $1]"
    elif report.status == "tp_hit":
        delivery.message = report.message or "Take profit hit on MT5."
        delivery.updated_at = utcnow()
        signal = db.get(Signal, delivery.signal_id)
        if signal and signal.status == "active":
            signal.status = "target"
            signal.close_price = report.fill_price or signal.tp
            signal.closed_at = utcnow()
    elif report.status == "closed":
        delivery.status = "closed"
        delivery.message = report.message or "Closed on the opposite ICWR signal."
        delivery.updated_at = utcnow()
        if report.fill_price:
            delivery.fill_price = report.fill_price
    elif delivery.status != "placed":
        delivery.status = "placed" if report.status == "placed" else "not_placed"
        delivery.ticket = report.ticket or None
        delivery.fill_price = report.fill_price
        delivery.placed_lots = report.lots
        delivery.broker_symbol = report.broker_symbol or None
        delivery.message = report.message or ("Placed by your platform." if report.status == "placed" else "Not placed.")
        delivery.updated_at = utcnow()
        row = db.get(Settings, user.id)
        if row is not None and report.status != "placed":
            row.last_ea_error = delivery.message
        if row is not None and report.status == "placed":
            row.last_ea_error = None
    db.commit()
    return Response(content="ok\n", media_type="text/plain")


@router.post("/events")
async def events(request: Request, user: User = Depends(current_ea_user), db: Session = Depends(get_db)) -> Response:
    raw = await request.body()
    data: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            data[k.strip()] = v.strip()
    ticket_str = data.get("ticket", "")
    status = data.get("status", "")
    message = data.get("message", "")

    delivery = None
    if ticket_str:
        delivery = db.query(Delivery).filter(Delivery.ticket == ticket_str, Delivery.user_id == user.id).first()
    if delivery is None:
        delivery = (
            db.query(Delivery)
            .filter(Delivery.user_id == user.id, Delivery.status == "placed")
            .order_by(Delivery.id.desc())
            .first()
        )

    if delivery is not None:
        if status == "sl_to_entry":
            delivery.message = message or "Profit reached $4. Stop loss moved to entry."
            delivery.updated_at = utcnow()
            signal = db.get(Signal, delivery.signal_id)
            if signal and signal.status == "active":
                signal.sl = signal.entry
                if "[SL moved to entry]" not in (signal.rationale or ""):
                    signal.rationale = f"{signal.rationale} [SL moved to entry]"
        elif status == "sl_lock":
            delivery.message = message or "Profit reached $5. Stop loss moved to lock $1."
            delivery.updated_at = utcnow()
            signal = db.get(Signal, delivery.signal_id)
            if signal and signal.status == "active":
                if "[SL locked $1]" not in (signal.rationale or ""):
                    signal.rationale = f"{signal.rationale} [SL locked $1]"
        elif status == "tp_hit":
            delivery.message = message or "Take profit hit on MT5."
            delivery.updated_at = utcnow()
            signal = db.get(Signal, delivery.signal_id)
            if signal and signal.status == "active":
                signal.status = "target"
                signal.closed_at = utcnow()
        db.commit()
    return Response(content="ok\n", media_type="text/plain")
