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
    trend = "uptrend" if side == "buy" else "downtrend"
    held = "above the last 15-minute swing low" if side == "buy" else "below the last 15-minute swing high"
    return (
        f"{verb} {spec.display}. The 1-hour trend is an {trend}: price and the 50-hour average "
        f"are on the same side of the 200-hour average, and the 15-minute swings agree. "
        f"On the last closed 15-minute candle RSI is {rsi:.0f}, inside the pullback band, and MACD momentum "
        f"is turning with the trend. Price closed back through the 15-minute 50-bar average and is still {held}. "
        "The stop is beyond that recent swing. The target matches the stop distance (1:1). "
        "This is a rules alert, not a promise of profit."
    )


def _fmt_price(value: float, digits: int) -> str:
    return f"{value:,.{digits}f}"


def _fmt_lots(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}"


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
        "15-minute pullback inside the 1-hour trend.",
        "",
        f"Entry   {_fmt_price(entry, spec.digits)}",
        f"Stop    {_fmt_price(sl, spec.digits)}",
        f"Target  {_fmt_price(tp, spec.digits)}",
        "",
        f"Size for {risk_percent:g}% risk on {balance:,.0f}",
    ]
    if spec.scales_with_account:
        lines.append(f"Standard (1 lot = 100,000)  {_fmt_lots(standard.lots)} lots")
        lines.append(f"Micro (1 lot = 1,000)       {_fmt_lots(micro.lots)} lots")
        if standard.lots is None and standard.reason:
            lines.append(standard.reason)
    else:
        if spec.group == "index":
            lines.append(f"{_fmt_lots(standard.lots)} lots.")
        else:
            lines.append(
                f"{_fmt_lots(standard.lots)} lots. On XM, 1 lot is {spec.contract_standard:g} {spec.unit}."
            )
        if standard.lots is None and standard.reason:
            lines.append(standard.reason)
    if spec.mt5_only:
        lines.append("XM lists this cash market on MT5.")
    lines += [
        "",
        "Your dashboard shows the size for your own balance.",
        "Automatic accounts place this when MT4 or MT5 is connected and the account type matches.",
        "Signals only: place it yourself, then set this stop and target.",
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
        f"Take profit: {_fmt_price(tp, spec.digits)}",
    ]
    if quote_lots is not None:
        label = "Micro" if account_type == "micro" else "Standard"
        unit_bit = f" · {units:,.2f} {spec.unit}" if units is not None else ""
        lines.append(f"Size ({label}): {quote_lots:.2f} lots{unit_bit}")
        lines.append(f"Planned risk about {risk_cash:.2f} {currency} if the stop is hit.")
    elif reason:
        lines.append(reason)
    return "\n".join(lines)
