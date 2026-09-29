"""Hourly trend-cross strategy.

A buy is taken on the last *closed* hourly candle when:
- the fast average crosses above the slow average on that candle,
- the slow average is above the long average,
- RSI sits in the middle of its range (the cross is not an exhausted spike).

The sell rules mirror that. The stop is 1.5× ATR. The target is twice the
stop distance (3× ATR). Decisions use closed candles only.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

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
