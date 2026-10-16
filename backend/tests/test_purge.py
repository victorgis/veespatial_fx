"""Trading rows go at 02:00 Africa/Lagos. Accounts do not."""

from datetime import datetime, timedelta, timezone

from app.models import BotConfig, BrokerSpec, Delivery, LastPrice, ScanRun, Settings, Signal, User, new_settings
from app.purge import LAGOS, clear_trading_data, purge_cutoff


def test_cutoff_is_the_latest_2am_in_lagos():
    # 01:59 WAT on 16 Oct 2026 is 00:59 UTC. The clear still belongs to the previous morning.
    before = datetime(2026, 10, 16, 0, 59, tzinfo=timezone.utc)
    assert purge_cutoff(before) == datetime(2026, 10, 15, 1, 0, tzinfo=timezone.utc)
    # 02:00 WAT is 01:00 UTC.
    at_two = datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)
    assert purge_cutoff(at_two) == datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)
    afternoon = datetime(2026, 10, 16, 15, 0, tzinfo=timezone.utc)
    assert purge_cutoff(afternoon) == datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)


def test_clear_removes_old_trades_and_keeps_the_account(client):
    from app.database import session_scope

    now = datetime(2026, 10, 16, 2, 0, tzinfo=timezone.utc)  # 03:00 WAT
    cutoff = purge_cutoff(now)
    old = cutoff - timedelta(minutes=5)
    fresh = cutoff + timedelta(hours=1)

    db = session_scope()
    user = User(email="purge@example.com", name="Ada", password_hash="hash")
    db.add(user)
    db.flush()
    settings = new_settings(user.id)
    settings.risk_percent = 1.25
    settings.ea_key_prefix = "fxkey"
    db.add(settings)
    watch = db.get(BotConfig, 1)
    watch.enabled_symbols = "eurusd"
    db.add(LastPrice(symbol_id="eurusd", close=1.1, updated_at=old))
    db.add(
        BrokerSpec(
            user_id=user.id,
            broker_symbol="EURUSD",
            contract_size=100000,
            tick_size=0.00001,
            tick_value=1,
            min_lot=0.01,
            max_lot=50,
            lot_step=0.01,
            digits=5,
            bid=1.1,
            ask=1.1002,
            updated_at=old,
        )
    )
    old_signal = Signal(
        symbol_id="eurusd",
        side="buy",
        entry=1.1,
        sl=1.095,
        tp=0,
        atr=0.006,
        rsi=60,
        candle_time=old,
        source="test",
        rationale="old",
        status="active",
        created_at=old,
    )
    fresh_signal = Signal(
        symbol_id="gbpusd",
        side="sell",
        entry=1.3,
        sl=1.305,
        tp=0,
        atr=0.006,
        rsi=40,
        candle_time=fresh,
        source="test",
        rationale="fresh",
        status="active",
        created_at=fresh,
    )
    db.add(old_signal)
    db.add(fresh_signal)
    db.flush()
    db.add(
        Delivery(
            signal_id=old_signal.id,
            user_id=user.id,
            status="placed",
            message="old",
            created_at=old,
            updated_at=old,
        )
    )
    db.add(
        Delivery(
            signal_id=fresh_signal.id,
            user_id=user.id,
            status="queued",
            message="fresh",
            created_at=fresh,
            updated_at=fresh,
        )
    )
    db.add(ScanRun(started_at=old, ok=True, message="old", signals_created=1))
    db.add(ScanRun(started_at=fresh, ok=True, message="fresh", signals_created=1))
    db.commit()
    fresh_id = fresh_signal.id
    user_id = user.id
    db.close()

    removed = clear_trading_data(now)
    assert removed == {"deliveries": 1, "signals": 1, "scan_runs": 1}

    db = session_scope()
    assert db.query(Signal).filter(Signal.rationale == "old").count() == 0
    assert db.query(Delivery).filter(Delivery.message == "old").count() == 0
    assert db.query(ScanRun).filter(ScanRun.message == "old").count() == 0
    kept = db.get(Signal, fresh_id)
    assert kept is not None and kept.rationale == "fresh"
    assert db.query(Delivery).filter(Delivery.signal_id == fresh_id).count() == 1
    assert db.query(ScanRun).filter(ScanRun.message == "fresh").count() == 1
    assert db.get(User, user_id).email == "purge@example.com"
    assert db.get(Settings, user_id).risk_percent == 1.25
    assert db.get(Settings, user_id).ea_key_prefix == "fxkey"
    assert db.get(BotConfig, 1).enabled_symbols == "eurusd"
    assert db.get(LastPrice, "eurusd").close == 1.1
    assert db.query(BrokerSpec).filter(BrokerSpec.user_id == user_id).count() == 1
    db.close()


def test_before_2am_keeps_trades_opened_after_the_previous_clear(client):
    from app.database import session_scope

    # 01:30 WAT on 16 Oct. Yesterday's 02:00 is the cutoff, so a trade from yesterday afternoon stays.
    now = datetime(2026, 10, 15, 23, 30, tzinfo=timezone.utc)
    afternoon = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
    db = session_scope()
    db.add(
        Signal(
            symbol_id="eurusd",
            side="buy",
            entry=1.1,
            sl=1.095,
            tp=0,
            atr=0.006,
            rsi=55,
            candle_time=afternoon,
            source="test",
            rationale="afternoon",
            status="active",
            created_at=afternoon,
        )
    )
    db.commit()
    db.close()

    removed = clear_trading_data(now)
    assert removed["signals"] == 0
    db = session_scope()
    assert db.query(Signal).filter(Signal.rationale == "afternoon").count() == 1
    db.close()


def test_empty_clear_is_a_no_op(client):
    assert clear_trading_data(datetime(2026, 10, 16, 1, 0, tzinfo=timezone.utc)) == {
        "deliveries": 0,
        "signals": 0,
        "scan_runs": 0,
    }


def test_purge_job_is_2am_lagos():
    from app.scheduler import start_scheduler

    scheduler = start_scheduler()
    try:
        job = scheduler.get_job("purge-trading-data")
        assert job is not None
        zone = getattr(job.trigger.timezone, "key", None) or getattr(job.trigger.timezone, "zone", None)
        assert zone == LAGOS.key
        hour = next(field for field in job.trigger.fields if field.name == "hour")
        minute = next(field for field in job.trigger.fields if field.name == "minute")
        assert str(hour) == "2"
        assert str(minute) == "0"
    finally:
        scheduler.shutdown(wait=False)
