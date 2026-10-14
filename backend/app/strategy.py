"""Signal rules.

The desk publishes a 15-minute pullback inside a higher-timeframe trend.
The 1-hour chart has to agree (price and the 50-hour average on the same
side of the 200-hour average). The 4-hour trend has to agree, or at
least not contradict. The 15-minute candle times the entry: RSI in a
pullback band and turning, MACD momentum turning with the trend, and the
close back through the 50-bar average without being extended. The stop sits
beyond the recent 15-minute swing. The target is 1:1 matching the stop distance.

`decide`, `levels`, and `evaluate` are the older hourly cross. They stay so
their tests stay, and the scan does not call them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.symbols import Symbol


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float


@dataclass(frozen=True)
class StrategyParams:
    fast: int = 20
    slow: int = 50
    trend: int = 200
    rsi_n: int = 14
    atr_n: int = 14
    sl_mult: float = 1.5
    tp_mult: float = 3.0
    buy_rsi: tuple[float, float] = (45, 75)
    sell_rsi: tuple[float, float] = (25, 55)


@dataclass(frozen=True)
class Snapshot:
    ema_fast: float
    ema_slow: float
    ema_trend: float
    rsi: float
    atr: float
    close: float


@dataclass(frozen=True)
class SignalDraft:
    side: str
    entry: float
    sl: float
    tp: float
    atr: float
    rsi: float
    candle_time: datetime


def ema(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if n <= 0 or len(values) < n:
        return out
    seed = sum(values[:n]) / n
    out[n - 1] = seed
    k = 2 / (n + 1)
    prev = seed
    for i in range(n, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(values: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(values)
    if n <= 0 or len(values) <= n:
        return out
    gains = 0.0
    losses = 0.0
    for i in range(1, n + 1):
        change = values[i] - values[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain = gains / n
    avg_loss = losses / n
    out[n] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    for i in range(n + 1, len(values)):
        change = values[i] - values[i - 1]
        avg_gain = (avg_gain * (n - 1) + max(change, 0.0)) / n
        avg_loss = (avg_loss * (n - 1) + max(-change, 0.0)) / n
        out[i] = 100.0 if avg_loss == 0 else 100 - (100 / (1 + avg_gain / avg_loss))
    return out


def atr(bars: list[Bar], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(bars)
    if n <= 0 or len(bars) <= n:
        return out
    trs: list[float] = []
    for i, bar in enumerate(bars):
        if i == 0:
            trs.append(bar.high - bar.low)
        else:
            prev = bars[i - 1].close
            trs.append(max(bar.high - bar.low, abs(bar.high - prev), abs(bar.low - prev)))
    seed = sum(trs[1 : n + 1]) / n
    out[n] = seed
    prev_atr = seed
    for i in range(n + 1, len(bars)):
        prev_atr = (prev_atr * (n - 1) + trs[i]) / n
        out[i] = prev_atr
    return out


def adx(bars: list[Bar], n: int = 14) -> list[float | None]:
    """Average Directional Index (ADX) measuring trend strength over `n` periods."""
    out: list[float | None] = [None] * len(bars)
    if n <= 0 or len(bars) <= n * 2:
        return out
    tr_l: list[float] = [0.0]
    plus_dm_l: list[float] = [0.0]
    minus_dm_l: list[float] = [0.0]
    for i in range(1, len(bars)):
        curr, prev = bars[i], bars[i - 1]
        tr = max(curr.high - curr.low, abs(curr.high - prev.close), abs(curr.low - prev.close))
        up_move = curr.high - prev.high
        down_move = prev.low - curr.low
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        tr_l.append(tr)
        plus_dm_l.append(plus_dm)
        minus_dm_l.append(minus_dm)

    smooth_tr = sum(tr_l[1 : n + 1])
    smooth_pdm = sum(plus_dm_l[1 : n + 1])
    smooth_mdm = sum(minus_dm_l[1 : n + 1])

    dx_l: list[float] = []
    for i in range(n, len(bars)):
        if i > n:
            smooth_tr = smooth_tr - (smooth_tr / n) + tr_l[i]
            smooth_pdm = smooth_pdm - (smooth_pdm / n) + plus_dm_l[i]
            smooth_mdm = smooth_mdm - (smooth_mdm / n) + minus_dm_l[i]
        p_di = 100.0 * (smooth_pdm / smooth_tr) if smooth_tr > 0 else 0.0
        m_di = 100.0 * (smooth_mdm / smooth_tr) if smooth_tr > 0 else 0.0
        denom = p_di + m_di
        dx = 100.0 * (abs(p_di - m_di) / denom) if denom > 0 else 0.0
        dx_l.append(dx)

    if len(dx_l) < n:
        return out
    adx_val = sum(dx_l[:n]) / n
    out[n * 2 - 1] = adx_val
    for j in range(n, len(dx_l)):
        adx_val = (adx_val * (n - 1) + dx_l[j]) / n
        out[n + j] = adx_val
    return out


def _swept_liquidity(bars: list[Bar], side: str, window: int = 20) -> bool:
    """Check if recent 5m price dipped below/above recent 20-bar swing low/high."""
    if len(bars) < window + 2:
        return True
    sub = bars[-(window + 2):]
    if side == "buy":
        recent_lows = [b.low for b in sub[-5:]]
        past_lowest = min(b.low for b in sub[:-5])
        return any(low < past_lowest for low in recent_lows)
    else:
        recent_highs = [b.high for b in sub[-5:]]
        past_highest = max(b.high for b in sub[:-5])
        return any(high > past_highest for high in recent_highs)


def decide(prev: Snapshot, cur: Snapshot, params: StrategyParams | None = None) -> str | None:
    params = params or StrategyParams()
    bull = prev.ema_fast <= prev.ema_slow and cur.ema_fast > cur.ema_slow
    bear = prev.ema_fast >= prev.ema_slow and cur.ema_fast < cur.ema_slow
    lo, hi = params.buy_rsi
    if bull and cur.ema_slow > cur.ema_trend and lo <= cur.rsi <= hi and cur.close > cur.ema_trend:
        return "buy"
    lo, hi = params.sell_rsi
    if bear and cur.ema_slow < cur.ema_trend and lo <= cur.rsi <= hi and cur.close < cur.ema_trend:
        return "sell"
    return None


def round_price(value: float, digits: int) -> float:
    return float(f"{value:.{digits}f}")


def levels(side: str, entry: float, atr_value: float, params: StrategyParams, digits: int) -> tuple[float, float] | None:
    if atr_value <= 0:
        return None
    sl_dist = atr_value * params.sl_mult
    tp_dist = atr_value * params.tp_mult
    if side == "buy":
        sl = round_price(entry - sl_dist, digits)
        tp = round_price(entry + tp_dist, digits)
        if sl >= entry or tp <= entry:
            return None
        return sl, tp
    sl = round_price(entry + sl_dist, digits)
    tp = round_price(entry - tp_dist, digits)
    if sl <= entry or tp >= entry:
        return None
    return sl, tp


def evaluate(bars: list[Bar], spec: Symbol, params: StrategyParams | None = None) -> SignalDraft | None:
    params = params or StrategyParams()
    need = max(params.trend, params.slow, params.fast, params.rsi_n, params.atr_n) + 2
    if len(bars) < need:
        return None
    closes = [b.close for b in bars]
    fast = ema(closes, params.fast)
    slow = ema(closes, params.slow)
    trend = ema(closes, params.trend)
    rsi_v = rsi(closes, params.rsi_n)
    atr_v = atr(bars, params.atr_n)
    i = len(bars) - 1
    if None in (fast[i], slow[i], trend[i], rsi_v[i], atr_v[i], fast[i - 1], slow[i - 1], trend[i - 1], rsi_v[i - 1], atr_v[i - 1]):
        return None
    prev = Snapshot(fast[i - 1], slow[i - 1], trend[i - 1], rsi_v[i - 1], atr_v[i - 1], closes[i - 1])  # type: ignore[arg-type]
    cur = Snapshot(fast[i], slow[i], trend[i], rsi_v[i], atr_v[i], closes[i])  # type: ignore[arg-type]
    if cur.atr <= 0 or cur.atr > cur.close * 0.15:
        return None
    side = decide(prev, cur, params)
    if side is None:
        return None
    entry = round_price(cur.close, spec.digits)
    built = levels(side, entry, cur.atr, params, spec.digits)
    if built is None:
        return None
    sl, tp = built
    return SignalDraft(side, entry, sl, tp, cur.atr, cur.rsi, bars[i].time)


def bar_hit(side: str, sl: float, tp: float, high: float, low: float) -> str | None:
    """If both the stop and the target print in one candle, the stop wins."""
    if side == "buy":
        if low <= sl:
            return "stopped"
        if high >= tp:
            return "target"
        return None
    if high >= sl:
        return "stopped"
    if low <= tp:
        return "target"
    return None


@dataclass(frozen=True)
class IntradayParams:
    rsi_n: int = 14
    atr_n: int = 14
    ma50: int = 50
    ema_hour: int = 50
    ema_trend: int = 200
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    swing_wing: int = 2
    buy_rsi: tuple[float, float] = (40, 58)
    sell_rsi: tuple[float, float] = (42, 60)
    min_stop_atr: float = 1.5
    max_stop_atr: float = 2.5
    target_r: float = 1.0


@dataclass(frozen=True)
class Structure:
    kind: str
    label: str
    last_low: float | None
    last_high: float | None
    higher_low: bool
    lower_high: bool


@dataclass(frozen=True)
class Decision:
    draft: SignalDraft | None
    log_line: str


def macd(
    values: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """MACD line, signal line, and histogram. None until each average exists."""
    fast_ema = ema(values, fast)
    slow_ema = ema(values, slow)
    line: list[float | None] = [None] * len(values)
    for i, (fast_v, slow_v) in enumerate(zip(fast_ema, slow_ema)):
        if fast_v is not None and slow_v is not None:
            line[i] = fast_v - slow_v
    first = next((i for i, value in enumerate(line) if value is not None), None)
    sig: list[float | None] = [None] * len(values)
    hist: list[float | None] = [None] * len(values)
    if first is None:
        return line, sig, hist
    seeded = ema([value for value in line[first:] if value is not None], signal)
    for offset, value in enumerate(seeded):
        idx = first + offset
        sig[idx] = value
        if value is not None and line[idx] is not None:
            hist[idx] = line[idx] - value
    return line, sig, hist


def swing_points(bars: list[Bar], wing: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Confirmed swing highs and swing lows. A point needs `wing` bars on each side."""
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    if wing < 1 or len(bars) < wing * 2 + 1:
        return highs, lows
    for i in range(wing, len(bars) - wing):
        others_h = [bars[j].high for j in range(i - wing, i + wing + 1) if j != i]
        others_l = [bars[j].low for j in range(i - wing, i + wing + 1) if j != i]
        if bars[i].high > max(others_h):
            highs.append((i, bars[i].high))
        if bars[i].low < min(others_l):
            lows.append((i, bars[i].low))
    return highs, lows


