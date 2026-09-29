"""Market data tests."""

from datetime import datetime, timedelta, timezone

from app.market import (
    MassiveMarket,
    FetchResult,
    clear_cache,
    drop_forming,
    get_market,
    m5_is_fresh,
    resample,
    series_is_fresh,
    session_open,
    set_market_override,
)
from app.strategy import Bar
from app.telegram_svc import explain_telegram_error


def test_session_and_five_minute_freshness():
    assert session_open(datetime(2026, 9, 25, 21, tzinfo=timezone.utc)) is True
    assert session_open(datetime(2026, 9, 25, 22, tzinfo=timezone.utc)) is False
    assert session_open(datetime(2026, 9, 26, 12, tzinfo=timezone.utc)) is False
    assert session_open(datetime(2026, 9, 27, 21, tzinfo=timezone.utc)) is False
    assert session_open(datetime(2026, 9, 27, 22, 30, tzinfo=timezone.utc)) is True
    now = datetime(2026, 9, 28, 12, 10, tzinfo=timezone.utc)
    fresh = [Bar(datetime(2026, 9, 28, 12, tzinfo=timezone.utc), 1, 2, 1, 1)]
    stale = [Bar(datetime(2026, 9, 28, 11, 40, tzinfo=timezone.utc), 1, 2, 1, 1)]
    assert m5_is_fresh(fresh, now) is True
    assert m5_is_fresh(stale, now) is False


def test_resample_and_drop_the_candle_that_is_still_open():
    start = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
    minutes = [
        Bar(start, 1.0, 1.2, 0.9, 1.1),
        Bar(start + timedelta(minutes=1), 1.1, 1.3, 1.0, 1.15),
        Bar(start + timedelta(minutes=5), 1.15, 1.16, 1.14, 1.15),
    ]
    five = resample(minutes, 5)
    assert [bar.time for bar in five] == [start, start + timedelta(minutes=5)]
    assert five[0].high == 1.3
    assert five[0].close == 1.15
    closed = drop_forming(five, 5, start + timedelta(minutes=7))
    assert [bar.time for bar in closed] == [start]


def test_chat_not_found_names_the_channel_id_and_hides_the_token():
    text = explain_telegram_error(400, '{"ok":false,"description":"Bad Request: chat not found"}')
    assert "-100" in text
    assert "admin" in text
    assert "bot" in text.lower()
    assert "api.telegram.org" not in text


def test_massive_market_fetches_candles_and_respects_key(monkeypatch):
    from app.symbols import get_symbol

    clear_cache()
    set_market_override(None)
    spec = get_symbol("eurusd")
    assert spec is not None

    # Test without key
    market_nokey = MassiveMarket("")
    res_nokey = market_nokey._download(spec)
    assert "MASSIVE_API_KEY is not configured" in res_nokey.error

    # Mock httpx responses for 1h and 5m
    class FakeResponse:
        def __init__(self, status_code, data):
            self.status_code = status_code
            self._data = data

        def json(self):
            return self._data

    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    fake_results_1h = [
        {"t": now_ms - (i * 3600 * 1000), "o": 1.10, "h": 1.11, "l": 1.09, "c": 1.10, "v": 100}
        for i in range(250, 0, -1)
    ]
    fake_results_5m = [
        {"t": now_ms - (i * 300 * 1000), "o": 1.10, "h": 1.11, "l": 1.09, "c": 1.10, "v": 10}
        for i in range(50, 0, -1)
    ]

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url):
            if "/range/1/hour/" in url:
                return FakeResponse(200, {"results": fake_results_1h, "status": "OK"})
            if "/range/5/minute/" in url:
                return FakeResponse(200, {"results": fake_results_5m, "status": "OK"})
            return FakeResponse(404, {})

    monkeypatch.setattr("httpx.Client", FakeClient)

    market = MassiveMarket("fake_key_123")
    res = market.fetch(spec)
    assert res.error is None
    assert "Massive API C:EURUSD" in res.source
    assert len(res.hourly) >= 220


def test_massive_market_fallback_on_429(monkeypatch):
    from app.symbols import get_symbol

    clear_cache()
    spec = get_symbol("eurusd")
    assert spec is not None

    class Fake429Client:
        def __init__(self, *args, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def get(self, url):
            class Resp:
                status_code = 429
            return Resp()

    monkeypatch.setattr("httpx.Client", Fake429Client)

    # Mock YahooMarket to verify fallback is called
    dummy_bar = Bar(datetime.now(timezone.utc), 1.1, 1.1, 1.1, 1.1)
    yahoo_fallback_result = FetchResult(
        bars=[dummy_bar],
        source="Yahoo Finance EURUSD=X",
        hourly=[dummy_bar] * 220,
    )
    monkeypatch.setattr("app.market.YahooMarket.fetch", lambda self, spec: yahoo_fallback_result)

    market = MassiveMarket("fake_key_123")
    res = market.fetch(spec)
    assert res.error is None
    assert "Yahoo Finance" in res.source
