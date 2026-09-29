"""Candle decoding. These do not call Dukascopy or Yahoo."""

import lzma
import struct
from datetime import datetime, timedelta, timezone

from app.market import decode_bid_candles, decode_hour_ticks, minutes_to_hours, series_is_fresh
from app.strategy import Bar
from app.telegram_svc import explain_telegram_error

_RECORD = struct.Struct(">5If")


def _blob(*rows: tuple) -> bytes:
    return lzma.compress(b"".join(_RECORD.pack(*row) for row in rows))


def test_hour_file_drops_flat_padding_and_scales_the_price():
    origin = datetime(2026, 8, 1, tzinfo=timezone.utc)
    blob = _blob(
        (0, 100000, 100000, 100000, 100000, 0.0),
        (3600, 116000, 116200, 115800, 116400, 10.0),
    )
    bars = decode_bid_candles(blob, origin, 100_000)
    assert len(bars) == 1
    assert bars[0].time == origin + timedelta(hours=1)
    assert bars[0].open == 1.16
    assert bars[0].close == 1.162
    assert bars[0].low == 1.158
    assert bars[0].high == 1.164


def test_tick_hour_uses_the_bid():
    hour = datetime(2026, 9, 29, 11, tzinfo=timezone.utc)
    tick = struct.Struct(">3I2f")
    raw = tick.pack(0, 113600, 113500, 1.0, 1.0) + tick.pack(1000, 113700, 113200, 1.0, 1.0)
    raw += tick.pack(2000, 113550, 113450, 1.0, 1.0)
    bar = decode_hour_ticks(lzma.compress(raw), hour, 100_000)
    assert bar is not None
    assert bar.time == hour
    assert bar.open == 1.135
    assert bar.high == 1.135
    assert bar.low == 1.132
    assert bar.close == 1.1345


def test_minutes_collapse_into_the_hour_they_belong_to():
    start = datetime(2026, 9, 25, 14, 0, tzinfo=timezone.utc)
    hours = minutes_to_hours(
        [
            Bar(start, 1.0, 1.2, 0.9, 1.1),
            Bar(start + timedelta(minutes=30), 1.1, 1.3, 1.0, 1.15),
            Bar(start + timedelta(hours=1), 1.15, 1.16, 1.14, 1.15),
        ]
    )
    assert len(hours) == 2
    assert hours[0].time == start
    assert hours[0].open == 1.0
    assert hours[0].high == 1.3
    assert hours[0].low == 0.9
    assert hours[0].close == 1.15
    assert hours[1].open == 1.15


def test_friday_close_is_stale_once_the_new_week_is_trading():
    friday = datetime(2026, 9, 25, 20, tzinfo=timezone.utc)
    start = friday - timedelta(hours=229)
    bars = [Bar(start + timedelta(hours=i), 1.1, 1.2, 1.0, 1.1) for i in range(230)]
    assert series_is_fresh(bars, datetime(2026, 9, 27, 12, tzinfo=timezone.utc)) is True
    assert series_is_fresh(bars, datetime(2026, 9, 29, 12, tzinfo=timezone.utc)) is False


def test_chat_not_found_names_the_channel_id_and_hides_the_token():
    text = explain_telegram_error(400, '{"ok":false,"description":"Bad Request: chat not found"}')
    assert "-100" in text
    assert "admin" in text
    assert "bot" in text.lower()
    assert "api.telegram.org" not in text