def structure_of(bars: list[Bar], wing: int = 2) -> Structure:
    highs, lows = swing_points(bars, wing)
    last_high = highs[-1][1] if highs else None
    prev_high = highs[-2][1] if len(highs) >= 2 else None
    last_low = lows[-1][1] if lows else None
    prev_low = lows[-2][1] if len(lows) >= 2 else None
    higher_high = prev_high is not None and last_high is not None and last_high > prev_high
    lower_high = prev_high is not None and last_high is not None and last_high < prev_high
    higher_low = prev_low is not None and last_low is not None and last_low > prev_low
    lower_low = prev_low is not None and last_low is not None and last_low < prev_low
    if higher_high and higher_low:
        return Structure("up", "HH/HL", last_low, last_high, True, False)
    if lower_high and lower_low:
        return Structure("down", "LH/LL", last_low, last_high, False, True)
    if len(highs) < 2 or len(lows) < 2:
        return Structure("unclear", "unclear", last_low, last_high, higher_low, lower_high)
    return Structure("mixed", "mixed", last_low, last_high, higher_low, lower_high)


def structure_allows(structure: Structure, side: str) -> bool:
    if side == "buy":
        return structure.kind == "up" or (structure.kind == "mixed" and structure.higher_low)
    if side == "sell":
        return structure.kind == "down" or (structure.kind == "mixed" and structure.lower_high)
    return False


