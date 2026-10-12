"""The desk's behaviour around automatic vs manual, and standard vs micro."""

from datetime import datetime, timedelta, timezone

import pytest

from app.ea_proto import format_orders, parse_heartbeat
from app.market import FetchResult, set_market_override
from app.strategy import Bar, SignalDraft
from app.symbols import ALL_IDS


class FakeMarket:
    def __init__(self) -> None:
        self.phase = 1

    def fetch(self, spec):  # type: ignore[no-untyped-def]
        if self.phase == 1:
            when = datetime(2026, 1, 2, tzinfo=timezone.utc)
            high = 1.105
        else:
            when = datetime(2026, 1, 4, tzinfo=timezone.utc)
            high = 1.20
        bar = Bar(when, 1.10, high, 1.095, 1.10)
        return FetchResult([bar], "test")


def _draft(bars, spec, params=None, **_kwargs):  # type: ignore[no-untyped-def]
    if spec.id != "eurusd":
        return None
    # Far enough apart that the cooldown between signals does not swallow the second one.
    hour = 1 if bars and bars[-1].time.day < 4 else 40
    candle = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=hour)
    return SignalDraft("buy", 1.10, 1.09, 1.12, 0.00667, 58.0, candle)


def _auth(client, email="ada@example.com"):  # type: ignore[no-untyped-def]
    created = client.post("/api/auth/register", json={"email": email, "name": "Ada", "password": "correct-horse"})
    assert created.status_code == 200, created.text
    token = created.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _save(client, headers, **overrides):  # type: ignore[no-untyped-def]
    body = {
        "trade_mode": "manual",
        "account_type": "micro",
        "platform": "mt5",
        "risk_percent": 1,
        "max_lot": 50,
        "planning_balance": 10000,
        "enabled_symbols": list(ALL_IDS),
        "alias_overrides": "",
        "onboarding_done": True,
        "risk_accepted": True,
        "trust_platform_size": False,
    }
    body.update(overrides)
    saved = client.put("/api/settings", json=body, headers=headers)
    assert saved.status_code == 200, saved.text
    return saved.json()


def _install_market(monkeypatch):  # type: ignore[no-untyped-def]
    market = FakeMarket()
    set_market_override(market)
    monkeypatch.setattr("app.scan.evaluate", _draft)
    monkeypatch.setattr("app.scan.telegram_send", lambda text: False)
    return market


def test_register_login_and_rejects_auto_on_the_xm_app(client):
    headers = _auth(client)
    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["is_admin"] is True
    rejected = client.put(
        "/api/settings",
        json={
            "trade_mode": "auto",
            "account_type": "standard",
            "platform": "xm",
            "risk_percent": 0.5,
            "max_lot": 0.5,
            "planning_balance": 1000,
            "enabled_symbols": ["eurusd"],
            "onboarding_done": True,
            "risk_accepted": True,
        },
        headers=headers,
    )
    assert rejected.status_code == 400
    assert "XM app" in rejected.json()["detail"]


