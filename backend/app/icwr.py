"""Intraday ICWR rules.

The active wave is the nearest completed 5-minute swing of at least 40 pips.
Fibonacci levels are drawn from its low (0) to its high (1). A signal can
print only after a later candle has closed inside the retracement channel
(0.382 to 0.618). The signal candle itself has to sit entirely beyond a
confirmation level:

- wholly above 0.750 is bullish (buy)
- wholly below 0.250 is bearish (sell)

A new trade also needs the daily 14-period RSI on the same side of 50.
The stop is 50 pips. There is no fixed target. The trade is closed by the
opposite signal or by that stop.

Forex uses the pair's pip. Other markets have no pip in these rules, so one
pip there is 0.01% of price (40 pips is 0.40% of price).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.strategy import Bar, SignalDraft, rsi, round_price
from app.symbols import Symbol

WAVE_PIPS = 40.0
STOP_PIPS = 50.0
PIVOT_WING = 2
RSI_PERIOD = 14


@dataclass(frozen=True)
class Wave:
    direction: str
    start: int
    end: int
    low: float
    high: float

    @property
    def height(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class Fibs:
    lower_confirm: float
    lower_retrace: float
    upper_retrace: float
    upper_confirm: float


@dataclass(frozen=True)
class Decision:
    draft: SignalDraft | None
    log_line: str
    signal_side: str | None = None


@dataclass(frozen=True)
class _Pivot:
    index: int
    kind: str
    price: float


class _Range:
    """Constant-time high and low over a bar range."""

    def __init__(self, bars: list[Bar]) -> None:
        n = len(bars)
        self.max_t: list[list[float]] = [[bar.high for bar in bars]]
        self.min_t: list[list[float]] = [[bar.low for bar in bars]]
        span = 1
        while span * 2 <= n:
            prev_max = self.max_t[-1]
            prev_min = self.min_t[-1]
            width = n - span * 2 + 1
            self.max_t.append([max(prev_max[i], prev_max[i + span]) for i in range(width)])
            self.min_t.append([min(prev_min[i], prev_min[i + span]) for i in range(width)])
            span *= 2

    def max_high(self, start: int, end: int) -> float:
        return self._pick(self.max_t, start, end, max)

    def min_low(self, start: int, end: int) -> float:
        return self._pick(self.min_t, start, end, min)

    @staticmethod
    def _pick(table: list[list[float]], start: int, end: int, choose) -> float:  # type: ignore[no-untyped-def]
        length = end - start + 1
        k = length.bit_length() - 1
        span = 1 << k
        return choose(table[k][start], table[k][end - span + 1])


def icwr_pip(spec: Symbol, price: float) -> float:
    """Price distance of one ICWR pip for this market."""
    if spec.group == "currency":
        return spec.pip
    if price <= 0:
        return spec.pip
    return price * 0.0001


def fib_levels(wave: Wave) -> Fibs:
    span = wave.height
    low = wave.low
    return Fibs(
        lower_confirm=low + 0.250 * span,
        lower_retrace=low + 0.382 * span,
        upper_retrace=low + 0.618 * span,
        upper_confirm=low + 0.750 * span,
    )


def rsi_confirms(side: str, value: float) -> bool:
    if side == "buy":
        return value > 50.0
    if side == "sell":
        return value < 50.0
    return False


def _utc(when: datetime) -> datetime:
    if when.tzinfo is None:
        return when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc)


def _day(when: datetime) -> datetime:
    when = _utc(when)
    return when.replace(hour=0, minute=0, second=0, microsecond=0)


def daily_rsi(hourly: list[Bar] | None, last: Bar, n: int = RSI_PERIOD) -> float | None:
    """14-period RSI on the daily closes, including the day that is still forming."""
    if not hourly:
        return None
    by_day: dict[datetime, float] = {}
    for bar in hourly:
        by_day[_day(bar.time)] = bar.close
    if not by_day:
        return None
    days = sorted(by_day)
    closes = [by_day[day] for day in days]
    last_day = _day(last.time)
    if days[-1] == last_day:
        closes[-1] = last.close
    elif last_day > days[-1]:
        closes.append(last.close)
    values = rsi(closes, n)
    if not values or values[-1] is None:
        return None
    return values[-1]


def _raw_pivots(bars: list[Bar], wing: int) -> list[_Pivot]:
    found: list[_Pivot] = []
    last = len(bars) - wing - 1
    for i in range(wing, last + 1):
        left = range(i - wing, i)
        right = range(i + 1, i + wing + 1)
        is_high = bars[i].high > max(bars[j].high for j in left) and bars[i].high > max(bars[j].high for j in right)
        is_low = bars[i].low < min(bars[j].low for j in left) and bars[i].low < min(bars[j].low for j in right)
        if is_high and is_low:
            mid = (bars[i].high + bars[i].low) / 2
            is_high = bars[i].close >= mid
            is_low = not is_high
        if is_high:
            found.append(_Pivot(i, "high", bars[i].high))
        elif is_low:
            found.append(_Pivot(i, "low", bars[i].low))
    return found


def _alternating(raw: list[_Pivot]) -> list[_Pivot]:
    out: list[_Pivot] = []
    for pivot in raw:
        if not out or out[-1].kind != pivot.kind:
            out.append(pivot)
            continue
        prev = out[-1]
        if pivot.kind == "high" and pivot.price >= prev.price:
            out[-1] = pivot
        elif pivot.kind == "low" and pivot.price <= prev.price:
            out[-1] = pivot
    return out


def active_wave(bars: list[Bar], threshold: float, wing: int = PIVOT_WING) -> Wave | None:
    """Nearest completed swing whose high-to-low height is at least `threshold`.

    Swings are ordered by the most recent end, and then by the most recent
    start. A nearer swing that is still under 40 pips is skipped, which is
    the chapter 3 rule for choosing the active wave.
    """
    if threshold <= 0 or len(bars) < wing * 2 + 1:
        return None
    pivots = _alternating(_raw_pivots(bars, wing))
    if len(pivots) < 2:
        return None
    span = _Range(bars)
    tol = max(threshold * 1e-9, 1e-10)
    for end_at in range(len(pivots) - 1, 0, -1):
        end = pivots[end_at]
        for start_at in range(end_at - 1, -1, -1):
            start = pivots[start_at]
            if start.kind == end.kind or start.index >= end.index:
                continue
            hi = span.max_high(start.index, end.index)
            lo = span.min_low(start.index, end.index)
            height = hi - lo
            if height + tol < threshold:
                continue
            if end.kind == "low" and start.kind == "high":
                if abs(start.price - hi) > tol or abs(end.price - lo) > tol:
                    continue
                return Wave("down", start.index, end.index, lo, hi)
            if end.kind == "high" and start.kind == "low":
                if abs(start.price - lo) > tol or abs(end.price - hi) > tol:
                    continue
                return Wave("up", start.index, end.index, lo, hi)
    return None


def _channel_entered(bars: list[Bar], wave: Wave, fibs: Fibs) -> bool:
    """A close inside 0.382–0.618 after the wave has ended."""
    for bar in bars[wave.end + 1 : -1]:
        if fibs.lower_retrace <= bar.close <= fibs.upper_retrace:
            return True
    return False


def breakout_side(bars: list[Bar], wave: Wave, fibs: Fibs) -> str | None:
    """Bullish or bearish ICWR signal on the last closed candle, if one is there."""
    if not bars or wave.end >= len(bars) - 1:
        return None
    if not _channel_entered(bars, wave, fibs):
        return None
    last = bars[-1]
    if last.low > fibs.upper_confirm:
        return "buy"
    if last.high < fibs.lower_confirm:
        return "sell"
    return None


def _stamp(when: datetime | None) -> str:
    if when is None:
        return "--:--"
    return _utc(when).strftime("%H:%M")


def _line(spec: Symbol, when: datetime | None, body: str) -> str:
    return f"{spec.display} 5m {_stamp(when)} UTC | {body}"


def _wave_text(wave: Wave, unit: float) -> str:
    pips = wave.height / unit if unit else 0.0
    return f"wave {wave.direction} {pips:.0f} pips"


def evaluate(
    bars: list[Bar],
    spec: Symbol,
    params: object | None = None,
    hourly: list[Bar] | None = None,
    m15: list[Bar] | None = None,
    m1: list[Bar] | None = None,
    now: datetime | None = None,
) -> Decision:
    """Judge the last closed 5-minute candle. Always returns a log line.

    `signal_side` is the ICWR signal on that candle even when the daily RSI
    blocks a new trade. The scan uses it to close an open position.
    """
    del params, m15, m1, now
    when = bars[-1].time if bars else None
    if len(bars) < PIVOT_WING * 2 + 2:
        return Decision(None, _line(spec, when, f"no entry: need more closed 5-minute candles (have {len(bars)})"))
    unit = icwr_pip(spec, bars[-1].close)
    if unit <= 0:
        return Decision(None, _line(spec, when, "no entry: the pip size is not usable"))
    wave = active_wave(bars, WAVE_PIPS * unit)
    if wave is None:
        return Decision(None, _line(spec, when, "no entry: no active wave of at least 40 pips"))
    fibs = fib_levels(wave)
    side = breakout_side(bars, wave, fibs)
    rsi_value = daily_rsi(hourly, bars[-1])
    described = _wave_text(wave, unit)
    rsi_txt = "daily RSI not ready" if rsi_value is None else f"daily RSI {rsi_value:.0f}"
    if side is None:
        if wave.end >= len(bars) - 1:
            why = "price has not left the active wave"
        elif not _channel_entered(bars, wave, fibs):
            why = "retracement channel has not been entered"
        else:
            why = "the candle is not wholly beyond a confirmation level"
        return Decision(None, _line(spec, when, f"{described} | {rsi_txt} | {why}"))
    if rsi_value is None:
        return Decision(
            None,
            _line(spec, when, f"{described} | {side} ICWR signal | daily RSI is not ready, so no new trade"),
            side,
        )
    if not rsi_confirms(side, rsi_value):
        need = "above 50" if side == "buy" else "below 50"
        return Decision(
            None,
            _line(spec, when, f"{described} | {side} ICWR signal | daily RSI {rsi_value:.0f} is not {need}"),
            side,
        )
    entry = round_price(bars[-1].close, spec.digits)
    distance = STOP_PIPS * unit
    if side == "buy":
        sl = round_price(entry - distance, spec.digits)
        if sl >= entry:
            return Decision(None, _line(spec, when, f"{described} | stop rounded onto the entry"), side)
    else:
        sl = round_price(entry + distance, spec.digits)
        if sl <= entry:
            return Decision(None, _line(spec, when, f"{described} | stop rounded onto the entry"), side)
    draft = SignalDraft(side, entry, sl, 0.0, wave.height, rsi_value, bars[-1].time)
    return Decision(
        draft,
        _line(spec, when, f"{described} | {rsi_txt} | entry: {side}, stop 50 pips, exit on the opposite signal"),
        side,
    )