def stop_distance(
    side: str,
    entry: float,
    swing: float,
    atr_value: float,
    pip: float,
    params: IntradayParams | None = None,
    spread_pips: float = 0.0,
) -> float | None:
    """Distance from entry to a stop beyond the swing.

    A stop tighter than 1.5× ATR is widened to that floor so the spread does
    not take it immediately. A swing farther than 2.5× ATR is skipped.
    """
    params = params or IntradayParams()
    if atr_value <= 0:
        return None
    spread_buf = max(spread_pips * pip, pip * 3.0)
    buffer = max(spread_buf, atr_value * 0.50)
    if side == "buy":
        distance = entry - (swing - buffer)
    else:
        distance = (swing + buffer) - entry
    if distance <= 0:
        return None
    if distance < atr_value * params.min_stop_atr:
        return atr_value * params.min_stop_atr
    if distance > atr_value * params.max_stop_atr:
        return None
    return distance


def _intraday_params(params: StrategyParams | IntradayParams | None) -> IntradayParams:
    if isinstance(params, IntradayParams):
        return params
    base = IntradayParams()
    if isinstance(params, StrategyParams):
        return IntradayParams(rsi_n=params.rsi_n, atr_n=params.atr_n)
    return base


def _stamp(when: datetime | None) -> str:
    if when is None:
        return "--:--"
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%H:%M")


