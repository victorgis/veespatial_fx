"""The intraday ICWR rules: active wave, Fibonacci confirmation, daily RSI, 50-pip stop."""

from datetime import datetime, timedelta, timezone

from app.icwr import Wave, active_wave, evaluate, fib_levels, icwr_pip, rsi_confirms
from app.strategy import Bar
from app.symbols import get_symbol


def _bars(start: datetime, rows: list[tuple[float, float, float]]) -> list[Bar]:
    out: list[Bar] = []
    for i, (high, low, close) in enumerate(rows):
        open_ = rows[i - 1][2] if i else close
        out.append(Bar(start + timedelta(minutes=5 * i), open_, high, low, close))
    return out


def _days(start: datetime, closes: list[float]) -> list[Bar]:
    return [
        Bar(start + timedelta(days=i), close, close, close, close)
        for i, close in enumerate(closes)
    ]


def _bullish_rows() -> list[tuple[float, float, float]]:
    """Down wave of 68 pips, then a channel close, then a whole candle above 0.750.

    The wave runs from 1.3100 to 1.3032. The 0.750 level is 1.3083, and the
    channel is about 1.3058 to 1.3074. The breakout is the last bar, so it is
    not yet a new 40-pip wave.
    """
    rows: list[tuple[float, float, float]] = []
    # Quiet lead-in, then the swing high at index 6.
    lead = [1.3040, 1.3044, 1.3048, 1.3052, 1.3060, 1.3070, 1.3092]
    for close in lead:
        rows.append((close + 0.0004, close - 0.0004, close))
    rows[6] = (1.3100, 1.3086, 1.3092)
    # Descend to the swing low at index 16, with a small bounce that is under 40 pips.
    descent = [1.3084, 1.3076, 1.3068, 1.3062, 1.3056, 1.3058, 1.3052, 1.3046, 1.3040, 1.3035]
    for close in descent:
        rows.append((close + 0.0003, close - 0.0003, close))
    rows[12] = (1.3064, 1.3054, 1.3058)  # 28 pips off the later low, so it is not the active wave
    rows[16] = (1.3040, 1.3032, 1.3035)
    # Confirm the low, then close inside the retracement channel.
    rows.append((1.3044, 1.3038, 1.3041))
    rows.append((1.3048, 1.3042, 1.3045))
    rows.append((1.3068, 1.3060, 1.3065))
    rows.append((1.3066, 1.3058, 1.3062))
    # Whole candle above 0.750 (1.3083).
    rows.append((1.3094, 1.3086, 1.3090))
    return rows


def _bearish_rows() -> list[tuple[float, float, float]]:
    """Up wave of 80 pips, channel close, then a whole candle below 0.250."""
    rows: list[tuple[float, float, float]] = []
    lead = [1.3080, 1.3074, 1.3068, 1.3060, 1.3048, 1.3030, 1.3006]
    for close in lead:
        rows.append((close + 0.0004, close - 0.0004, close))
    rows[6] = (1.3010, 1.3000, 1.3006)
    ascent = [1.3014, 1.3024, 1.3034, 1.3042, 1.3050, 1.3046, 1.3056, 1.3064, 1.3072, 1.3076]
    for close in ascent:
        rows.append((close + 0.0003, close - 0.0003, close))
    rows[16] = (1.3080, 1.3072, 1.3076)
    rows.append((1.3074, 1.3066, 1.3070))
    rows.append((1.3068, 1.3060, 1.3064))
    rows.append((1.3048, 1.3042, 1.3045))
    rows.append((1.3049, 1.3043, 1.3046))
    rows.append((1.3015, 1.3008, 1.3010))
    return rows


def _rising_daily() -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [1.20 + i * 0.003 for i in range(40)]
    return _days(start, closes)


def _falling_daily() -> list[Bar]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    closes = [1.40 - i * 0.002 for i in range(40)]
    return _days(start, closes)


def test_fibonacci_levels_match_the_worked_example():
    # Low 1.3257, high 1.3317, height 60 pips. The book prints 0.250 as 1.3272.
    fibs = fib_levels(Wave("up", 0, 1, 1.3257, 1.3317))
    assert fibs.lower_confirm == pytest_approx(1.3272)
    assert fibs.upper_confirm == pytest_approx(1.3302)
    assert fibs.lower_retrace == pytest_approx(1.3257 + 0.382 * 0.006)
    assert fibs.upper_retrace == pytest_approx(1.3257 + 0.618 * 0.006)


def pytest_approx(value: float):
    from pytest import approx

    return approx(value, abs=1e-9)


def test_the_nearest_swing_under_40_pips_is_not_the_active_wave():
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    bars = _bars(start, _bullish_rows())
    wave = active_wave(bars, 0.0040)
    assert wave is not None
    assert wave.direction == "down"
    assert wave.high == pytest_approx(1.3100)
    assert wave.low == pytest_approx(1.3032)
    assert wave.height == pytest_approx(0.0068)


