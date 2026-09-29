"""Hourly candles. Yahoo Finance is the default source and needs no key.

Spot FX comes from Yahoo's =X pairs. Gold tries the spot symbol first, then
COMEX futures. WTI and Brent come from the futures that Yahoo publishes
(CL=F, BZ=F), which can differ from XM's OILCash and BRENTCash quotes.
The copier refuses an order if the broker price has already left the signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.strategy import Bar
from app.symbols import Symbol

_cache: dict[str, tuple[float, "FetchResult"]] = {}
_TTL_SECONDS = 600


@dataclass
class FetchResult:
    bars: list[Bar]
    source: str
    error: str | None = None


class MarketData:
    def fetch(self, spec: Symbol) -> FetchResult:
        raise NotImplementedError


def _closed(bars: list[Bar], now: datetime | None = None) -> list[Bar]:
    """Drop the hour that has not finished yet."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hour_start = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    out = []
    for bar in bars:
        t = bar.time if bar.time.tzinfo else bar.time.replace(tzinfo=timezone.utc)
        if t.astimezone(timezone.utc) < hour_start:
            out.append(Bar(t.astimezone(timezone.utc), bar.open, bar.high, bar.low, bar.close))
    return out


class YahooMarket(MarketData):
    def fetch(self, spec: Symbol) -> FetchResult:
        now = datetime.now(timezone.utc).timestamp()
        cached = _cache.get(spec.id)
        if cached and now - cached[0] < _TTL_SECONDS:
            return cached[1]
        result = self._download(spec)
        if result.error is None:
            _cache[spec.id] = (now, result)
        return result

    def _download(self, spec: Symbol) -> FetchResult:
        try:
            import yfinance as yf
        except Exception as exc:  # pragma: no cover
            return FetchResult([], "", f"{spec.display}: market data library is missing ({exc}).")
        errors: list[str] = []
        for ticker in spec.yahoo:
            try:
                df = yf.download(
                    ticker,
                    period="90d",
                    interval="1h",
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
            except Exception as exc:
                errors.append(f"{ticker}: {exc}")
                continue
            bars = _frame_to_bars(df)
            bars = _closed(bars)
            if len(bars) >= 220:
                label = f"Yahoo Finance {ticker}"
                if ticker.endswith("=F"):
                    label += " (futures — the XM cash price can differ)"
                return FetchResult(bars, label, None)
            errors.append(f"{ticker}: not enough closed hours ({len(bars)})")
        detail = "; ".join(errors) if errors else "no data"
        return FetchResult([], "", f"{spec.display}: {detail}")


def _frame_to_bars(df) -> list[Bar]:  # type: ignore[no-untyped-def]
    if df is None or getattr(df, "empty", True):
        return []
    import pandas as pd

    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=lambda c: str(c).lower())
    bars: list[Bar] = []
    for ts, row in df.iterrows():
        try:
            t = pd.Timestamp(ts)
            if t.tzinfo is None:
                t = t.tz_localize("UTC")
            else:
                t = t.tz_convert("UTC")
            op = float(row["open"])
            hi = float(row["high"])
            lo = float(row["low"])
            cl = float(row["close"])
        except Exception:
            continue
        if any(v != v for v in (op, hi, lo, cl)):  # NaN
            continue
        bars.append(Bar(t.to_pydatetime(), op, hi, lo, cl))
    bars.sort(key=lambda b: b.time)
    return bars


_override: MarketData | None = None


def set_market_override(market: MarketData | None) -> None:
    global _override
    _override = market


def get_market() -> MarketData:
    return _override or YahooMarket()


def clear_cache() -> None:
    _cache.clear()


# Imported by tests that want a bar slightly in the past.
def hour_ago(hours: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    base = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return base - timedelta(hours=hours)
