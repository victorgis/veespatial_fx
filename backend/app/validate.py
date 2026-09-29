"""Checks for the settings form."""

from __future__ import annotations

from app.schemas import SettingsIn
from app.symbols import BY_ID, parse_alias_overrides


def settings_error(body: SettingsIn) -> str | None:
    if body.trade_mode not in ("auto", "manual"):
        return "Choose automatic or signals only."
    if body.account_type not in ("standard", "micro"):
        return "Choose a standard or a micro account."
    if body.platform not in ("mt4", "mt5", "xm"):
        return "Choose MT5, MT4, or the XM app."
    if body.trade_mode == "auto" and body.platform == "xm":
        return "Automatic orders need MT4 or MT5. The XM app is for placing signals yourself."
    if not (0.1 <= body.risk_percent <= 5):
        return "Risk per trade must be between 0.1% and 5%."
    if not (0.01 <= body.max_lot <= 100):
        return "The maximum size must be between 0.01 and 100 lots."
    if type(body.max_open_trades) is not int or not (1 <= body.max_open_trades <= 5):
        return "Open automatic trades must be a whole number from 1 to 5."
    if body.planning_balance < 0 or body.planning_balance > 100_000_000:
        return "Enter a planning balance of zero or more."
    if body.onboarding_done and not body.risk_accepted:
        return "Confirm that you understand you can lose money."
    if not body.enabled_symbols:
        return "Choose at least one market."
    for symbol_id in body.enabled_symbols:
        if symbol_id not in BY_ID:
            return f"Unknown market '{symbol_id}'."
    try:
        parse_alias_overrides(body.alias_overrides)
    except ValueError as exc:
        return str(exc)
    return None
