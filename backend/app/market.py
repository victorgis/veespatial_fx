"""Hourly candles.

Dukascopy's public bid feed is the source. It needs no key and answers from
a cloud host, which Yahoo Finance often refuses. A finished month is one
hourly file. The month still in progress is built from that month's minute
files. Yahoo remains the fallback.

WTI and Brent are Dukascopy cash CFDs (LIGHTCMDUSD, BRENTCMDUSD). They can
still differ from XM's OILCash and BRENTCash. The copier skips an order when
the broker price has already left the signal.
"""

from __future__ import annotations

import logging
import lzma
import struct
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.strategy import Bar
from app.symbols import Symbol

log = logging.getLogger("desk.market")

_RECORD = struct.Struct(">5If")
_TICK = struct.Struct(">3I2f")
_FEED = "https://datafeed.dukascopy.com/datafeed"
_MIN_BARS = 220

# Completed months and completed days do not change, so they stay for the life of the process.
_month_cache: dict[tuple[str, int, int], list[Bar]] = {}
_day_cache: dict[tuple[str, datetime], list[Bar]] = {}
# Closed hours built from tick files. None means the hour file is absent.
_tick_cache: dict[tuple[str, datetime], Bar | None] = {}
# Minute bars from a tick hour. A None expiry is a closed hour, kept for the process.
# The hour still forming expires so the next scan sees new ticks.
_tick_minute_cache: dict[tuple[str, datetime], tuple[float | None, list[Bar]]] = {}
# Completed days of 1-minute candles. Today's file is not published until the day ends.
_minute_day_cache: dict[tuple[str, datetime], list[Bar]] = {}
_CURRENT_HOUR_TTL = 60.0
# Successful series, reused until the next UTC hour.
_hour_cache: dict[str, tuple[datetime, "FetchResult"]] = {}
_yahoo_cache: dict[str, tuple[float, "FetchResult"]] = {}
_YAHOO_TTL = 600


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
        # Callers that only pass candles are asking for a decision on those candles.
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


def decode_bid_candles(blob: bytes, origin: datetime, divisor: int) -> list[Bar]:
    """Dukascopy bid candles: time, open, close, low, high, volume. Time is seconds from origin.

    A row with no volume and a flat price is padding for a closed hour. Those rows are dropped.
    """
    if not blob or divisor <= 0:
        return []
    try:
        raw = lzma.decompress(blob)
    except lzma.LZMAError:
        return []
    if len(raw) % _RECORD.size:
        return []
    if origin.tzinfo is None:
        origin = origin.replace(tzinfo=timezone.utc)
    bars: list[Bar] = []
    for time_s, op, cl, lo, hi, vol in _RECORD.iter_unpack(raw):
        if vol <= 0 and op == hi == lo == cl:
            continue
        if min(op, cl, lo, hi) <= 0 or hi < lo or hi < op or hi < cl or lo > op or lo > cl:
            continue
        when = origin + timedelta(seconds=int(time_s))
        scale = float(divisor)
        bars.append(Bar(when, op / scale, hi / scale, lo / scale, cl / scale))
    return bars


def decode_hour_ticks(blob: bytes, hour: datetime, divisor: int) -> Bar | None:
    """One hour of Dukascopy ticks. Bid is the third field. The bar opens at `hour`."""
    if not blob or divisor <= 0:
        return None
    try:
        raw = lzma.decompress(blob)
    except lzma.LZMAError:
        return None
    if len(raw) % _TICK.size:
        return None
    if hour.tzinfo is None:
        hour = hour.replace(tzinfo=timezone.utc)
    bids: list[int] = []
    for _ms, _ask, bid, _ask_vol, _bid_vol in _TICK.iter_unpack(raw):
        if bid > 0:
            bids.append(bid)
    if not bids:
        return None
    scale = float(divisor)
    return Bar(hour, bids[0] / scale, max(bids) / scale, min(bids) / scale, bids[-1] / scale)


