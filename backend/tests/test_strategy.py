from app.strategy import Snapshot, StrategyParams, bar_hit, decide, ema, levels, rsi


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
