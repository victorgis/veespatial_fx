"""The copier inside MT4 or MT5 calls these. The body is plain text."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.ea_proto import OrderOut, format_orders, parse_execution, parse_heartbeat
from app.models import BrokerSpec, Delivery, Settings, Signal, User, utcnow
from app.quotes import account_mismatch, build_quote
from app.security import current_ea_user
from app.symbols import aliases_for, get_symbol

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
    mismatch, message = account_mismatch(row)
    if mismatch and not row.trust_platform_size:
        _mark(db, user.id, "paused", message or "Account type does not match the platform.")
        db.commit()
        text = format_orders(row.trade_mode, row.account_type, message or "paused", [])
        return Response(content=text, media_type="text/plain")

    queued = (
        db.query(Delivery, Signal)
        .join(Signal, Signal.id == Delivery.signal_id)
        .filter(Delivery.user_id == user.id, Delivery.status == "queued", Signal.status == "active")
        .order_by(Signal.id.asc())
        .all()
    )
    outgoing: list[OrderOut] = []
    waiting_specs = False
    for delivery, signal in queued:
        spec = get_symbol(signal.symbol_id)
        if spec is None:
            continue
        quote = build_quote(db, row, spec, signal.side, signal.entry, signal.sl, signal.tp)
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
        if quote.broker_symbol and quote.broker_symbol not in names:
            names.insert(0, quote.broker_symbol)
        outgoing.append(
            OrderOut(
                delivery_id=delivery.id,
                side=signal.side,
                symbols=names,
                entry=signal.entry,
                sl=signal.sl,
                tp=signal.tp,
                lots=quote.lots,
                chase=quote.chase,
                comment=f"fx{delivery.id}",
            )
        )
    db.commit()
    warn = ""
    return Response(content=format_orders(row.trade_mode, row.account_type, warn, outgoing), media_type="text/plain")


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
    if delivery.status != "placed":
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