def decode_tick_minutes(blob: bytes, hour: datetime, divisor: int) -> list[Bar]:
    """One hour of Dukascopy ticks, grouped into 1-minute bid candles."""
    if not blob or divisor <= 0:
        return []
    try:
        raw = lzma.decompress(blob)
    except lzma.LZMAError:
        return []
    if len(raw) % _TICK.size:
        return []
    if hour.tzinfo is None:
        hour = hour.replace(tzinfo=timezone.utc)
    buckets: dict[int, list[int]] = {}
    for ms, _ask, bid, _ask_vol, _bid_vol in _TICK.iter_unpack(raw):
        if bid <= 0:
            continue
        minute = min(59, int(ms) // 60_000)
        buckets.setdefault(minute, []).append(bid)
    scale = float(divisor)
    bars: list[Bar] = []
    for minute in sorted(buckets):
        bids = buckets[minute]
        when = hour + timedelta(minutes=minute)
        bars.append(Bar(when, bids[0] / scale, max(bids) / scale, min(bids) / scale, bids[-1] / scale))
    return bars


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


def minutes_to_hours(minutes: list[Bar]) -> list[Bar]:
    buckets: dict[datetime, list[Bar]] = {}
    for bar in minutes:
        t = bar.time if bar.time.tzinfo else bar.time.replace(tzinfo=timezone.utc)
        hour = t.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(hour, []).append(bar)
    hours: list[Bar] = []
    for hour in sorted(buckets):
        group = buckets[hour]
        hours.append(
            Bar(
                hour,
                group[0].open,
                max(bar.high for bar in group),
                min(bar.low for bar in group),
                group[-1].close,
            )
        )
    return hours


def series_is_fresh(bars: list[Bar], now: datetime | None = None) -> bool:
    """True when the last hour is recent enough to trade.

    Saturday and Sunday morning are judged against Friday's close. On a
    weekday the last hour has to be from the current session.
    """
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


def _sane(spec: Symbol, bars: list[Bar]) -> bool:
    if len(bars) < _MIN_BARS:
        return False
    price = bars[-1].close
    feed = spec.feed.upper()
    if feed.endswith("JPY"):
        return 50 <= price <= 400
    if spec.id == "gold":
        return 500 <= price <= 20_000
    if spec.group == "energy":
        return 5 <= price <= 400
    return 0.2 <= price <= 5


def _month_start(year: int, month: int) -> datetime:
    return datetime(year, month, 1, tzinfo=timezone.utc)


def _shift_month(year: int, month: int, back: int) -> tuple[int, int]:
    month -= back
    while month <= 0:
        month += 12
        year -= 1
    return year, month


def _get(client: httpx.Client, url: str) -> bytes | None:
    """Return the body, b'' for a missing file, or None when the request failed."""
    for attempt in range(4):
        try:
            response = client.get(url)
        except httpx.HTTPError:
            response = None
        if response is not None and response.status_code == 404:
            return b""
        if response is not None and response.status_code == 200 and response.content:
            return response.content
        if attempt < 3:
            time.sleep(0.5 * (attempt + 1))
    return None


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
            if len(bars) >= _MIN_BARS:
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


class DeskMarket(MarketData):
    def fetch(self, spec: Symbol) -> FetchResult:
        """5-minute candles for the decision, plus the higher timeframes that filter it.

        The hourly series stays cached until the next UTC hour. The hour that is
        still printing is reread about once a minute, which is what lets a closed
        5-minute candle show up without waiting for the hour to finish.
        """
        now = datetime.now(timezone.utc)
        minutes = self._recent_minutes(spec, now)
        m1 = drop_forming(minutes, 1, now)
        m5 = drop_forming(resample(m1, 5), 5, now)
        m15 = drop_forming(resample(m1, 15), 15, now)
        hourly = self._hourly(spec)
        source = f"Dukascopy {spec.feed} bid" if m5 and spec.feed else hourly.source
        if spec.group == "energy" and source.startswith("Dukascopy") and "cash CFD" not in source:
            source += " (cash CFD — the XM price can differ)"
        skip: str | None = None
        tradable = False
        error: str | None = None
        if not session_open(now):
            skip = f"{spec.display}: market is closed, no new 5-minute trade"
        elif not m5:
            skip = f"{spec.display}: no closed 5-minute candle, so no new trade"
            if not hourly.bars:
                error = hourly.error or skip
        elif not m5_is_fresh(m5, now):
            skip = f"{spec.display}: last 5-minute candle {m5[-1].time.strftime('%H:%M')} UTC is too old to trade"
        else:
            tradable = True
        return FetchResult(
            m5,
            source,
            error,
            hourly=hourly.bars,
            m15=m15,
            m1=m1,
            tradable=tradable,
            skip_reason=skip,
        )

    def _hourly(self, spec: Symbol) -> FetchResult:
        hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        cached = _hour_cache.get(spec.id)
        if cached and cached[0] == hour and cached[1].error is None:
            return cached[1]
        result = self._dukascopy(spec)
        if result.error:
            log.warning("%s", result.error)
            fallback = YahooMarket().fetch(spec)
            if fallback.error is None:
                log.info("%s: using %s", spec.display, fallback.source)
                result = fallback
        if result.error is None:
            _hour_cache[spec.id] = (hour, result)
        return result

    def _dukascopy(self, spec: Symbol) -> FetchResult:
        if not spec.feed or spec.price_divisor <= 0:
            return FetchResult([], "", f"{spec.display}: no price feed is configured.")
        today = datetime.now(timezone.utc).date()
        try:
            with httpx.Client(
                timeout=12,
                headers={"User-Agent": "Mozilla/5.0"},
                follow_redirects=True,
            ) as client:
                bars = self._history(client, spec, today)
        except Exception as exc:
            log.warning("%s: Dukascopy request failed: %s", spec.display, type(exc).__name__)
            return FetchResult([], "", f"{spec.display}: price feed could not be reached.")
        bars = _closed(bars)
        if not series_is_fresh(bars):
            return FetchResult([], "", f"{spec.display}: the newest hour is too old to trade.")
        if not _sane(spec, bars):
            return FetchResult(
                [],
                "",
                f"{spec.display}: Dukascopy returned {len(bars)} usable hours.",
            )
        label = f"Dukascopy {spec.feed} bid"
        if spec.group == "energy":
            label += " (cash CFD — the XM price can differ)"
        log.info("%s: %s closed hours from %s", spec.display, len(bars), label)
        return FetchResult(bars, label, None)

    def _history(self, client: httpx.Client, spec: Symbol, today) -> list[Bar]:  # type: ignore[no-untyped-def]
        merged: dict[datetime, Bar] = {}
        year, month = today.year, today.month
        for back in (2, 1):
            past_year, past_month = _shift_month(year, month, back)
            for bar in self._month(client, spec, past_year, past_month):
                merged[bar.time] = bar
        for bar in self._current_month(spec, today):
            merged[bar.time] = bar
        for bar in self._today_ticks(spec):
            merged[bar.time] = bar
        return [merged[key] for key in sorted(merged)]

    def _month(self, client: httpx.Client, spec: Symbol, year: int, month: int) -> list[Bar]:
        key = (spec.feed, year, month)
        cached = _month_cache.get(key)
        if cached is not None:
            return cached
        url = f"{_FEED}/{spec.feed}/{year}/{month - 1:02d}/BID_candles_hour_1.bi5"
        blob = _get(client, url)
        if not blob:
            return []
        bars = decode_bid_candles(blob, _month_start(year, month), spec.price_divisor)
        _month_cache[key] = bars
        return bars

    def _current_month(self, spec: Symbol, today) -> list[Bar]:  # type: ignore[no-untyped-def]
        year, month = today.year, today.month
        hours: list[Bar] = []
        pending: list[int] = []
        # Today's minute file is published after the day ends. Hours so far come from tick files.
        for day in range(1, today.day):
            stamp = datetime(year, month, day, tzinfo=timezone.utc)
            cached = _day_cache.get((spec.feed, stamp))
            if cached is not None and day < today.day:
                hours.extend(cached)
            else:
                pending.append(day)
        if not pending:
            return hours
        fetched = self._fetch_days(spec, year, month, pending)
        for day, day_hours, remember in fetched:
            stamp = datetime(year, month, day, tzinfo=timezone.utc)
            if remember and day < today.day:
                _day_cache[(spec.feed, stamp)] = day_hours
            hours.extend(day_hours)
        hours.sort(key=lambda bar: bar.time)
        return hours

    def _today_ticks(self, spec: Symbol) -> list[Bar]:
        now = datetime.now(timezone.utc)
        pending: list[datetime] = []
        hours: list[Bar] = []
        for hour_n in range(now.hour):
            stamp = now.replace(hour=hour_n, minute=0, second=0, microsecond=0)
            key = (spec.feed, stamp)
            if key in _tick_cache:
                cached = _tick_cache[key]
                if cached is not None:
                    hours.append(cached)
                continue
            remembered = self._stored_minutes(spec, stamp, time.monotonic())
            if remembered is not None:
                built = minutes_to_hours(remembered)
                bar = built[0] if built else None
                _tick_cache[key] = bar
                if bar is not None:
                    hours.append(bar)
                continue
            pending.append(stamp)
        if not pending:
            return hours
        for stamp, bar, remember in self._fetch_tick_hours(spec, pending):
            if remember:
                _tick_cache[(spec.feed, stamp)] = bar
            if bar is not None:
                hours.append(bar)
        hours.sort(key=lambda bar: bar.time)
        return hours

    def _fetch_tick_hours(
        self, spec: Symbol, stamps: list[datetime]
    ) -> list[tuple[datetime, Bar | None, bool]]:
        def one(stamp: datetime) -> tuple[datetime, Bar | None, bool]:
            url = (
                f"{_FEED}/{spec.feed}/{stamp.year}/{stamp.month - 1:02d}/"
                f"{stamp.day:02d}/{stamp.hour:02d}h_ticks.bi5"
            )
            with httpx.Client(timeout=12, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as local:
                blob = _get(local, url)
            if blob is None:
                return stamp, None, False
            return stamp, decode_hour_ticks(blob, stamp, spec.price_divisor), True

        # Newest first, and one at a time. A burst of connections is what this host drops.
        return [one(stamp) for stamp in sorted(stamps, reverse=True)]

    def _fetch_days(
        self,
        spec: Symbol,
        year: int,
        month: int,
        days: list[int],
    ) -> list[tuple[int, list[Bar], bool]]:
        def one(day: int) -> tuple[int, list[Bar], bool]:
            url = f"{_FEED}/{spec.feed}/{year}/{month - 1:02d}/{day:02d}/BID_candles_min_1.bi5"
            # A client is not shared across threads. One slow day must not corrupt the others.
            with httpx.Client(timeout=12, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as local:
                blob = _get(local, url)
            if blob is None:
                return day, [], False
            origin = datetime(year, month, day, tzinfo=timezone.utc)
            return day, minutes_to_hours(decode_bid_candles(blob, origin, spec.price_divisor)), True

        return [one(day) for day in days]

    def _recent_minutes(self, spec: Symbol, now: datetime) -> list[Bar]:
        """Yesterday and the days just before it, plus today's ticks.

        Monday morning still needs Friday. Four calendar days covers that
        without downloading the whole month of minute files.
        """
        merged: dict[datetime, Bar] = {}
        for back in (4, 3, 2, 1):
            day = (now - timedelta(days=back)).date()
            for bar in self._minute_day(spec, day):
                merged[bar.time] = bar
        for bar in self._today_minutes(spec, now):
            merged[bar.time] = bar
        return [merged[key] for key in sorted(merged)]

    def _minute_day(self, spec: Symbol, day) -> list[Bar]:  # type: ignore[no-untyped-def]
        stamp = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        key = (spec.feed, stamp)
        cached = _minute_day_cache.get(key)
        if cached is not None:
            return cached
        url = f"{_FEED}/{spec.feed}/{day.year}/{day.month - 1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
        with httpx.Client(timeout=12, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
            blob = _get(client, url)
        if blob is None:
            return []
        if not blob:
            _minute_day_cache[key] = []
            return []
        bars = decode_bid_candles(blob, stamp, spec.price_divisor)
        _minute_day_cache[key] = bars
        return bars

    def _today_minutes(self, spec: Symbol, now: datetime) -> list[Bar]:
        minutes: list[Bar] = []
        # Include the hour that is still printing. Its file can 404 early in the hour.
        for hour_n in range(now.hour + 1):
            stamp = now.replace(hour=hour_n, minute=0, second=0, microsecond=0)
            closed = hour_n < now.hour
            got = self._tick_minutes(spec, stamp, closed)
            minutes.extend(got)
        return minutes

    def _stored_minutes(self, spec: Symbol, stamp: datetime, now_mono: float) -> list[Bar] | None:
        hit = _tick_minute_cache.get((spec.feed, stamp))
        if hit is None:
            return None
        expiry, bars = hit
        if expiry is not None and now_mono >= expiry:
            return None
        return bars

    def _tick_minutes(self, spec: Symbol, stamp: datetime, closed: bool) -> list[Bar]:
        now_mono = time.monotonic()
        stored = self._stored_minutes(spec, stamp, now_mono)
        if stored is not None:
            return stored
        url = (
            f"{_FEED}/{spec.feed}/{stamp.year}/{stamp.month - 1:02d}/"
            f"{stamp.day:02d}/{stamp.hour:02d}h_ticks.bi5"
        )
        with httpx.Client(timeout=12, headers={"User-Agent": "Mozilla/5.0"}, follow_redirects=True) as client:
            blob = _get(client, url)
        if blob is None:
            return []
        bars = decode_tick_minutes(blob, stamp, spec.price_divisor) if blob else []
        expiry = None if closed else now_mono + _CURRENT_HOUR_TTL
        _tick_minute_cache[(spec.feed, stamp)] = (expiry, bars)
        return bars


_override: MarketData | None = None


def set_market_override(market: MarketData | None) -> None:
    global _override
    _override = market


def get_market() -> MarketData:
    return _override or DeskMarket()


def clear_cache() -> None:
    _hour_cache.clear()
    _yahoo_cache.clear()
    _month_cache.clear()
    _day_cache.clear()
    _tick_cache.clear()
    _tick_minute_cache.clear()
    _minute_day_cache.clear()


def hour_ago(hours: int, now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    base = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return base - timedelta(hours=hours)
