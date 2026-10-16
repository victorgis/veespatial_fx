from datetime import datetime, timedelta, timezone

from app.strategy import (
    Bar,
    Snapshot,
    StrategyParams,
    bar_hit,
    decide,
    ema,
    levels,
    macd,
    rsi,
    stop_distance,
    structure_allows,
    structure_of,
)


def test_ema_of_a_flat_series_is_the_price():
    out = ema([5.0] * 30, 10)
    assert out[9] == 5
    assert out[20] == 5


def test_rsi_of_a_rising_series_is_overbought():
    values = [float(i) for i in range(1, 40)]
    out = rsi(values, 14)
    assert out[-1] == 100


def test_buy_requires_trend_and_rsi_band():
    params = StrategyParams()
    prev = Snapshot(1, 2, 1, 50, 1, 3)
    cur = Snapshot(2.1, 2.0, 1, 55, 1, 3)
    assert decide(prev, cur, params) == "buy"
    blocked = Snapshot(2.1, 2.0, 3, 55, 1, 1)
    assert decide(prev, blocked, params) is None
    hot = Snapshot(2.1, 2.0, 1, 90, 1, 3)
    assert decide(prev, hot, params) is None


def test_sell_mirrors_the_buy():
    prev = Snapshot(2, 1, 3, 40, 1, 1)
    cur = Snapshot(0.9, 1.0, 3, 40, 1, 0.5)
    assert decide(prev, cur) == "sell"


def test_target_is_twice_the_stop_and_on_the_correct_side():
    sl, tp = levels("buy", 100, 2, StrategyParams(), 2)
    assert sl == 97
    assert tp == 106
    sl, tp = levels("sell", 100, 2, StrategyParams(), 2)
    assert sl == 103
    assert tp == 94


def test_stop_wins_when_both_print_in_one_candle():
    assert bar_hit("buy", 9, 12, high=13, low=8) == "stopped"
    assert bar_hit("buy", 9, 12, high=13, low=10) == "target"
    assert bar_hit("sell", 12, 8, high=13, low=9) == "stopped"
    assert bar_hit("sell", 12, 8, high=11, low=7) == "target"
    assert bar_hit("buy", 9, 12, high=11, low=10) is None
    assert bar_hit("buy", 9, 0, high=13, low=10) is None
    assert bar_hit("sell", 12, 0, high=11, low=7) is None


def test_macd_of_a_rising_series_is_positive():
    # A straight line leaves the histogram near zero. A series that steepens
    # keeps the MACD line above its signal.
    values = [float(i) ** 1.2 for i in range(1, 80)]
    line, signal, hist = macd(values)
    assert line[-1] is not None and signal[-1] is not None and hist[-1] is not None
    assert line[-1] > 0
    assert hist[-1] > 0


def test_swing_structure_reads_higher_highs_and_lower_lows():
    start = datetime(2026, 3, 2, tzinfo=timezone.utc)

    def bar(i: int, lo: float, hi: float) -> Bar:
        mid = (lo + hi) / 2
        return Bar(start + timedelta(minutes=15 * i), mid, hi, lo, mid)

    up = [bar(i, 1.0, 1.1) for i in range(24)]
    up[4] = bar(4, 0.90, 1.05)
    up[8] = bar(8, 1.00, 1.30)
    up[12] = bar(12, 0.95, 1.05)
    up[16] = bar(16, 1.00, 1.40)
    assert structure_of(up).label == "HH/HL"
    assert structure_allows(structure_of(up), "buy")
    assert not structure_allows(structure_of(up), "sell")

    down = [bar(i, 1.0, 1.1) for i in range(24)]
    down[4] = bar(4, 1.00, 1.40)
    down[8] = bar(8, 0.95, 1.05)
    down[12] = bar(12, 1.00, 1.30)
    down[16] = bar(16, 0.90, 1.05)
    assert structure_of(down).label == "LH/LL"
    assert structure_allows(structure_of(down), "sell")


def test_stop_widens_a_tiny_swing_and_skips_a_huge_one():
    normal = stop_distance("buy", 1.10, 1.0990, 0.001, 0.0001)
    assert normal is not None and abs(normal - 0.0015) < 1e-9
    tight = stop_distance("buy", 1.10, 1.0999, 0.001, 0.0001)
    assert tight is not None and abs(tight - 0.0015) < 1e-9
    assert stop_distance("buy", 1.10, 1.090, 0.001, 0.0001) is None