def test_manual_micro_size_and_auto_standard_execution(client, monkeypatch):
    market = _install_market(monkeypatch)
    headers = _auth(client)
    _save(client, headers)

    scanned = client.post("/api/system/scan", headers=headers)
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["signals_created"] == 1

    home = client.get("/api/dashboard", headers=headers).json()
    assert home["me"]["status_line"].startswith("You are on signals only")
    signal = home["signals"][0]
    assert signal["display"] == "EURUSD"
    assert signal["side"] == "buy"
    assert signal["quote"]["lots"] == 10
    assert signal["quote"]["standard_lots"] == 0.1
    assert signal["quote"]["micro_lots"] == 10
    assert "10.00" in signal["copy_text"]
    assert signal["delivery_status"] == "for_you"

    marked = client.post(f"/api/signals/{signal['id']}/mark", json={"action": "you_placed"}, headers=headers)
    assert marked.status_code == 200
    assert marked.json()["delivery_status"] == "you_placed"

    switched = _save(client, headers, trade_mode="auto", account_type="standard", max_lot=1)
    key = switched["ea_key"]
    assert key.startswith("fxk_")
    # The signal from the manual period must not be sent just because auto is now on.
    waiting = client.get("/api/ea/orders", headers={"X-Api-Key": key})
    assert waiting.status_code == 200
    assert waiting.text.split("---", 1)[1].strip() == ""

    beat = "\n".join(
        [
            "platform=mt5",
            "login=12345678",
            "broker=XMTrading-MT5",
            "balance=10000",
            "equity=10000",
            "currency=USD",
            "fx_contract=100000",
            "fx_symbol=EURUSD",
            "spec=EURUSD|100000|0.00001|1|0.01|50|0.01|5|1.10000|1.10002",
        ]
    )
    parsed = parse_heartbeat(beat)
    assert parsed.fx_contract == 100000
    assert parsed.specs[0].broker_symbol == "EURUSD"
    hb = client.post("/api/ea/heartbeat", content=beat, headers={"X-Api-Key": key})
    assert hb.status_code == 200
    assert "mismatch=0" in hb.text

    market.phase = 2
    again = client.post("/api/system/scan", headers=headers)
    assert again.json()["signals_created"] == 1

    orders = client.get("/api/ea/orders", headers={"X-Api-Key": key})
    payload = orders.text.split("---", 1)[1].strip().splitlines()
    assert len(payload) == 1
    parts = payload[0].split("|")
    assert parts[1] == "buy"
    assert "EURUSD" in parts[2]
    assert parts[6] == "0.10"
    delivery_id = parts[0]

    report = "\n".join(
        [
            f"delivery_id={delivery_id}",
            "status=placed",
            "ticket=998877",
            "fill_price=1.10001",
            "lots=0.10",
            "broker_symbol=EURUSD",
            "message=filled",
        ]
    )
    done = client.post("/api/ea/executions", content=report, headers={"X-Api-Key": key})
    assert done.status_code == 200
    home = client.get("/api/dashboard", headers=headers).json()
    placed = [s for s in home["signals"] + home["recent"] if s["delivery_status"] == "placed"]
    assert placed
    assert placed[0]["ticket"] == "998877"
    assert home["me"]["connection"]["online"] is True
    assert home["me"]["connection"]["detected_account_type"] == "standard"


def test_mismatch_pauses_and_does_not_resume(client, monkeypatch):
    market = _install_market(monkeypatch)
    headers = _auth(client, "bea@example.com")
    _save(client, headers, trade_mode="auto", account_type="standard", max_lot=1, planning_balance=10000)
    # Key is created because auto is on. Read it by rotating so the test holds the secret.
    # Saving auto the first time already returned it; call save again only returns a key when missing.
    first = client.put(
        "/api/settings",
        json={
            "trade_mode": "auto",
            "account_type": "standard",
            "platform": "mt5",
            "risk_percent": 1,
            "max_lot": 1,
            "planning_balance": 10000,
            "enabled_symbols": list(ALL_IDS),
            "onboarding_done": True,
            "risk_accepted": True,
            "trust_platform_size": False,
        },
        headers=headers,
    )
    # Second save does not repeat the secret. Rotate to obtain one.
    assert first.json()["ea_key"] is None or first.json()["ea_key"].startswith("fxk_")
    key = first.json()["ea_key"]
    if not key:
        rotated = client.post("/api/settings/ea-key", headers=headers)
        key = rotated.json()["ea_key"]

    client.post("/api/system/scan", headers=headers)
    beat = "\n".join(
        [
            "platform=mt5",
            "login=55",
            "broker=XM",
            "balance=10000",
            "equity=10000",
            "currency=USD",
            "fx_contract=100000",
            "fx_symbol=EURUSD",
            "spec=EURUSD|100000|0.00001|1|0.01|50|0.01|5|1.1|1.10002",
        ]
    )
    assert client.post("/api/ea/heartbeat", content=beat, headers={"X-Api-Key": key}).status_code == 200
    # The signal was created while already auto, so it is queued. Move the candle forward and
    # rescan only if the first one was not queued — it should be queued already.
    orders = client.get("/api/ea/orders", headers={"X-Api-Key": key})
    assert "0.10" in orders.text
    old_id = orders.text.split("---", 1)[1].strip().splitlines()[0].split("|")[0]

    _save(client, headers, trade_mode="auto", account_type="micro", max_lot=50, planning_balance=10000)
    paused = client.get("/api/ea/orders", headers={"X-Api-Key": key})
    assert paused.text.split("---", 1)[1].strip() == ""
    assert "mismatch=1" in client.post("/api/ea/heartbeat", content=beat, headers={"X-Api-Key": key}).text

    # Switching the label back does not revive the paused signal.
    _save(client, headers, trade_mode="auto", account_type="standard", max_lot=1, planning_balance=10000)
    market.phase = 2
    client.post("/api/system/scan", headers=headers)
    resumed = client.get("/api/ea/orders", headers={"X-Api-Key": key})
    # A new signal may exist because phase 2 closed the old idea. The paused one must not return
    # with the original delivery. We only assert the account is tradable again: a buy line is allowed
    # for the NEW signal, and the dashboard says connected rather than paused.
    home = client.get("/api/dashboard", headers=headers).json()
    assert "paused" not in home["me"]["status_line"]
    assert home["me"]["connection"]["mismatch"] is False
    resumed_body = resumed.text.split("---", 1)[1]
    assert f"{old_id}|" not in resumed_body


