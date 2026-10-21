"""What size a person should trade, for one signal and one account."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import BrokerSpec, LastPrice, Settings
from app.sizing import (
    ANCHORED_GROUPS,
    LotResult,
    chase_for,
    detect_account_type,
    lots_from_contract,
    lots_from_ticks,
    rebase_levels,
)
from app.symbols import (
    Symbol,
    aliases_for,
    broker_symbol_matches,
    contract_size_for,
    get_symbol,
    is_micro_symbol_name,
)
from app.wording import copy_text, mismatch_message


@dataclass
class Quote:
    lots: float | None
    units: float | None
    unit: str
    risk_cash: float
    currency: str
    min_lot: float
    too_small: bool
    reason: str | None
    approximate: bool
    standard_lots: float | None
    micro_lots: float | None
    scales_with_account: bool
    uses_live_contract: bool
    contract_size: float | None
    balance_source: str
    balance: float
    blocked: bool
    chase: float
    broker_symbol: str | None
    copy: str


def converters(db: Session) -> dict[str, float]:
    rows = db.query(LastPrice).all()
    return {r.symbol_id: r.close for r in rows}


def account_mismatch(settings: Settings) -> tuple[bool, str | None]:
    detected = detect_account_type(settings.fx_contract)
    if settings.trust_platform_size or detected is None:
        return False, None
    if detected == settings.account_type:
        return False, None
    return True, mismatch_message(settings.account_type, detected, settings.fx_symbol, settings.fx_contract)


def account_for_names(settings: Settings) -> str:
    """Which XM name set to use: the copier's contract when it is known, else the website choice."""
    detected = detect_account_type(settings.fx_contract)
    if detected and (settings.trust_platform_size or detected == settings.account_type):
        return detected
    return settings.account_type


def _name_rank(broker_symbol: str, account_type: str) -> int:
    micro = is_micro_symbol_name(broker_symbol)
    if account_type == "micro":
        return 0 if micro else 1
    return 0 if not micro else 1


def _pick_spec(rows: list[BrokerSpec], spec: Symbol, settings: Settings) -> BrokerSpec | None:
    kind = account_for_names(settings)
    names = aliases_for(spec, settings.alias_overrides, kind)
    matches = [r for r in rows if broker_symbol_matches(r.broker_symbol, names)]
    if not matches:
        return None
    target = contract_size_for(spec, kind)
    # Cash CFDs (OILCash, NGASCash) are the markets the desk signals.
    # A futures month with the same contract size must not win the tie.
    # On XM micro, EURUSD is often visible but untradeable; EURUSDmicro is the fill.
    matches.sort(
        key=lambda r: (
            0 if "CASH" in r.broker_symbol.upper() else 1,
            abs(r.contract_size - target),
            _name_rank(r.broker_symbol, kind),
            len(r.broker_symbol),
            r.broker_symbol,
        )
    )
    return matches[0]


def anchor_levels(
    spec: Symbol,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    rows: list[BrokerSpec],
    settings: Settings,
) -> tuple[float, float, float]:
    """Express a metal, energy, or commodity signal on the connected quote."""
    if spec.group not in ANCHORED_GROUPS:
        return entry, sl, tp
    live = _pick_spec(rows, spec, settings)
    if live is None:
        return entry, sl, tp
    return rebase_levels(side, entry, sl, tp, live.bid, live.ask)


def _spec_conflicts(row: BrokerSpec, spec: Symbol, account_type: str) -> bool:
    if row.contract_size <= 0:
        return True
    if not spec.scales_with_account:
        return False
    target = contract_size_for(spec, account_type)
    if target <= 0:
        return True
    ratio = row.contract_size / target
    return ratio > 3 or ratio < (1 / 3)


def build_quote(
    db: Session,
    settings: Settings,
    spec: Symbol,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    rates: dict[str, float] | None = None,
    broker_specs: list[BrokerSpec] | None = None,
) -> Quote:
    currency = settings.account_currency or "USD"
    if settings.balance is not None and settings.balance > 0:
        balance = float(settings.balance)
        source = "platform"
    else:
        balance = float(settings.planning_balance or 0)
        source = "planning"
    risk_cash = balance * float(settings.risk_percent) / 100.0
    if rates is None:
        rates = converters(db)
    # Comparison figures are the uncapped risk size, so standard vs micro stays honest.
    standard = lots_from_contract(spec, "standard", risk_cash, entry, sl, settings.platform, 1_000_000, currency, rates)
    micro = lots_from_contract(spec, "micro", risk_cash, entry, sl, settings.platform, 1_000_000, currency, rates)
    own = lots_from_contract(
        spec, settings.account_type, risk_cash, entry, sl, settings.platform, settings.max_lot, currency, rates
    )
    rows = broker_specs if broker_specs is not None else db.query(BrokerSpec).filter(BrokerSpec.user_id == settings.user_id).all()
    live = _pick_spec(rows, spec, settings)
    mismatch, mismatch_text = account_mismatch(settings)
    kind = account_for_names(settings)
    conflict = bool(live and _spec_conflicts(live, spec, kind) and not settings.trust_platform_size)
    blocked = mismatch or conflict

    chosen: LotResult
    uses_live = False
    broker_symbol = None
    contract = None
    if live and not blocked:
        cap = float(settings.max_lot)
        chosen = lots_from_ticks(
            risk_cash,
            abs(entry - sl),
            live.tick_size,
            live.tick_value,
            live.contract_size,
            live.min_lot,
            live.lot_step or 0.01,
            cap,
            currency,
        )
        uses_live = True
        broker_symbol = live.broker_symbol
        contract = live.contract_size
    else:
        chosen = own
        contract = chosen.contract_size

    warning = None
    if blocked:
        warning = mismatch_text or (
            f"{live.broker_symbol if live else spec.display} on your platform does not match a "
            f"{settings.account_type} contract. Automatic orders for this market are paused."
        )

    # Manual traders still need a number to type. Automatic sending is what pauses.
    if settings.trade_mode == "auto" and blocked:
        lots = None
        units = None
        reason = warning
        too_small = False
        approximate = False
    else:
        lots = chosen.lots
        units = chosen.units
        reason = chosen.reason or warning
        too_small = chosen.too_small
        approximate = chosen.approximate

    text = copy_text(spec, side, entry, sl, tp, settings.account_type, lots, units, risk_cash, currency, reason if lots is None else None)
    if warning and lots is not None:
        text = text + "\n" + warning
    return Quote(
        lots=lots,
        units=units,
        unit=spec.unit,
        risk_cash=risk_cash,
        currency=currency,
        min_lot=chosen.min_lot,
        too_small=too_small,
        reason=reason,
        approximate=approximate,
        standard_lots=standard.lots,
        micro_lots=micro.lots,
        scales_with_account=spec.scales_with_account,
        uses_live_contract=uses_live,
        contract_size=contract,
        balance_source=source,
        balance=balance,
        blocked=blocked,
        chase=chase_for(spec, entry, sl),
        broker_symbol=broker_symbol,
        copy=text,
    )


def symbol_or_none(symbol_id: str) -> Symbol | None:
    return get_symbol(symbol_id)