def _check_line(
    display: str,
    when: datetime | None,
    trend: str,
    rsi_txt: str,
    ma50_txt: str,
    ema200_txt: str,
    macd_txt: str,
    structure: str,
    verdict: str,
) -> str:
    return (
        f"{display} 15m {_stamp(when)} UTC | {trend} | RSI {rsi_txt} | MA50 {ma50_txt} | "
        f"EMA200 {ema200_txt} | MACD {macd_txt} | 15m {structure} | {verdict}"
    )


def _rsi_txt(cur: float | None, prev: float | None) -> str:
    if cur is None:
        return "—"
    if prev is None or abs(cur - prev) <= 0.05:
        direction = "flat"
    elif cur > prev:
        direction = "rising"
    else:
        direction = "falling"
    return f"{cur:.0f} {direction}"


def _macd_txt(hist: float | None, prev: float | None, line: float | None, signal: float | None) -> str:
    if hist is None or prev is None:
        return "—"
    if hist > prev:
        direction = "rising"
    elif hist < prev:
        direction = "falling"
    else:
        direction = "flat"
    if line is None or signal is None:
        return direction
    if line > signal:
        place = "above signal"
    elif line < signal:
        place = "below signal"
    else:
        place = "on signal"
    return f"{direction}, {place}"


def calculate_supply_demand_tp(
    side: str,
    entry: float,
    distance: float,
    m15: list[Bar] | None,
    cur_atr: float,
    pip: float,
    default_r: float = 1.5,
) -> float:
    """Locates opposing supply (swing high) or demand (swing low) zones on the 15m structure.

    If an opposing structural wall exists between 1.2R and 2.0R, caps Take Profit
    right before that wall (minus a spread/ATR buffer) so the trade exits cleanly.
    Otherwise defaults to default_r (1.5R).
    """
    if not m15 or len(m15) < 4 or distance <= 0:
        return default_r

    recent = m15[-40:]
    zone_buffer = max(pip * 2.0, cur_atr * 0.1)

    if side == "buy":
        highs = [b.high for b in recent if b.high > entry + distance * 1.0]
        if highs:
            supply_wall = min(highs) - zone_buffer
            if supply_wall > entry:
                r_to_wall = (supply_wall - entry) / distance
                if 1.2 <= r_to_wall <= 2.0:
                    return min(r_to_wall, 1.8)
    else:
        lows = [b.low for b in recent if b.low < entry - distance * 1.0]
        if lows:
            demand_wall = max(lows) + zone_buffer
            if demand_wall < entry:
                r_to_wall = (entry - demand_wall) / distance
                if 1.2 <= r_to_wall <= 2.0:
                    return min(r_to_wall, 1.8)

    return default_r


