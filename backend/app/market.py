"""Market data provider.

Yahoo Finance is the main provider for 1-minute background scanner checks.
Massive.com API provides high-accuracy MT5 spot candles when a signal is triggered,
as well as on-demand spot requests.
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
_MASSIVE_TTL = 60

_yahoo_cache: dict[str, tuple[float, "FetchResult"]] = {}
_massive_cache: dict[str, tuple[float, "FetchResult"]] = {}
_massive_1h_cache: dict[str, tuple[datetime, list[Bar]]] = {}


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


def _massive_ticker(spec: Symbol) -> str:
    feed = spec.feed.upper()
    if spec.group == "currency":
        return f"C:{feed}"
    if spec.id == "gold":
        return "C:XAUUSD"
    if spec.id == "oil":
        return "C:XTIUSD"
    if spec.id == "brent":
        return "C:XBRUSD"
    return f"C:{feed}"


class MassiveMarket(MarketData):
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = (api_key or get_settings().massive_api_key).strip()

    def fetch(self, spec: Symbol) -> FetchResult:
        now_ts = datetime.now(timezone.utc).timestamp()
        cached = _massive_cache.get(spec.id)
        if cached and now_ts - cached[0] < _MASSIVE_TTL:
            return cached[1]
        result = self._download(spec)
        if result.error:
            log.warning(
                "%s: Massive API unavailable (%s); falling back to Yahoo Finance",
                spec.display,
                result.error,
            )
            fallback_yahoo = YahooMarket().fetch(spec)
            if fallback_yahoo.error is None and (fallback_yahoo.bars or fallback_yahoo.hourly):
                log.info("%s: using %s", spec.display, fallback_yahoo.source)
                return fallback_yahoo
        if result.error is None:
            _massive_cache[spec.id] = (now_ts, result)
        return result

    def _get_with_retry(self, client: httpx.Client, url: str, max_retries: int = 2) -> httpx.Response:
        for attempt in range(max_retries + 1):
            resp = client.get(url)
            if resp.status_code == 429 and attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
                continue
            return resp
        return resp

    def _download(self, spec: Symbol) -> FetchResult:
        if not self.api_key:
            return FetchResult([], "", f"{spec.display}: MASSIVE_API_KEY is not configured.")

        ticker = _massive_ticker(spec)
        now_dt = datetime.now(timezone.utc)
        today_str = now_dt.strftime("%Y-%m-%d")
        from_5m_str = (now_dt - timedelta(days=7)).strftime("%Y-%m-%d")
        from_1h_str = (now_dt - timedelta(days=90)).strftime("%Y-%m-%d")

        hour_stamp = now_dt.replace(minute=0, second=0, microsecond=0)
        cached_1h = _massive_1h_cache.get(spec.id)
        bars_1h: list[Bar] = []

        try:
            with httpx.Client(timeout=10.0, follow_redirects=True) as client:
                if cached_1h and cached_1h[0] == hour_stamp:
                    bars_1h = cached_1h[1]
                else:
                    url_1h = (
                        f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/1/hour/"
                        f"{from_1h_str}/{today_str}?adjusted=true&sort=asc&limit=50000&apiKey={self.api_key}"
                    )
                    resp_1h = self._get_with_retry(client, url_1h)
                    if resp_1h.status_code == 429:
                        return FetchResult([], "", f"{spec.display}: Massive API rate limit (429)")
                    if resp_1h.status_code != 200:
                        return FetchResult([], "", f"{spec.display}: Massive API 1h request returned HTTP {resp_1h.status_code}")
                    data_1h = resp_1h.json()
                    results_1h = data_1h.get("results", [])
                    for item in results_1h:
                        dt = datetime.fromtimestamp(item["t"] / 1000.0, tz=timezone.utc)
                        bars_1h.append(Bar(dt, float(item["o"]), float(item["h"]), float(item["l"]), float(item["c"])))
                    bars_1h = _closed(bars_1h)
                    if len(bars_1h) >= _MIN_BARS:
                        _massive_1h_cache[spec.id] = (hour_stamp, bars_1h)

                if len(bars_1h) < _MIN_BARS:
                    return FetchResult([], "", f"{spec.display}: Massive API returned {len(bars_1h)} closed hours (need {_MIN_BARS}).")

                url_5m = (
                    f"https://api.massive.com/v2/aggs/ticker/{ticker}/range/5/minute/"
                    f"{from_5m_str}/{today_str}?adjusted=true&sort=asc&limit=50000&apiKey={self.api_key}"
                )
                resp_5m = self._get_with_retry(client, url_5m)
                if resp_5m.status_code == 429:
                    return FetchResult([], "", f"{spec.display}: Massive API rate limit (429)")
                bars_5m: list[Bar] = []
                if resp_5m.status_code == 200:
                    data_5m = resp_5m.json()
                    results_5m = data_5m.get("results", [])
                    for item in results_5m:
                        dt = datetime.fromtimestamp(item["t"] / 1000.0, tz=timezone.utc)
                        bars_5m.append(Bar(dt, float(item["o"]), float(item["h"]), float(item["l"]), float(item["c"])))

                m5 = drop_forming(bars_5m, 5, now_dt) if bars_5m else []
                m15 = drop_forming(resample(m5, 15), 15, now_dt) if m5 else []

                label = f"Massive API {ticker}"
                skip: str | None = None
                tradable = False
                error: str | None = None

                if not session_open(now_dt):
                    skip = f"{spec.display}: market is closed, no new 5-minute trade"
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
        except Exception as exc:
            log.warning("%s: Massive API request failed: %s", spec.display, exc)
            return FetchResult([], "", f"{spec.display}: Massive API could not be reached ({exc}).")


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
    _massive_cache.clear()
    _massive_1h_cache.clear()
    _yahoo_cache.clear()


def hour_ago(hours: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    base = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return base - timedelta(hours=hours)
