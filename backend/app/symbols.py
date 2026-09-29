"""Markets the desk watches.

Contract sizes follow XM's published specifications:
- Standard FX: 1 lot = 100,000. Micro FX: 1 lot = 1,000.
- Gold: 100 oz on standard, 1 oz on micro (the same 100× relationship).
- OILCash and BRENTCash: 100 barrels per lot. XM does not shrink that
  contract on a micro FX account, so oil does not use the 100× lot scaling.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_ALIAS = re.compile(r"^[A-Za-z0-9._#]{2,32}$")


@dataclass(frozen=True)
class Symbol:
    id: str
    display: str
    pair: str
    group: str  # currency | metal | energy
    yahoo: tuple[str, ...]
    aliases: tuple[str, ...]
    contract_standard: float
    scales_with_account: bool
    pip: float
    digits: int
    unit: str
    # usd: quote currency is USD. divide: P&L is in the quote and USD = pnl/price
    # (USDJPY, USDCHF, USDCAD). cross: needs another pair's price.
    quote_mode: str
    mt5_only: bool
    note: str
    # Dukascopy public feed name and the integer divisor that turns its prices into quotes.
    feed: str = ""
    price_divisor: int = 100_000


def _fx(
    id_: str,
    display: str,
    pair: str,
    yahoo: str,
    pip: float,
    digits: int,
    unit: str,
    quote_mode: str,
) -> Symbol:
    base = id_.upper()
    return Symbol(
        id=id_,
        display=display,
        pair=pair,
        group="currency",
        yahoo=(yahoo,),
        aliases=(base, base + "m", base + "micro", base + "#", base + ".", base + ".m"),
        contract_standard=100_000,
        scales_with_account=True,
        pip=pip,
        digits=digits,
        unit=unit,
        quote_mode=quote_mode,
        mt5_only=False,
        note="",
        feed=base,
        price_divisor=1000 if id_.endswith("jpy") else 100_000,
    )


SYMBOLS: tuple[Symbol, ...] = (
    _fx("eurusd", "EURUSD", "Euro / US dollar", "EURUSD=X", 0.0001, 5, "EUR", "usd"),
    _fx("gbpusd", "GBPUSD", "Sterling / US dollar", "GBPUSD=X", 0.0001, 5, "GBP", "usd"),
    _fx("usdjpy", "USDJPY", "US dollar / yen", "USDJPY=X", 0.01, 3, "USD", "divide"),
    _fx("usdchf", "USDCHF", "US dollar / franc", "USDCHF=X", 0.0001, 5, "USD", "divide"),
    _fx("audusd", "AUDUSD", "Australian dollar / US dollar", "AUDUSD=X", 0.0001, 5, "AUD", "usd"),
    _fx("usdcad", "USDCAD", "US dollar / Canadian dollar", "USDCAD=X", 0.0001, 5, "USD", "divide"),
    _fx("nzdusd", "NZDUSD", "New Zealand dollar / US dollar", "NZDUSD=X", 0.0001, 5, "NZD", "usd"),
    _fx("eurgbp", "EURGBP", "Euro / sterling", "EURGBP=X", 0.0001, 5, "EUR", "cross"),
    _fx("eurjpy", "EURJPY", "Euro / yen", "EURJPY=X", 0.01, 3, "EUR", "cross"),
    _fx("gbpjpy", "GBPJPY", "Sterling / yen", "GBPJPY=X", 0.01, 3, "GBP", "cross"),
    Symbol(
        id="gold",
        display="Gold",
        pair="Gold vs US dollar",
        group="metal",
        yahoo=("GC=F", "XAUUSD=X"),
        aliases=("GOLD", "GOLD#", "XAUUSD", "XAUUSD#", "GOLDmicro", "GOLDm#", "XAUUSDmicro", "XAUUSDm"),
        contract_standard=100,  # troy ounces
        scales_with_account=True,
        pip=0.01,
        digits=2,
        unit="oz",
        quote_mode="usd",
        mt5_only=False,
        note="On XM, standard gold is usually named GOLD (100 oz) and micro gold GOLDmicro (1 oz).",
        feed="XAUUSD",
        price_divisor=1000,
    ),
    Symbol(
        id="oil",
        display="WTI cash",
        pair="West Texas crude, cash",
        group="energy",
        yahoo=("CL=F",),
        aliases=("OILCash", "OILCash#", "USOIL", "WTI", "XTIUSD"),
        contract_standard=100,  # barrels
        scales_with_account=False,
        pip=0.01,
        digits=3,
        unit="barrels",
        quote_mode="usd",
        mt5_only=True,
        note="XM lists this as OILCash, 100 barrels per lot, on MT5. The cash contract is not on MT4.",
        feed="LIGHTCMDUSD",
        price_divisor=1000,
    ),
    Symbol(
        id="brent",
        display="Brent cash",
        pair="Brent crude, cash",
        group="energy",
        yahoo=("BZ=F",),
        aliases=("BRENTCash", "BRENTCash#", "UKOIL", "XBRUSD"),
        contract_standard=100,
        scales_with_account=False,
        pip=0.01,
        digits=3,
        unit="barrels",
        quote_mode="usd",
        mt5_only=True,
        note="XM lists this as BRENTCash, 100 barrels per lot, on MT5. The cash contract is not on MT4.",
        feed="BRENTCMDUSD",
        price_divisor=1000,
    ),
)

BY_ID: dict[str, Symbol] = {s.id: s for s in SYMBOLS}
ALL_IDS: tuple[str, ...] = tuple(s.id for s in SYMBOLS)


def get_symbol(symbol_id: str) -> Symbol | None:
    return BY_ID.get(symbol_id)


def contract_size_for(spec: Symbol, account_type: str) -> float:
    if account_type == "micro" and spec.scales_with_account:
        return spec.contract_standard / 100.0
    return spec.contract_standard


def parse_alias_overrides(text: str) -> dict[str, list[str]]:
    """Lines like `oil=OILCash.pro`. Blank lines are ignored."""
    out: dict[str, list[str]] = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Could not read '{line}'. Use symbol=Name, for example oil=OILCash.")
        key, name = (p.strip() for p in line.split("=", 1))
        key = key.lower()
        if key not in BY_ID:
            known = ", ".join(ALL_IDS)
            raise ValueError(f"Unknown market '{key}'. Known markets: {known}.")
        if not _ALIAS.match(name):
            raise ValueError(f"'{name}' is not a usable symbol name.")
        out.setdefault(key, [])
        if name not in out[key]:
            out[key].append(name)
    return out


def aliases_for(spec: Symbol, overrides_text: str) -> tuple[str, ...]:
    extra: list[str] = []
    try:
        extra = parse_alias_overrides(overrides_text).get(spec.id, [])
    except ValueError:
        extra = []
    # User names first so a custom symbol wins the closest-size sort when tied.
    seen: list[str] = []
    for name in list(extra) + list(spec.aliases):
        if name not in seen:
            seen.append(name)
    return tuple(seen)
