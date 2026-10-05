"""Market data tests."""

from datetime import datetime, timedelta, timezone

from app.market import (
    FetchResult,
    YahooMarket,
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



