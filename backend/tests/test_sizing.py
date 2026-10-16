import pytest

from app.ea_proto import parse_execution
from app.models import BrokerSpec, Settings
from app.quotes import _pick_spec
from app.sizing import chase_for, chase_limit, lots_from_contract, lots_from_ticks, rebase_levels
from app.symbols import aliases_for, broker_symbol_matches, get_symbol, parse_alias_overrides
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
    assert chase_limit(1.10, 1.09, 0.0001) == pytest.approx(0.0040)


def test_commodities_are_not_refused_for_a_different_broker_price():
    oil = get_symbol("oil")
    gold = get_symbol("gold")
    eurusd = get_symbol("eurusd")
    assert oil is not None and gold is not None and eurusd is not None
    assert chase_for(oil, 80, 79.5) == 0
    assert chase_for(gold, 2650, 2642) == 0
    assert chase_for(eurusd, 1.10, 1.09) == pytest.approx(0.004)


def test_rebase_keeps_the_stop_distance_when_the_cash_price_differs():
    entry, sl, tp = rebase_levels("buy", 80.0, 79.5, 80.5, 77.20, 77.25)
    assert entry == pytest.approx(77.25)
    assert entry - sl == pytest.approx(0.50)
    assert tp - entry == pytest.approx(0.50)


def test_rebase_keeps_a_missing_target_at_zero():
    entry, sl, tp = rebase_levels("buy", 1.10, 1.095, 0.0, 1.1002, 1.1004)
    assert entry == pytest.approx(1.1004)
    assert entry - sl == pytest.approx(0.005)
    assert tp == 0.0


def test_rebase_scales_soybeans_from_cents_onto_dollars():
    entry, sl, tp = rebase_levels("sell", 1050.0, 1058.0, 1042.0, 10.52, 10.55)
    assert entry == pytest.approx(10.52)
    assert sl - entry == pytest.approx(0.08)
    assert entry - tp == pytest.approx(0.08)


def test_xm_commodity_names_match_month_codes():
    copper = get_symbol("copper")
    ngas = get_symbol("ngas")
    soybean = get_symbol("soybean")
    assert copper is not None and ngas is not None and soybean is not None
    assert aliases_for(ngas, "")[0] == "NGASCash"
    assert broker_symbol_matches("HGCOP-DEC26", aliases_for(copper, ""))
    assert broker_symbol_matches("SBEAN", aliases_for(soybean, ""))
    assert not broker_symbol_matches("NGAS-JAN26", ("NGASCash",))
    assert not broker_symbol_matches("EURUSD", aliases_for(copper, ""))


def test_cash_symbol_beats_the_futures_month():
    spec = get_symbol("ngas")
    assert spec is not None
    settings = Settings(user_id=1, account_type="standard", alias_overrides="")
    rows = [
        BrokerSpec(
            user_id=1, broker_symbol="NGAS-JAN26", contract_size=1000, tick_size=0.001,
            tick_value=1, min_lot=1, max_lot=10, lot_step=0.01, digits=3, bid=3.1, ask=3.12,
        ),
        BrokerSpec(
            user_id=1, broker_symbol="NGASCash", contract_size=1000, tick_size=0.001,
            tick_value=1, min_lot=0.01, max_lot=10, lot_step=0.01, digits=3, bid=2.8, ask=2.82,
        ),
    ]
    picked = _pick_spec(rows, spec, settings)
    assert picked is not None
    assert picked.broker_symbol == "NGASCash"


def test_stop_move_reports_keep_their_status():
    report = parse_execution("delivery_id=fx15\nstatus=sl_lock\nfill_price=77.4\n")
    assert report.delivery_id == 15
    assert report.status == "sl_lock"
    assert report.fill_price == pytest.approx(77.4)


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
