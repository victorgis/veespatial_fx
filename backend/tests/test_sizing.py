import pytest

from app.sizing import chase_limit, lots_from_contract, lots_from_ticks
from app.symbols import get_symbol, parse_alias_overrides
from app.wording import status_line


def test_fx_micro_is_one_hundred_times_standard():
    spec = get_symbol("eurusd")
    assert spec is not None
    standard = lots_from_contract(spec, "standard", 100, 1.10, 1.09, "mt5", 100, "USD")
    micro = lots_from_contract(spec, "micro", 100, 1.10, 1.09, "mt5", 10_000, "USD")
    assert standard.lots == pytest.approx(0.10)
    assert micro.lots == pytest.approx(10.0)
    assert standard.units == pytest.approx(10_000)  # EUR
    assert micro.units == pytest.approx(10_000)


def test_gold_scales_the_same_way():
    spec = get_symbol("gold")
    assert spec is not None
    # $10 stop, $100 risk → 0.10 standard lots (10 oz) or 10 micro lots (10 oz).
    standard = lots_from_contract(spec, "standard", 100, 2000, 1990, "mt5", 100, "USD")
    micro = lots_from_contract(spec, "micro", 100, 2000, 1990, "mt5", 10_000, "USD")
    assert standard.lots == pytest.approx(0.10)
    assert micro.lots == pytest.approx(10.0)
    assert standard.units == pytest.approx(10)
    assert micro.units == pytest.approx(10)


def test_oil_and_brent_do_not_scale_with_account_type():
    for symbol_id in ("oil", "brent"):
        spec = get_symbol(symbol_id)
        assert spec is not None
        assert spec.scales_with_account is False
        standard = lots_from_contract(spec, "standard", 100, 80, 78, "mt5", 100, "USD")
        micro = lots_from_contract(spec, "micro", 100, 80, 78, "mt5", 100, "USD")
        assert standard.lots == pytest.approx(0.50)
        assert micro.lots == pytest.approx(0.50)
        assert standard.units == pytest.approx(50)  # barrels


def test_usdjpy_divides_by_price():
    spec = get_symbol("usdjpy")
    assert spec is not None
    sized = lots_from_contract(spec, "standard", 100, 150, 149.5, "mt5", 100, "USD")
    assert sized.lots == pytest.approx(0.30)


def test_min_lot_is_not_rounded_up_past_the_risk():
    spec = get_symbol("gold")
    assert spec is not None
    # $30 stop on 0.01 standard lots risks $30, but the account only allows $10.
    sized = lots_from_contract(spec, "standard", 10, 2000, 1970, "mt5", 100, "USD")
    assert sized.lots is None
    assert sized.too_small is True
    assert "Nothing will be placed automatically" in (sized.reason or "")


def test_live_ticks_match_the_contract_math():
    sized = lots_from_ticks(100, 0.01, 0.00001, 1.0, 100_000, 0.01, 0.01, 5, "USD")
    assert sized.lots == pytest.approx(0.10)


def test_chase_limit_is_a_quarter_of_the_stop():
    assert chase_limit(1.10, 1.09, 0.0001) == pytest.approx(0.0025)


def test_alias_override_rejects_unknown_markets():
    with pytest.raises(ValueError):
        parse_alias_overrides("not-a-market=EURUSD")
    parsed = parse_alias_overrides("oil=OILCash.pro\n# comment\n")
    assert parsed["oil"] == ["OILCash.pro"]


def test_status_sentences():
    assert "signals only" in status_line("manual", False, False, None)
    assert "not connected" in status_line("auto", False, False, None)
    assert "paused" in status_line("auto", True, True, "XM")
    assert "XM" in status_line("auto", True, False, "XM")