def test_automatic_cap_keeps_extra_signals_on_telegram(client, monkeypatch):
    set_market_override(FakeMarket())
    sent: list[str] = []

    def _many(bars, spec, params=None, **_kwargs):  # type: ignore[no-untyped-def]
        if spec.id not in ("eurusd", "gbpusd", "usdjpy", "usdchf"):
            return None
        return SignalDraft("buy", 1.10, 1.09, 1.12, 0.00667, 48.0, datetime(2026, 3, 2, 12, tzinfo=timezone.utc))

    monkeypatch.setattr("app.scan.evaluate", _many)
    monkeypatch.setattr("app.scan.telegram_send", lambda text: sent.append(text) or True)
    auto = _auth(client, "auto-cap@example.com")
    manual = _auth(client, "hand-cap@example.com")
    rejected = client.put(
        "/api/settings",
        json={
            "trade_mode": "auto",
            "account_type": "standard",
            "platform": "mt5",
            "risk_percent": 1,
            "max_lot": 1,
            "planning_balance": 10000,
            "enabled_symbols": list(ALL_IDS),
            "onboarding_done": True,
            "risk_accepted": True,
            "max_open_trades": 6,
        },
        headers=auto,
    )
    assert rejected.status_code == 400
    saved = _save(
        client,
        auto,
        trade_mode="auto",
        account_type="standard",
        max_lot=1,
        planning_balance=10000,
        max_open_trades=3,
    )
    _save(client, manual, trade_mode="manual", account_type="micro")
    scanned = client.post("/api/system/scan", headers=auto)
    assert scanned.status_code == 200, scanned.text
    assert scanned.json()["signals_created"] == 4
    assert len(sent) == 4

    auto_home = client.get("/api/dashboard", headers=auto).json()
    auto_status = sorted(row["delivery_status"] for row in auto_home["signals"])
    assert auto_status.count("queued") == 3
    assert auto_status.count("capped") == 1
    specs = "\n".join(
        f"spec={name}|100000|0.00001|1|0.01|50|0.01|5|1.10000|1.10002"
        for name in ("EURUSD", "GBPUSD", "USDJPY", "USDCHF")
    )
    beat = "\n".join(
        [
            "platform=mt5",
            "login=12345678",
            "broker=XMTrading-MT5",
            "balance=10000",
            "equity=10000",
            "currency=USD",
            "fx_contract=100000",
            "fx_symbol=EURUSD",
            specs,
        ]
    )
    hb = client.post("/api/ea/heartbeat", content=beat, headers={"X-Api-Key": saved["ea_key"]})
    assert hb.status_code == 200, hb.text
    orders = client.get("/api/ea/orders", headers={"X-Api-Key": saved["ea_key"]})
    placed = [line for line in orders.text.split("---", 1)[1].splitlines() if line.strip()]
    assert len(placed) == 3

    manual_home = client.get("/api/dashboard", headers=manual).json()
    assert {row["delivery_status"] for row in manual_home["signals"]} == {"for_you"}
    assert len(manual_home["signals"]) == 4


