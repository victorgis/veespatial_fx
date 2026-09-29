"""Build the JSON the website renders."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models import Delivery, ScanRun, Settings, Signal, User, utcnow
from app.quotes import Quote, account_mismatch, build_quote
from app.schemas import (
    ConnectionOut,
    MeOut,
    QuoteOut,
    ScanOut,
    SettingsOut,
    SignalOut,
    UserOut,
)
from app.sizing import detect_account_type
from app.symbols import SYMBOLS, get_symbol
from app.telegram_svc import configured
from app.wording import status_line


def split_ids(text: str) -> list[str]:
    return [p.strip() for p in (text or "").split(",") if p.strip()]


def settings_out(row: Settings) -> SettingsOut:
    return SettingsOut(
        trade_mode=row.trade_mode,
        account_type=row.account_type,
        platform=row.platform,
        risk_percent=row.risk_percent,
        max_lot=row.max_lot,
        planning_balance=row.planning_balance,
        enabled_symbols=split_ids(row.enabled_symbols),
        alias_overrides=row.alias_overrides or "",
        onboarding_done=row.onboarding_done,
        risk_accepted=row.risk_accepted,
        trust_platform_size=row.trust_platform_size,
        ea_key_prefix=row.ea_key_prefix,
    )


def user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, name=user.name, is_admin=user.is_admin)


def online(row: Settings) -> bool:
    if row.ea_last_seen is None:
        return False
    return utcnow() - row.ea_last_seen < timedelta(seconds=90)


def connection_out(row: Settings) -> ConnectionOut:
    detected = detect_account_type(row.fx_contract)
    mismatch, message = account_mismatch(row)
    return ConnectionOut(
        online=online(row),
        last_seen=row.ea_last_seen,
        broker=row.broker,
        account_login=row.account_login,
        balance=row.balance,
        equity=row.equity,
        currency=row.account_currency or "USD",
        ea_platform=row.ea_platform,
        fx_symbol=row.fx_symbol,
        fx_contract=row.fx_contract,
        detected_account_type=detected,
        mismatch=mismatch,
        mismatch_message=message,
    )


def me_out(db: Session, user: User, row: Settings) -> MeOut:
    from app.models import BotConfig

    cfg = db.get(BotConfig, 1)
    watched = split_ids(cfg.enabled_symbols) if cfg else []
    conn = connection_out(row)
    return MeOut(
        user=user_out(user),
        settings=settings_out(row),
        connection=conn,
        telegram_configured=configured(),
        status_line=status_line(row.trade_mode, conn.online, conn.mismatch and row.trade_mode == "auto", row.broker),
        watchlist=watched,
    )


def quote_out(q: Quote) -> QuoteOut:
    return QuoteOut(
        lots=q.lots,
        units=q.units,
        unit=q.unit,
        risk_cash=q.risk_cash,
        currency=q.currency,
        min_lot=q.min_lot,
        too_small=q.too_small,
        reason=q.reason,
        approximate=q.approximate,
        standard_lots=q.standard_lots,
        micro_lots=q.micro_lots,
        scales_with_account=q.scales_with_account,
        uses_live_contract=q.uses_live_contract,
        contract_size=q.contract_size,
        balance_source=q.balance_source,
        balance=q.balance,
        blocked=q.blocked,
    )


def signal_out(db: Session, settings: Settings, signal: Signal, delivery: Delivery | None) -> SignalOut | None:
    spec = get_symbol(signal.symbol_id)
    if spec is None:
        return None
    quote = build_quote(db, settings, spec, signal.side, signal.entry, signal.sl, signal.tp)
    return SignalOut(
        id=signal.id,
        symbol_id=spec.id,
        display=spec.display,
        pair=spec.pair,
        group=spec.group,
        digits=spec.digits,
        unit=spec.unit,
        mt5_only=spec.mt5_only,
        note=spec.note,
        side=signal.side,
        entry=signal.entry,
        sl=signal.sl,
        tp=signal.tp,
        rsi=signal.rsi,
        status=signal.status,
        rationale=signal.rationale,
        source=signal.source,
        created_at=signal.created_at,
        closed_at=signal.closed_at,
        close_price=signal.close_price,
        delivery_id=delivery.id if delivery else None,
        delivery_status=delivery.status if delivery else None,
        delivery_message=delivery.message if delivery else None,
        ticket=delivery.ticket if delivery else None,
        fill_price=delivery.fill_price if delivery else None,
        placed_lots=delivery.placed_lots if delivery else None,
        broker_symbol=delivery.broker_symbol if delivery else None,
        quote=quote_out(quote),
        copy_text=quote.copy,
    )


def scan_out(db: Session) -> ScanOut:
    row = db.query(ScanRun).order_by(ScanRun.id.desc()).first()
    if row is None:
        return ScanOut(started_at=None, finished_at=None, ok=None, message="No scan yet.", signals_created=0)
    return ScanOut(
        started_at=row.started_at,
        finished_at=row.finished_at,
        ok=row.ok,
        message=row.message,
        signals_created=row.signals_created,
    )


def market_dicts() -> list[dict]:
    rows = []
    for spec in SYMBOLS:
        rows.append(
            {
                "id": spec.id,
                "display": spec.display,
                "pair": spec.pair,
                "group": spec.group,
                "mt5_only": spec.mt5_only,
                "aliases": list(spec.aliases),
                "scales_with_account": spec.scales_with_account,
                "unit": spec.unit,
                "note": spec.note,
                "contract_standard": spec.contract_standard,
                "contract_micro": spec.contract_standard / 100 if spec.scales_with_account else spec.contract_standard,
            }
        )
    return rows
