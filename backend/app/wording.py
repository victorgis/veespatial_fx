"""Sentences shown in the app and in Telegram. Kept here so tests can pin them."""

from __future__ import annotations

from app.sizing import LotResult
from app.symbols import Symbol


def status_line(trade_mode: str, online: bool, mismatch: bool, broker: str | None) -> str:
    if trade_mode == "manual":
        return "You are on signals only. New trades are not sent to a platform."
    if mismatch:
        return "Automatic trading is paused because the account type does not match your platform."
    if not online:
        return "Automatic trading is on, and your platform is not connected."
    name = broker or "Your platform"
    return f"Automatic trading is on. {name} is connected."


def mismatch_message(selected: str, detected: str, fx_symbol: str | None, fx_contract: float | None) -> str:
    label = "standard (1 lot = 100,000)" if detected == "standard" else "micro (1 lot = 1,000)"
    picked = "Standard" if selected == "standard" else "Micro"
    where = fx_symbol or "a forex pair"
    size = f"{fx_contract:,.0f}" if fx_contract else "a different size"
    return (
        f"You chose {picked}, but {where} on your platform has a contract size of {size}. "
        f"That is a {label} account. Automatic orders are paused until these agree."
    )


def rationale(spec: Symbol, side: str, rsi: float) -> str:
    verb = "Buy" if side == "buy" else "Sell"
    bias = "above 50, so the day is bullish" if side == "buy" else "below 50, so the day is bearish"
    level = "75% confirmation level" if side == "buy" else "25% confirmation level"
    return (
        f"{verb} {spec.display}. On the 5-minute chart the nearest swing of at least 40 pips is the active wave. "
        f"Price closed inside its 38.2–61.8 retracement channel, then a whole candle closed beyond the {level}. "
        f"That is an ICWR {'bullish' if side == 'buy' else 'bearish'} signal. "
        f"The daily 14-period RSI is {rsi:.0f}, {bias}. "
        "The stop is 50 pips from the entry. There is no fixed target: the trade exits on the opposite ICWR signal, or at the stop. "
        "This is a rules alert, not a promise of profit."
    )


def _fmt_price(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}"


def _fmt_lots(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


def _example_miss(result: LotResult) -> str:
    """Why this shared example has no lot. It is not an order on anyone's account."""
    if result.min_risk is not None:
        return (
            f"No size in this example. The smallest order is {result.min_lot:.2f} lots "
            f"and would risk about {result.min_risk:.2f}, above {result.risk_cash:.2f}."
        )
    return result.reason or "No size in this example."


def _example_line(label: str, result: LotResult) -> str:
    if result.lots is None:
        return f"{label}  {_example_miss(result)}"
    return f"{label}  {_fmt_lots(result.lots)} lots"


def telegram_message(
    spec: Symbol,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    standard: LotResult,
    micro: LotResult,
    signal_id: int,
    balance: float,
    risk_percent: float,
) -> str:
    verb = "BUY" if side == "buy" else "SELL"
    mark = "▲" if side == "buy" else "▼"
    lines = [
        f"{mark} {verb} {spec.display}",
        spec.pair,
        "Intraday ICWR. 5-minute wave, confirmed by the daily RSI.",
        "",
        f"Entry   {_fmt_price(entry, spec.digits)}",
        f"Stop    {_fmt_price(sl, spec.digits)}",
        "Target  none. Exit on the opposite ICWR signal." if tp == 0 else f"Target  {_fmt_price(tp, spec.digits)}",
        "",
        f"Size for {risk_percent:g}% risk on a {balance:,.0f} USD balance",
    ]
    if spec.scales_with_account:
        lines.append(_example_line("Standard (1 lot = 100,000)", standard))
        lines.append(_example_line("Micro (1 lot = 1,000)", micro))
    else:
        if standard.lots is None:
            lines.append(_example_miss(standard))
        elif spec.group == "index":
            lines.append(f"{_fmt_lots(standard.lots)} lots.")
        else:
            lines.append(
                f"{_fmt_lots(standard.lots)} lots. On XM, 1 lot is {spec.contract_standard:g} {spec.unit}."
            )
    if spec.mt5_only:
        lines.append("XM lists this cash market on MT5.")
    lines += [
        "",
        "Your dashboard shows the size for your own balance.",
        "Automatic accounts place this when MT4 or MT5 is connected and the account type matches.",
        "Signals only: place it yourself, then set this stop. Close it when the opposite signal prints.",
        "",
        f"Signal {signal_id}. A rules alert, not a promise of profit. You can lose money.",
    ]
    return "\n".join(lines)


def close_message(spec: Symbol, side: str, outcome: str, price: float | None) -> str:
    verb = "buy" if side == "buy" else "sell"
    px = _fmt_price(price, spec.digits) if price is not None else "the close"
    if outcome == "target":
        return f"{spec.display} {verb} reached the target at {px}."
    if outcome == "stopped":
        return f"{spec.display} {verb} hit the stop at {px}."
    if outcome == "exit":
        return f"{spec.display} {verb} closed on the opposite ICWR signal at {px}."
    return f"{spec.display} {verb} expired without stop or target. The idea is closed."


def copy_text(
    spec: Symbol,
    side: str,
    entry: float,
    sl: float,
    tp: float,
    account_type: str,
    quote_lots: float | None,
    units: float | None,
    risk_cash: float,
    currency: str,
    reason: str | None,
) -> str:
    verb = "BUY" if side == "buy" else "SELL"
    lines = [
        f"{verb} {spec.display}",
        f"Entry: {_fmt_price(entry, spec.digits)}",
        f"Stop loss: {_fmt_price(sl, spec.digits)}",
        "Take profit: none. Exit when the opposite ICWR signal prints."
        if tp == 0
        else f"Take profit: {_fmt_price(tp, spec.digits)}",
    ]
    if quote_lots is not None:
        label = "Micro" if account_type == "micro" else "Standard"
        unit_bit = f" · {units:,.2f} {spec.unit}" if units is not None else ""
        lines.append(f"Size ({label}): {quote_lots:.2f} lots{unit_bit}")
        lines.append(f"Planned risk about {risk_cash:.2f} {currency} if the stop is hit.")
    elif reason:
        lines.append(reason)
    return "\n".join(lines)
