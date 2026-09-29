"""Position size from a cash risk and a stop distance.

Live broker ticks are preferred. The contract-size math is the estimate used
before a platform connects, and the figure printed in Telegram.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.symbols import Symbol, contract_size_for


@dataclass(frozen=True)
class LotResult:
    lots: float | None
    units: float | None
    contract_size: float
    risk_cash: float
    too_small: bool
    min_lot: float
    min_risk: float | None
    reason: str | None
    approximate: bool


def floor_to_step(value: float, step: float) -> float:
    if value <= 0 or step <= 0:
        return 0.0
    steps = math.floor(value / step + 1e-8)
    return round(steps * step, 2)


def default_min_lot(spec: Symbol, account_type: str, platform: str) -> float:
    if not spec.scales_with_account:
        return 0.01
    # XM micro on MT5 starts at 0.1 lots. MT4 micro starts at 0.01.
    if account_type == "micro" and platform == "mt5":
        return 0.1
    return 0.01


def chase_limit(entry: float, sl: float, pip: float) -> float:
    """How far price may run from the signal before the copier refuses to chase."""
    return max(abs(entry - sl) * 0.25, pip * 2)


def _finish(
    raw: float,
    loss_per_lot: float,
    contract: float,
    risk_cash: float,
    min_lot: float,
    lot_step: float,
    max_lot: float,
    currency: str,
    approximate: bool,
) -> LotResult:
    if loss_per_lot <= 0 or raw <= 0:
        return LotResult(None, None, contract, risk_cash, True, min_lot, None, "The stop is too close to size a trade.", approximate)
    stepped = floor_to_step(raw, lot_step)
    if max_lot > 0:
        stepped = min(stepped, floor_to_step(max_lot, lot_step))
    min_risk = loss_per_lot * min_lot
    if stepped < min_lot:
        return LotResult(
            None,
            None,
            contract,
            risk_cash,
            True,
            min_lot,
            min_risk,
            (
                f"The smallest order is {min_lot:.2f} lots and would risk about "
                f"{min_risk:.2f} {currency}, above your {risk_cash:.2f} {currency} limit. "
                "Nothing will be placed automatically."
            ),
            approximate,
        )
    units = stepped * contract
    return LotResult(stepped, units, contract, risk_cash, False, min_lot, min_risk, None, approximate)


def lots_from_ticks(
    risk_cash: float,
    stop_distance: float,
    tick_size: float,
    tick_value: float,
    contract_size: float,
    min_lot: float,
    lot_step: float,
    max_lot: float,
    currency: str,
) -> LotResult:
    if risk_cash <= 0:
        return LotResult(None, None, contract_size, risk_cash, True, min_lot, None, "Set a balance above zero so a size can be calculated.", False)
    if tick_size <= 0 or tick_value <= 0 or stop_distance <= 0:
        return LotResult(None, None, contract_size, risk_cash, True, min_lot, None, "The platform did not report a usable tick size.", False)
    loss_per_lot = (stop_distance / tick_size) * tick_value
    raw = risk_cash / loss_per_lot if loss_per_lot > 0 else 0
    return _finish(raw, loss_per_lot, contract_size, risk_cash, min_lot, lot_step, max_lot, currency, False)


def value_per_price_unit(spec: Symbol, contract: float, price: float, converters: dict[str, float]) -> tuple[float | None, bool]:
    """USD (or account-currency approximation) gained per 1.0 price move, per lot."""
    if spec.quote_mode == "usd":
        return contract, False
    if spec.quote_mode == "divide":
        if price <= 0:
            return None, False
        return contract / price, False
    if spec.id == "eurgbp":
        rate = converters.get("gbpusd")
        if not rate:
            return None, True
        return contract * rate, True
    if spec.id in ("eurjpy", "gbpjpy"):
        rate = converters.get("usdjpy")
        if not rate:
            return None, True
        return contract / rate, True
    return None, True


def lots_from_contract(
    spec: Symbol,
    account_type: str,
    risk_cash: float,
    entry: float,
    sl: float,
    platform: str,
    max_lot: float,
    currency: str,
    converters: dict[str, float] | None = None,
    min_lot: float | None = None,
    lot_step: float = 0.01,
) -> LotResult:
    contract = contract_size_for(spec, account_type)
    floor_min = default_min_lot(spec, account_type, platform) if min_lot is None else min_lot
    if risk_cash <= 0:
        return LotResult(None, None, contract, risk_cash, True, floor_min, None, "Set a balance above zero so a size can be calculated.", False)
    stop = abs(entry - sl)
    per_unit, approximate = value_per_price_unit(spec, contract, entry, converters or {})
    if per_unit is None:
        return LotResult(
            None,
            None,
            contract,
            risk_cash,
            False,
            floor_min,
            None,
            "Connect the platform for an exact size. This cross needs a live tick value.",
            True,
        )
    loss_per_lot = stop * per_unit
    raw = risk_cash / loss_per_lot if loss_per_lot > 0 else 0
    return _finish(raw, loss_per_lot, contract, risk_cash, floor_min, lot_step, max_lot, currency, approximate)


def detect_account_type(fx_contract: float | None) -> str | None:
    if fx_contract is None or fx_contract <= 0:
        return None
    if 50_000 <= fx_contract <= 200_000:
        return "standard"
    if 500 <= fx_contract <= 5_000:
        return "micro"
    return None