def test_downward_corrective_wave_buys_when_the_daily_rsi_is_bullish():
    spec = get_symbol("eurusd")
    assert spec is not None
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    bars = _bars(start, _bullish_rows())
    decision = evaluate(bars, spec, hourly=_rising_daily())
    assert decision.draft is not None, decision.log_line
    assert decision.draft.side == "buy"
    assert decision.signal_side == "buy"
    assert decision.draft.tp == 0
    assert decision.draft.entry - decision.draft.sl == pytest_approx(0.0050)
    assert decision.draft.entry == pytest_approx(1.3090)
    assert "entry: buy" in decision.log_line
    assert "50 pips" in decision.log_line


def test_daily_rsi_at_or_below_50_blocks_the_buy_but_keeps_the_signal():
    spec = get_symbol("eurusd")
    assert spec is not None
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    decision = evaluate(_bars(start, _bullish_rows()), spec, hourly=_falling_daily())
    assert decision.draft is None
    assert decision.signal_side == "buy"
    assert "not above 50" in decision.log_line
    assert rsi_confirms("buy", 50) is False
    assert rsi_confirms("sell", 50) is False
    assert rsi_confirms("buy", 50.1) is True
    assert rsi_confirms("sell", 49.9) is True


def test_a_breakout_without_the_retracement_channel_is_not_a_signal():
    spec = get_symbol("eurusd")
    assert spec is not None
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    rows = _bullish_rows()
    # The two bars that confirm the low, and the bar before the breakout, stay near the low.
    rows[-4] = (1.3044, 1.3038, 1.3041)
    rows[-3] = (1.3046, 1.3040, 1.3043)
    rows[-2] = (1.3048, 1.3042, 1.3045)
    decision = evaluate(_bars(start, rows), spec, hourly=_rising_daily())
    assert decision.draft is None
    assert decision.signal_side is None
    assert "retracement channel" in decision.log_line


def test_a_wick_back_through_the_confirmation_level_is_not_a_signal():
    spec = get_symbol("eurusd")
    assert spec is not None
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    rows = _bullish_rows()
    rows[-1] = (1.3094, 1.3080, 1.3090)  # low is still under 0.750 at 1.3083
    decision = evaluate(_bars(start, rows), spec, hourly=_rising_daily())
    assert decision.draft is None
    assert decision.signal_side is None
    assert "not wholly beyond" in decision.log_line


def test_upward_corrective_wave_sells_when_the_daily_rsi_is_bearish():
    spec = get_symbol("eurusd")
    assert spec is not None
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    decision = evaluate(_bars(start, _bearish_rows()), spec, hourly=_falling_daily())
    assert decision.draft is not None, decision.log_line
    assert decision.draft.side == "sell"
    assert decision.draft.tp == 0
    assert decision.draft.sl - decision.draft.entry == pytest_approx(0.0050)
    assert decision.draft.entry == pytest_approx(1.3010)


def test_yen_uses_a_pip_of_one_hundredth_so_the_stop_is_half_a_yen():
    spec = get_symbol("usdjpy")
    assert spec is not None
    assert icwr_pip(spec, 150.0) == 0.01
    start = datetime(2026, 3, 2, 8, tzinfo=timezone.utc)
    # 60-pip up wave from 150.00 to 150.60, channel, then a whole candle below 0.250.
    rows: list[tuple[float, float, float]] = []
    for close in (150.40, 150.30, 150.20, 150.12, 150.08, 150.04, 150.02):
        rows.append((close + 0.02, close - 0.02, close))
    rows[6] = (150.08, 150.00, 150.02)
    for close in (150.10, 150.18, 150.26, 150.32, 150.40, 150.36, 150.44, 150.50, 150.55, 150.56):
        rows.append((close + 0.02, close - 0.02, close))
    rows[16] = (150.60, 150.52, 150.56)
    rows.append((150.50, 150.42, 150.46))
    rows.append((150.44, 150.36, 150.40))
    rows.append((150.28, 150.22, 150.25))
    rows.append((150.27, 150.21, 150.24))
    rows.append((150.12, 150.05, 150.08))
    decision = evaluate(_bars(start, rows), spec, hourly=_days(datetime(2026, 1, 1, tzinfo=timezone.utc), [151 - i * 0.02 for i in range(40)]))
    assert decision.draft is not None, decision.log_line
    assert decision.draft.side == "sell"
    assert decision.draft.sl - decision.draft.entry == pytest_approx(0.50)


def test_a_non_forex_pip_is_one_hundredth_of_one_percent_of_price():
    gold = get_symbol("gold")
    assert gold is not None
    assert icwr_pip(gold, 2000.0) == pytest_approx(0.20)
    assert icwr_pip(gold, 2000.0) * 40 == pytest_approx(8.0)
    assert icwr_pip(gold, 2000.0) * 50 == pytest_approx(10.0)
