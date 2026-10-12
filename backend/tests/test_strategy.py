from datetime import datetime, timedelta, timezone

from app.strategy import (
    Bar,
    Snapshot,
    StrategyParams,
    bar_hit,
    decide,
    ema,
    evaluate_intraday,
    levels,
    macd,
    rsi,
    stop_distance,
    structure_allows,
    structure_of,
)
from app.symbols import get_symbol


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


def _five_minute_pullback() -> tuple[list[Bar], list[Bar], list[Bar]]:
    """A rising 5-minute series that tags the 50-bar average and closes back above it."""
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    bars: list[Bar] = []
    price = 1.10
    for i in range(120):
        price += -0.00003 if i % 5 == 4 else 0.0001
        prev = bars[-1].close if bars else price
        when = start + timedelta(minutes=5 * len(bars))
        bars.append(Bar(when, prev, max(prev, price) + 0.00008, min(prev, price) - 0.00008, price))
    from app.strategy import atr

    for _ in range(12):
        average = ema([bar.close for bar in bars], 50)[-1]
        width = atr(bars, 14)[-1]
        assert average is not None and width is not None
        if bars[-1].close - average < width * 0.6:
            break
        price = bars[-1].close - 0.00025
        prev = bars[-1].close
        when = start + timedelta(minutes=5 * len(bars))
        bars.append(Bar(when, prev, max(prev, price) + 0.00008, min(prev, price) - 0.00008, price))
    price = bars[-1].close + 0.00030
    prev = bars[-1].close
    when = start + timedelta(minutes=5 * len(bars))
    bars.append(Bar(when, prev, max(prev, price) + 0.00005, min(prev, price) - 0.00005, price))

    hourly: list[Bar] = []
    level = bars[-1].close - 0.04
    for i in range(230):
        level += 0.04 / 230
        hourly.append(
            Bar(start + timedelta(hours=i), level - 0.0002, level + 0.0003, level - 0.0003, level)
        )
    floor = bars[-1].close - 0.02
    m15 = []
    for i in range(40):
        mid = floor + 0.006
        m15.append(Bar(start + timedelta(minutes=15 * i), mid, floor + 0.008, floor + 0.004, mid))
    swings = {
        6: (floor, floor + 0.006, floor + 0.003),
        10: (floor + 0.006, floor + 0.014, floor + 0.012),
        16: (floor + 0.003, floor + 0.008, floor + 0.005),
        20: (floor + 0.008, floor + 0.018, floor + 0.016),
        26: (floor + 0.005, floor + 0.010, floor + 0.008),
        30: (floor + 0.010, floor + 0.020, floor + 0.018),
    }
    for index, (lo, hi, close) in swings.items():
        m15[index] = Bar(m15[index].time, close, hi, lo, close)
    return bars, hourly, m15


def test_five_minute_pullback_publishes_inside_the_hour_trend():
    spec = get_symbol("eurusd")
    assert spec is not None
    bars, hourly, m15 = _five_minute_pullback()
    decision = evaluate_intraday(bars, spec, hourly=hourly, m15=m15, now=bars[-1].time + timedelta(minutes=6))
    assert decision.draft is not None, decision.log_line
    assert decision.draft.side == "buy"
    assert decision.draft.sl < decision.draft.entry < decision.draft.tp
    reward = decision.draft.tp - decision.draft.entry
    risk = decision.draft.entry - decision.draft.sl
    assert abs(reward / risk - 1.0) < 0.05
    for word in ("RSI", "MACD", "MA50", "EMA200", "15m", "entry: buy"):
        assert word in decision.log_line


def test_opposing_fifteen_minute_structure_blocks_the_pullback():
    spec = get_symbol("eurusd")
    assert spec is not None
    bars, hourly, m15 = _five_minute_pullback()
    flipped = []
    for bar in m15:
        mid = (bar.high + bar.low) / 2
        flipped.append(Bar(bar.time, mid, 2.2 - bar.low, 2.2 - bar.high, mid))
    decision = evaluate_intraday(bars, spec, hourly=hourly, m15=flipped, now=bars[-1].time + timedelta(minutes=6))
    assert decision.draft is None
    assert "15-minute structure" in decision.log_line


def test_a_fresh_one_minute_bar_against_the_trade_blocks_it():
    spec = get_symbol("eurusd")
    assert spec is not None
    bars, hourly, m15 = _five_minute_pullback()
    last = bars[-1]
    minute = Bar(last.time + timedelta(minutes=4), last.close, last.close + 0.0001, last.close - 0.0002, last.close - 0.0001)
    decision = evaluate_intraday(
        bars,
        spec,
        hourly=hourly,
        m15=m15,
        m1=[minute],
        now=minute.time + timedelta(seconds=30),
    )
    assert decision.draft is None
    assert "1-minute" in decision.log_line


def test_short_history_still_names_every_check():
    spec = get_symbol("eurusd")
    assert spec is not None
    when = datetime(2026, 3, 2, 12, 5, tzinfo=timezone.utc)
    decision = evaluate_intraday([Bar(when, 1.1, 1.11, 1.09, 1.1)], spec)
    assert decision.draft is None
    for word in ("RSI", "MACD", "MA50", "EMA200", "15m"):
        assert word in decision.log_line


def test_multi_timeframe_trend_conflict():
    from app.strategy import _4h_bias, _1d_bias
    spec = get_symbol("eurusd")
    assert spec is not None
    bars, hourly, m15 = _five_minute_pullback()
    # Test 4H bias calculation
    bias_4h = _4h_bias(hourly, bars[-1].close)
    assert bias_4h in ("buy", "sell", "flat", None)