def _levels_r(side: str, entry: float, distance: float, digits: int, target_r: float) -> tuple[float, float] | None:
    if distance <= 0:
        return None
    if side == "buy":
        sl = round_price(entry - distance, digits)
        tp = round_price(entry + distance * target_r, digits)
        if sl >= entry or tp <= entry:
            return None
        return sl, tp
    sl = round_price(entry + distance, digits)
    tp = round_price(entry - distance * target_r, digits)
    if sl <= entry or tp >= entry:
        return None
    return sl, tp


def _recent_swing(bars: list[Bar], side: str, wing: int) -> float:
    """Extreme of this candle and the two before it.

    A scalp stop belongs beyond that immediate swing. The whole pullback leg
    is often several ranges away, and hiding the stop inside it is worse than
    skipping a bar whose own range is already too wide.
    """
    del wing
    last = len(bars) - 1
    window = bars[max(0, last - 2) : last + 1]
    if side == "buy":
        return min(bar.low for bar in window)
    return max(bar.high for bar in window)


def _minute_confirms(side: str, m1: list[Bar] | None, now: datetime) -> bool:
    """A fresh 1-minute bar has to close with the trade. A missing or old one does not block."""
    if not m1:
        return True
    last = m1[-1]
    when = last.time if last.time.tzinfo else last.time.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    if now.astimezone(timezone.utc) - when.astimezone(timezone.utc) > timedelta(minutes=3):
        return True
    if side == "buy":
        return last.close > last.open
    return last.close < last.open


def _resample_bars(bars: list[Bar], minutes: int) -> list[Bar]:
    if minutes <= 0 or not bars:
        return []
    buckets: dict[datetime, list[Bar]] = {}
    for bar in bars:
        t = bar.time if bar.time.tzinfo else bar.time.replace(tzinfo=timezone.utc)
        if minutes == 240:
            h_bucket = t.hour - (t.hour % 4)
            bucket = t.replace(hour=h_bucket, minute=0, second=0, microsecond=0)
        elif minutes >= 1440:
            bucket = t.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            bucket = t - timedelta(minutes=t.minute % minutes)
        buckets.setdefault(bucket, []).append(bar)
    out: list[Bar] = []
    for bucket in sorted(buckets):
        group = buckets[bucket]
        out.append(
            Bar(
                bucket,
                group[0].open,
                max(b.high for b in group),
                min(b.low for b in group),
                group[-1].close,
            )
        )
    return out


def _4h_bias(hourly: list[Bar] | None, price: float) -> str | None:
    if not hourly:
        return None
    h4 = _resample_bars(hourly, 240)
    if len(h4) < 15:
        return None
    closes = [b.close for b in h4]
    fast = ema(closes, 12)
    slow = ema(closes, 26)
    i = len(closes) - 1
    if fast[i] is None or slow[i] is None:
        return None
    f_val, s_val = fast[i], slow[i]
    assert f_val is not None and s_val is not None
    if price > s_val and f_val > s_val:
        return "buy"
    if price < s_val and f_val < s_val:
        return "sell"
    return "flat"


def _1d_bias(hourly: list[Bar] | None, price: float) -> str | None:
    if not hourly:
        return None
    d1 = _resample_bars(hourly, 1440)
    if len(d1) < 7:
        return None
    closes = [b.close for b in d1]
    fast = ema(closes, 5)
    slow = ema(closes, 15)
    i = len(closes) - 1
    if fast[i] is None or slow[i] is None:
        return None
    f_val, s_val = fast[i], slow[i]
    assert f_val is not None and s_val is not None
    if price > s_val and f_val >= s_val:
        return "buy"
    if price < s_val and f_val <= s_val:
        return "sell"
    return "flat"


