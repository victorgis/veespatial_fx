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
# XM micro names: EURUSDmicro, EURUSD.micro, EURUSDm, EURUSDm#.
_XM_SUFFIXES = ("", "micro", ".micro", "m", "m#", "#", ".", ".m")


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
    # Real-time market feed name and the integer divisor that turns its prices into quotes.
    feed: str = ""
    price_divisor: int = 100_000


def xm_names(*roots: str) -> tuple[str, ...]:
    """Standard, micro, ultra-low, and dotted XM names for each root."""
    out: list[str] = []
    seen: set[str] = set()
    for root in roots:
        for suffix in _XM_SUFFIXES:
            name = root + suffix
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(name)
    return tuple(out)


def with_micro_forms(aliases: tuple[str, ...]) -> tuple[str, ...]:
    extra: list[str] = []
    for name in aliases:
        extra.append(name + "micro")
        extra.append(name + ".micro")
    return tuple(dict.fromkeys((*aliases, *extra)))


def is_micro_symbol_name(name: str) -> bool:
    """True for XM micro spellings such as EURUSDmicro, EURUSD.micro, EURUSDm."""
    token = (name or "").upper()
    if not token:
        return False
    if "MICRO" in token:
        return True
    if token.endswith("M#") or token.endswith(".M"):
        return True
    if token.endswith("M") and len(token) >= 2 and not token[-2].isdigit():
        return True
    return False


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
        aliases=xm_names(base),
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
        aliases=xm_names("GOLD", "XAUUSD"),
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
        id="silver",
        display="Silver",
        pair="Silver vs US dollar",
        group="metal",
        yahoo=("SI=F", "XAGUSD=X"),
        aliases=xm_names("SILVER", "SILVERCash", "XAGUSD"),
        contract_standard=5000,  # troy ounces
        scales_with_account=True,
        pip=0.01,
        digits=3,
        unit="oz",
        quote_mode="usd",
        mt5_only=False,
        note="On XM, standard silver is named SILVER (5000 oz) and micro silver SILVERmicro (50 oz).",
        feed="XAGUSD",
        price_divisor=1000,
    ),
    Symbol(
        id="oil",
        display="WTI cash",
        pair="West Texas crude, cash",
        group="energy",
        yahoo=("CL=F",),
        aliases=with_micro_forms(("OILCash", "OILCash#", "OILCash.m", "USOIL", "WTI", "XTIUSD")),
        contract_standard=100,  # barrels
        scales_with_account=False,
        pip=0.01,
        digits=3,
        unit="barrels",
        quote_mode="usd",
        mt5_only=True,
        note="XM lists this as OILCash, 100 barrels per lot, on MT5.",
        feed="LIGHTCMDUSD",
        price_divisor=1000,
    ),
    Symbol(
        id="brent",
        display="Brent cash",
        pair="Brent crude, cash",
        group="energy",
        yahoo=("BZ=F",),
        aliases=with_micro_forms(("BRENTCash", "BRENTCash#", "BRENTCash.m", "UKOIL", "XBRUSD")),
        contract_standard=100,
        scales_with_account=False,
        pip=0.01,
        digits=3,
        unit="barrels",
        quote_mode="usd",
        mt5_only=True,
        note="XM lists this as BRENTCash, 100 barrels per lot, on MT5.",
        feed="BRENTCMDUSD",
        price_divisor=1000,
    ),
    Symbol(
        id="copper",
        display="Copper",
        pair="High Grade Copper",
        group="commodity",
        yahoo=("HG=F",),
        aliases=with_micro_forms(("HGCOP", "HGCOP#", "COPPER", "COPPER#", "COPPERCash", "COPPERCash#", "HGCOPPER", "COPPER.c")),
        contract_standard=2000,  # lbs. XM's HGCOP contract is 2,000 lbs.
        scales_with_account=False,
        pip=0.001,
        digits=4,
        unit="lbs",
        quote_mode="usd",
        mt5_only=True,
        note="XM lists high grade copper as HGCOP, 2,000 lbs per lot. A month code such as HGCOP-DEC26 is the same market.",
    ),
    Symbol(
        id="ngas",
        display="Natural Gas",
        pair="Natural Gas, cash",
        group="energy",
        yahoo=("NG=F",),
        aliases=with_micro_forms(("NGASCash", "NGASCash#", "NATGASCash", "NATGASCash#", "NGAS", "NGAS#", "NATGAS", "NGAS.c", "NGAS.m")),
        contract_standard=1000,  # MMBtu
        scales_with_account=False,
        pip=0.001,
        digits=3,
        unit="MMBtu",
        quote_mode="usd",
        mt5_only=True,
        note="XM lists natural gas cash as NGASCash, 1,000 MMBtu per lot, on MT5.",
    ),
    Symbol(
        id="soybean",
        display="US Soybeans",
        pair="US Soybeans",
        group="commodity",
        yahoo=("ZS=F",),
        aliases=with_micro_forms(("SBEAN", "SBEAN#", "SOYBEAN", "SOYBEAN#", "SOYBEANCash", "SOYBEANCash#", "SOYBEAN.c", "SOY")),
        contract_standard=400,  # bushels. XM's SBEAN contract is 400 bushels.
        scales_with_account=False,
        pip=0.01,
        digits=2,
        unit="bushels",
        quote_mode="usd",
        mt5_only=True,
        note="XM lists US soybeans as SBEAN, 400 bushels per lot. Yahoo quotes cents per bushel; the copier rescales the stop onto the MT5 price.",
    ),
    Symbol(
        id="us30",
        display="US30",
        pair="Dow Jones 30 Cash",
        group="index",
        yahoo=("^DJI", "YM=F"),
        aliases=with_micro_forms(("US30", "US30Cash", "US30Cash#", "US30#", "DJ30", "USA30", "US30.pro", "US30.m", "WS30")),
        contract_standard=1.0,  # 1 point per lot
        scales_with_account=False,
        pip=1.0,
        digits=2,
        unit="points",
        quote_mode="usd",
        mt5_only=True,
        note="US30 Dow Jones cash index.",
    ),
    Symbol(
        id="us100",
        display="US100",
        pair="Nasdaq 100 Cash",
        group="index",
        yahoo=("^NDX", "NQ=F"),
        aliases=with_micro_forms(("US100", "US100Cash", "US100Cash#", "US100#", "NAS100", "USTECH", "US100.pro", "US100.m")),
        contract_standard=1.0,  # 1 point per lot
        scales_with_account=False,
        pip=1.0,
        digits=2,
        unit="points",
        quote_mode="usd",
        mt5_only=True,
        note="US100 Nasdaq cash index.",
    ),
    Symbol(
        id="us500",
        display="US500",
        pair="S&P 500 Cash",
        group="index",
        yahoo=("^GSPC", "ES=F"),
        aliases=with_micro_forms(("US500", "US500Cash", "US500Cash#", "US500#", "SPX500", "US500.pro", "US500.m")),
        contract_standard=1.0,  # 1 point per lot
        scales_with_account=False,
        pip=0.1,
        digits=2,
        unit="points",
        quote_mode="usd",
        mt5_only=True,
        note="US500 S&P 500 cash index.",
    ),
    Symbol(
        id="ger40",
        display="GER40",
        pair="DAX 40 Cash",
        group="index",
        yahoo=("^GDAXI", "FDAX=F"),
        aliases=with_micro_forms(("GER40", "GER40Cash", "GER40Cash#", "GER40#", "DE40", "GER30", "GER40.pro", "GER40.m")),
        contract_standard=1.0,  # 1 point per lot
        scales_with_account=False,
        pip=1.0,
        digits=2,
        unit="points",
        quote_mode="usd",
        mt5_only=True,
        note="Germany DAX 40 cash index.",
    ),
    Symbol(
        id="jp225",
        display="JP225",
        pair="Nikkei 225 Cash",
        group="index",
        yahoo=("^N225", "NKD=F"),
        aliases=with_micro_forms(("JP225", "JP225Cash", "JP225Cash#", "JP225#", "JPN225", "JP225.pro", "JP225.m")),
        contract_standard=100.0,
        scales_with_account=False,
        pip=1.0,
        digits=2,
        unit="points",
        quote_mode="usd",
        mt5_only=True,
        note="Japan Nikkei 225 cash index.",
    ),
    Symbol(
        id="vix",
        display="VIX",
        pair="S&P 500 Volatility Index",
        group="index",
        yahoo=("^VIX", "VX=F"),
        aliases=with_micro_forms(("VOLX", "VOLXCash", "VIX", "VOLX#", "VIX#", "VOLX.c", "VIX.c")),
        contract_standard=100.0,
        scales_with_account=False,
        pip=0.01,
        digits=2,
        unit="points",
        quote_mode="usd",
        mt5_only=True,
        note="VIX Volatility Index.",
    ),
    Symbol(
        id="dxy",
        display="DXY",
        pair="US Dollar Index",
        group="index",
        yahoo=("DX-Y.NYB", "DXY=F"),
        aliases=with_micro_forms(("USDX", "USDXCash", "DXY", "USDX#", "DXY#", "USDX.c")),
        contract_standard=100.0,
        scales_with_account=False,
        pip=0.01,
        digits=3,
        unit="points",
        quote_mode="usd",
        mt5_only=True,
        note="US Dollar Index.",
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


_PREFIX_BREAK = set("#.-_")


def broker_symbol_matches(broker_symbol: str, aliases: tuple[str, ...] | set[str]) -> bool:
    """True when the platform name is an alias, or a month code built on one.

    XM lists copper as HGCOP and sometimes HGCOP-DEC26. The month suffix is
    still the same market. Short aliases are exact only, so SOY does not
    swallow an unrelated name.
    """
    name = (broker_symbol or "").upper()
    if not name:
        return False
    for alias in aliases:
        token = alias.upper()
        if not token:
            continue
        if name == token:
            return True
        if len(token) < 4 or not name.startswith(token):
            continue
        if name[len(token)] in _PREFIX_BREAK:
            return True
    return False


def aliases_for(spec: Symbol, overrides_text: str, account_type: str | None = None) -> tuple[str, ...]:
    extra: list[str] = []
    try:
        extra = parse_alias_overrides(overrides_text).get(spec.id, [])
    except ValueError:
        extra = []
    # User names first so a custom symbol wins the closest-size sort when tied.
    seen: list[str] = []
    rest = [name for name in spec.aliases if name not in extra]
    if account_type == "micro":
        rest.sort(key=lambda name: (0 if is_micro_symbol_name(name) else 1, len(name), name))
    elif account_type == "standard":
        rest.sort(key=lambda name: (0 if not is_micro_symbol_name(name) else 1, len(name), name))
    for name in list(extra) + rest:
        if name not in seen:
            seen.append(name)
    return tuple(seen)
