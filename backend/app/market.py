"""Market data provider.

Yahoo Finance is the main provider for market data and background scanner checks.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.strategy import Bar
from app.symbols import Symbol

log = logging.getLogger("desk.market")

_MIN_BARS = 220
_YAHOO_TTL = 60

_yahoo_cache: dict[str, tuple[float, "FetchResult"]] = {}


class FetchResult:
    def __init__(
        self,
        bars: list[Bar],
        source: str,
        error: str | None = None,
        hourly: list[Bar] | None = None,
        m15: list[Bar] | None = None,
        m1: list[Bar] | None = None,
        tradable: bool | None = None,
        skip_reason: str | None = None,
    ) -> None:
        self.bars = bars
        self.source = source
        self.error = error
        self.hourly = list(hourly or [])
        self.m15 = list(m15 or [])
        self.m1 = list(m1 or [])
        self.skip_reason = skip_reason
        self.tradable = (error is None and skip_reason is None) if tradable is None else tradable


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


def _as_utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def resample(bars: list[Bar], minutes: int) -> list[Bar]:
    """Build larger candles. `minutes` is the bucket size (5 or 15)."""
    if minutes <= 0:
        return []
    buckets: dict[datetime, list[Bar]] = {}
    for bar in bars:
        t = _as_utc(bar.time).replace(second=0, microsecond=0)
        bucket = t - timedelta(minutes=t.minute % minutes)
        buckets.setdefault(bucket, []).append(bar)
    out: list[Bar] = []
    for bucket in sorted(buckets):
        group = buckets[bucket]
        out.append(
            Bar(
                bucket,
                group[0].open,
                max(bar.high for bar in group),
                min(bar.low for bar in group),
                group[-1].close,
            )
        )
    return out


def drop_forming(bars: list[Bar], minutes: int, now: datetime | None = None) -> list[Bar]:
    """Drop the candle that has not closed yet."""
    if minutes <= 0:
        return list(bars)
    now = _as_utc(now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    bucket = now - timedelta(minutes=now.minute % minutes)
    out: list[Bar] = []
    for bar in bars:
        t = _as_utc(bar.time)
        if t < bucket:
            out.append(Bar(t, bar.open, bar.high, bar.low, bar.close))
    return out


def session_open(now: datetime | None = None) -> bool:
    """Retail FX is open from Sunday 22:00 UTC until Friday 22:00 UTC."""
    now = _as_utc(now or datetime.now(timezone.utc))
    weekday = now.weekday()
    minute_of_day = now.hour * 60 + now.minute
    if weekday == 5:
        return False
    if weekday == 6 and minute_of_day < 22 * 60:
        return False
    if weekday == 4 and minute_of_day >= 22 * 60:
        return False
    return True


def is_no_trade_window(now: datetime | None = None) -> bool:
    """Blocks new trades between 9:00 PM WAT (20:00 UTC) and 2:00 AM WAT (01:00 UTC)."""
    now = _as_utc(now or datetime.now(timezone.utc))
    hour = now.hour
    return hour >= 20 or hour < 1


def m5_is_fresh(bars: list[Bar], now: datetime | None = None) -> bool:
    """The last closed 5-minute candle has to be from the last quarter hour."""
    if not bars:
        return False
    now = _as_utc(now or datetime.now(timezone.utc))
    last = _as_utc(bars[-1].time)
    age = now - last
    return timedelta(0) <= age <= timedelta(minutes=15)


def series_is_fresh(bars: list[Bar], now: datetime | None = None) -> bool:
    if not bars:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    last = bars[-1].time
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    age = now - last.astimezone(timezone.utc)
    weekend = now.weekday() == 5 or (now.weekday() == 6 and now.hour < 22)
    limit = timedelta(hours=72 if weekend else 8)
    return timedelta(0) <= age <= limit


class YahooMarket(MarketData):
    def fetch(self, spec: Symbol) -> FetchResult:
        now = datetime.now(timezone.utc).timestamp()
        cached = _yahoo_cache.get(spec.id)
        if cached and now - cached[0] < _YAHOO_TTL:
            return cached[1]
        result = self._download(spec)
        if result.error is None:
            _yahoo_cache[spec.id] = (now, result)
        return result

    def _download(self, spec: Symbol) -> FetchResult:
        try:
            import yfinance as yf
        except Exception as exc:  # pragma: no cover
            return FetchResult([], "", f"{spec.display}: market data library is missing ({exc}).")
        errors: list[str] = []
        for ticker in spec.yahoo:
            try:
                df_1h = yf.download(
                    ticker,
                    period="90d",
                    interval="1h",
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
            except Exception as exc:
                errors.append(f"{ticker} (1h): {exc}")
                continue

            bars_1h = _closed(_frame_to_bars(df_1h))
            if len(bars_1h) < _MIN_BARS:
                errors.append(f"{ticker}: not enough closed hours ({len(bars_1h)})")
                continue

            bars_5m: list[Bar] = []
            try:
                df_5m = yf.download(
                    ticker,
                    period="5d",
                    interval="5m",
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
                bars_5m = _frame_to_bars(df_5m)
            except Exception:
                pass

            now_dt = datetime.now(timezone.utc)
            m5 = drop_forming(bars_5m, 5, now_dt) if bars_5m else []
            m15 = drop_forming(resample(m5, 15), 15, now_dt) if m5 else []

            label = f"Yahoo Finance {ticker}"
            if ticker.endswith("=F"):
                label += " (futures — the XM cash price can differ)"

            skip: str | None = None
            tradable = False
            error: str | None = None

            if not session_open(now_dt):
                skip = f"{spec.display}: market is closed, no new 5-minute trade"
            elif is_no_trade_window(now_dt):
                skip = f"{spec.display}: no-trade window active (9:00 PM - 2:00 AM WAT)"
            elif not m5:
                skip = f"{spec.display}: no closed 5-minute candle, so no new trade"
            elif not m5_is_fresh(m5, now_dt):
                skip = f"{spec.display}: last 5-minute candle {m5[-1].time.strftime('%H:%M')} UTC is too old to trade"
            else:
                tradable = True

            return FetchResult(
                m5,
                label,
                error=error,
                hourly=bars_1h,
                m15=m15,
                m1=[],
                tradable=tradable,
                skip_reason=skip,
            )

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
    if _override:
        return _override
    return YahooMarket()


def clear_cache() -> None:
    _yahoo_cache.clear()


def hour_ago(hours: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    base = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return base - timedelta(hours=hours)