def test_close_is_not_sent_to_telegram(client, monkeypatch):
    market = _install_market(monkeypatch)
    sent: list[str] = []
    monkeypatch.setattr("app.scan.telegram_send", lambda text: sent.append(text) or True)
    headers = _auth(client, "close-quiet@example.com")
    _save(client, headers, trade_mode="manual")
    first = client.post("/api/system/scan", headers=headers)
    assert first.status_code == 200, first.text
    assert len(sent) == 1
    assert "BUY" in sent[0]
    market.phase = 2
    sent.clear()
    second = client.post("/api/system/scan", headers=headers)
    assert second.status_code == 200, second.text
    assert all("reached the target" not in text and "hit the stop" not in text for text in sent)


def test_oil_order_is_anchored_to_the_mt5_price(client):
    headers = _auth(client, "oil@example.com")
    saved = _save(
        client,
        headers,
        trade_mode="auto",
        account_type="standard",
        max_lot=5,
        planning_balance=10000,
    )
    key = saved["ea_key"]
    user_id = client.get("/api/me", headers=headers).json()["user"]["id"]
    beat = "\n".join(
        [
            "platform=mt5",
            "login=1",
            "broker=XMTrading-MT5",
            "balance=10000",
            "equity=10000",
            "currency=USD",
            "fx_contract=100000",
            "fx_symbol=EURUSD",
            "spec=EURUSD|100000|0.00001|1|0.01|50|0.01|5|1.10000|1.10020",
            "spec=OILCash|100|0.01|1|0.01|50|0.01|3|77.20|77.25",
        ]
    )
    heartbeat = client.post("/api/ea/heartbeat", content=beat, headers={"X-Api-Key": key})
    assert heartbeat.status_code == 200, heartbeat.text
    from app.database import session_scope
    from app.models import Delivery, Signal

    db = session_scope()
    signal = Signal(
        symbol_id="oil",
        side="buy",
        entry=80.0,
        sl=79.5,
        tp=81.0,
        atr=0.4,
        rsi=48,
        candle_time=datetime(2026, 4, 1, tzinfo=timezone.utc),
        source="test",
        rationale="test",
        status="active",
    )
    db.add(signal)
    db.flush()
    db.add(
        Delivery(
            signal_id=signal.id,
            user_id=user_id,
            status="not_placed",
            message="Price moved away from the signal.",
        )
    )
    db.commit()
    db.close()
    orders = client.get("/api/ea/orders", headers={"X-Api-Key": key})
    assert orders.status_code == 200, orders.text
    body = [line for line in orders.text.split("---", 1)[1].splitlines() if line.strip()]
    assert len(body) == 1
    parts = body[0].split("|")
    assert "OILCash" in parts[2]
    assert parts[2].split(",")[0] == "OILCash"
    assert float(parts[3]) == pytest.approx(77.25)
    assert float(parts[4]) == pytest.approx(76.75)
    assert float(parts[7]) == pytest.approx(0.0)


def test_order_formatter_and_copier_files():
    from app.ea_proto import OrderOut

    text = format_orders(
        "auto",
        "micro",
        "",
        [OrderOut(4, "sell", ["BRENTCash", "BRENTCash#"], 80, 82, 76, 0.5, 0.5, "fx4")],
    )
    assert text.splitlines()[0] == "mode=auto"
    assert "BRENTCash" in text
    from app.routers.system import experts_dir

    folder = experts_dir()
    for name in ("SignalBridge.mq5", "SignalBridge.mq4"):
        source = (folder / name).read_text()
        assert "WebRequest" in source
        assert "X-Api-Key" in name or "X-Api-Key" in source


def test_download_and_markets(client):
    headers = _auth(client, "cy@example.com")
    markets = client.get("/api/markets", headers=headers)
    ids = {row["id"] for row in markets.json()}
    assert {"eurusd", "gold", "oil", "brent"} <= ids
    oil = next(row for row in markets.json() if row["id"] == "oil")
    assert oil["mt5_only"] is True
    assert "OILCash" in oil["aliases"]
    brent = next(row for row in markets.json() if row["id"] == "brent")
    assert "BRENTCash" in brent["aliases"]
    downloaded = client.get("/api/downloads/SignalBridge.mq5")
    assert downloaded.status_code == 200
    assert "WebRequest" in downloaded.text
    assert client.get("/api/health").json()["ok"] is True
    assert client.get("/health").json()["ok"] is True