def _hourly_bias(hourly: list[Bar] | None, price: float, params: IntradayParams) -> tuple[str | None, str]:
    """Return 'buy', 'sell', or None, plus the EMA200 column text.

    'short' in the text means the hourly history itself is too short to judge.
    """
    if not hourly or len(hourly) < params.ema_trend:
        return None, "not ready"
    closes = [bar.close for bar in hourly]
    mid = ema(closes, params.ema_hour)
    trend = ema(closes, params.ema_trend)
    i = len(closes) - 1
    if mid[i] is None or trend[i] is None:
        return None, "not ready"
    ema50 = mid[i]
    ema200 = trend[i]
    assert ema50 is not None and ema200 is not None
    if price > ema200 and ema50 > ema200:
        return "buy", "close above, EMA50 above"
    if price < ema200 and ema50 < ema200:
        return "sell", "close below, EMA50 below"
    return None, "flat"


def evaluate_intraday(
    bars: list[Bar],
    spec: Symbol,
    params: StrategyParams | IntradayParams | None = None,
    hourly: list[Bar] | None = None,
    m15: list[Bar] | None = None,
    m1: list[Bar] | None = None,
    now: datetime | None = None,
) -> Decision:
    """Judge the last closed 15-minute candle. Always returns a log line."""
    tuned = _intraday_params(params)
    now = now or datetime.now(timezone.utc)
    when = bars[-1].time if bars else None
    need = max(tuned.ma50, tuned.macd_slow + tuned.macd_signal, tuned.rsi_n, tuned.atr_n) + 2
    if len(bars) < need:
        line = _check_line(
            spec.display, when, "1h waiting", "—", "—", "—", "—", "—",
            f"no entry: need {need} closed 15-minute candles (have {len(bars)})",
        )
        return Decision(None, line)

    closes = [bar.close for bar in bars]
    ma50 = ema(closes, tuned.ma50)
    rsi_v = rsi(closes, tuned.rsi_n)
    atr_v = atr(bars, tuned.atr_n)
    macd_line, macd_sig, macd_hist = macd(closes, tuned.macd_fast, tuned.macd_slow, tuned.macd_signal)
    i = len(bars) - 1
    cur_ma = ma50[i]
    prev_ma = ma50[i - 1]
    cur_rsi = rsi_v[i]
    prev_rsi = rsi_v[i - 1]
    cur_atr = atr_v[i]
    cur_hist = macd_hist[i]
    prev_hist = macd_hist[i - 1]
    cur_macd = macd_line[i]
    cur_sig = macd_sig[i]
    rsi_txt = _rsi_txt(cur_rsi, prev_rsi)
    macd_txt = _macd_txt(cur_hist, prev_hist, cur_macd, cur_sig)
    if cur_ma is None:
        ma_txt = "—"
    elif closes[i] > cur_ma:
        ma_txt = "close above"
    elif closes[i] < cur_ma:
        ma_txt = "close below"
    else:
        ma_txt = "close on"

    if None in (cur_ma, prev_ma, cur_rsi, prev_rsi, cur_atr, cur_hist, prev_hist, cur_macd, cur_sig):
        line = _check_line(
            spec.display, when, "1h waiting", rsi_txt, ma_txt, "—", macd_txt, "—",
            "no entry: 15-minute averages are not ready",
        )
        return Decision(None, line)
    assert cur_ma is not None and cur_rsi is not None and prev_rsi is not None
    assert cur_atr is not None and cur_hist is not None and prev_hist is not None
    assert cur_macd is not None and cur_sig is not None

    if cur_atr <= 0 or cur_atr > closes[i] * 0.15:
        line = _check_line(
            spec.display, when, "1h waiting", rsi_txt, ma_txt, "—", macd_txt, "—",
            "no entry: the 15-minute range is not usable",
        )
        return Decision(None, line)

    bias_1h, ema_txt = _hourly_bias(hourly, closes[i], tuned)
    b4h = _4h_bias(hourly, closes[i])
    b1d = _1d_bias(hourly, closes[i])

    bias = bias_1h
    trend_conflict: str | None = None

    if bias_1h is not None:
        if b4h is not None and b4h != "flat" and b4h != bias_1h:
            bias = None
            trend_conflict = f"no entry: 4-hour trend ({b4h}) conflicts with 1-hour trend ({bias_1h})"
        elif b1d is not None and b1d != "flat" and b1d != bias_1h:
            bias = None
            trend_conflict = f"no entry: 1-day trend ({b1d}) conflicts with 1-hour trend ({bias_1h})"

    if not hourly or len(hourly) < tuned.ema_trend:
        trend_txt = "1h not ready"
    elif bias == "buy":
        trend_txt = "1h/4h uptrend" if b4h == "buy" else "1h uptrend"
    elif bias == "sell":
        trend_txt = "1h/4h downtrend" if b4h == "sell" else "1h downtrend"
    else:
        trend_txt = "1h flat"

    structure_source = m15 if (m15 and len(m15) >= 10) else bars
    structure = structure_of(structure_source, tuned.swing_wing)
    struct_txt = structure.label

    def finish(verdict: str, draft: SignalDraft | None = None) -> Decision:
        return Decision(
            draft,
            _check_line(spec.display, when, trend_txt, rsi_txt, ma_txt, ema_txt, macd_txt, struct_txt, verdict),
        )

    if trend_txt == "1h not ready":
        return finish("no entry: 1-hour trend is not ready")
    if trend_conflict is not None:
        return finish(trend_conflict)
    if bias is None:
        return finish("no entry: 1-hour trend is flat")
    side = bias
    if not structure_allows(structure, side):
        return finish(f"no entry: 15-minute structure is {structure.label}")

    # 15m Liquidity Sweep Filter
    # if not _swept_liquidity(bars, side):
    #     return finish("no entry: price has not swept 20-bar liquidity")

    lo, hi = tuned.buy_rsi if side == "buy" else tuned.sell_rsi
    if not (lo <= cur_rsi <= hi):
        return finish(f"no entry: RSI {cur_rsi:.0f} is outside {lo:.0f}-{hi:.0f}")
    if side == "buy" and cur_rsi <= prev_rsi:
        return finish("no entry: RSI is not rising")
    if side == "sell" and cur_rsi >= prev_rsi:
        return finish("no entry: RSI is not falling")

    # The turn often prints while the line is still the other side of the signal.
    # What matters is the histogram turning with the trend. The log still names
    # whether the line is above or below the signal.
    hist_with = (cur_hist > prev_hist) if side == "buy" else (cur_hist < prev_hist)
    if not hist_with:
        return finish("no entry: MACD momentum is not with the trend")

    touch = max(spec.pip, cur_atr * 0.15)
    prev_close = closes[i - 1]
    bar = bars[i]
    if side == "buy":
        reclaimed = bar.close > cur_ma and (bar.low <= cur_ma + touch or prev_close <= cur_ma)
    else:
        reclaimed = bar.close < cur_ma and (bar.high >= cur_ma - touch or prev_close >= cur_ma)
    if not reclaimed:
        return finish("no entry: price has not closed back through MA50")
    if abs(bar.close - cur_ma) > cur_atr * 1.25:
        return finish("no entry: price is extended beyond MA50")

    if side == "buy":
        if structure.last_low is None or bar.close <= structure.last_low:
            return finish("no entry: demand has not held")
    else:
        if structure.last_high is None or bar.close >= structure.last_high:
            return finish("no entry: supply has not held")
    swing = _recent_swing(bars, side, tuned.swing_wing)

    if not _minute_confirms(side, m1, now):
        return finish("no entry: the 1-minute candle does not confirm")

    entry = round_price(bar.close, spec.digits)
    distance = stop_distance(side, entry, swing, cur_atr, spec.pip, tuned)
    if distance is None:
        raw = entry - swing if side == "buy" else swing - entry
        if raw > cur_atr * tuned.max_stop_atr:
            return finish("no entry: the stop would be wider than 2 times the 15-minute range")
        return finish("no entry: the swing does not give a stop")
    target_r = tuned.target_r
    built = _levels_r(side, entry, distance, spec.digits, target_r)
    if built is None:
        return finish("no entry: the stop rounded onto the entry")
    sl, tp = built
    draft = SignalDraft(side, entry, sl, tp, cur_atr, cur_rsi, bar.time)
    return finish(f"entry: {side}, stop beyond the swing, target {target_r:g} times the stop (1:1)", draft)
