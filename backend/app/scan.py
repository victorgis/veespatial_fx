"""One pass over the watched markets: update outcomes, then look for a new signal."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.database import session_scope
from app.market import get_market
from app.models import BotConfig, Delivery, LastPrice, ScanRun, Settings, Signal, User, utcnow
from app.strategy import bar_hit, evaluate
from app.strategy import StrategyParams
from app.symbols import get_symbol
from app.telegram_svc import send as telegram_send
from app.wording import close_message, rationale, telegram_message
from app.sizing import lots_from_contract

log = logging.getLogger("desk.scan")
_lock = threading.Lock()


def params_from_settings() -> StrategyParams:
    cfg = get_settings()
    return StrategyParams(
        fast=cfg.ema_fast,
        slow=cfg.ema_slow,
        trend=cfg.ema_trend,
        rsi_n=cfg.rsi_period,
        atr_n=cfg.atr_period,
        sl_mult=cfg.sl_atr,
        tp_mult=cfg.tp_atr,
    )


def _watched_ids(db) -> list[str]:  # type: ignore[no-untyped-def]
    row = db.get(BotConfig, 1)
    if row is None or not row.enabled_symbols.strip():
        return []
    return [p.strip() for p in row.enabled_symbols.split(",") if p.strip() and get_symbol(p.strip())]


def _delivery_status(user_settings: Settings, spec_id: str, spec_mt5_only: bool) -> tuple[str, str]:
    enabled = {p.strip() for p in (user_settings.enabled_symbols or "").split(",") if p.strip()}
    if spec_id not in enabled:
        return "off", "This market is turned off on your account."
    if user_settings.trade_mode != "auto":
        return "for_you", "Signals only. Place this yourself if you want it."
    if user_settings.platform == "xm":
        return "for_you", "The XM app cannot attach the copier. Place this yourself."
    if spec_mt5_only and user_settings.platform == "mt4":
        return "not_placed", "This cash market is on MT5 at XM. It was not sent to MT4."
    return "queued", "Waiting for your platform."


def _announce(db, spec, signal: Signal) -> bool:  # type: ignore[no-untyped-def]
    cfg = get_settings()
    ref_balance = cfg.telegram_reference_balance
    ref_risk = ref_balance * cfg.telegram_reference_risk / 100.0
    rates = {row.symbol_id: row.close for row in db.query(LastPrice).all()}
    standard = lots_from_contract(spec, "standard", ref_risk, signal.entry, signal.sl, "mt5", 100, "USD", rates)
    micro = lots_from_contract(spec, "micro", ref_risk, signal.entry, signal.sl, "mt5", 10_000, "USD", rates)
    text = telegram_message(
        spec,
        signal.side,
        signal.entry,
        signal.sl,
        signal.tp,
        standard,
        micro,
        signal.id,
        ref_balance,
        cfg.telegram_reference_risk,
    )
    return telegram_send(text)


def _resolve(signal: Signal, bars, now: datetime, expiry_hours: int) -> tuple[str, float] | None:
    future = []
    for bar in bars:
        t = bar.time if bar.time.tzinfo else bar.time.replace(tzinfo=timezone.utc)
        if t > signal.candle_time:
            future.append(bar)
    for bar in future:
        hit = bar_hit(signal.side, signal.sl, signal.tp, bar.high, bar.low)
        if hit == "stopped":
            return "stopped", signal.sl
        if hit == "target":
            return "target", signal.tp
    age = now - (signal.candle_time if signal.candle_time.tzinfo else signal.candle_time.replace(tzinfo=timezone.utc))
    if age > timedelta(hours=expiry_hours) and bars:
        return "expired", bars[-1].close
    return None


def run_scan() -> dict:
    if not _lock.acquire(blocking=False):
        return {"status": "busy", "message": "A scan is already running.", "signals_created": 0}
    try:
        return _run()
    finally:
        _lock.release()


def _run() -> dict:
    cfg = get_settings()
    now = utcnow()
    db = session_scope()
    created = 0
    try:
        run = ScanRun(started_at=now, ok=False, message="", signals_created=0)
        db.add(run)
        db.flush()
        market = get_market()
        params = params_from_settings()
        ids = _watched_ids(db)
        fetched = {}
        failures: list[str] = []
        for symbol_id in ids:
            spec = get_symbol(symbol_id)
            if spec is None:
                continue
            result = market.fetch(spec)
            fetched[symbol_id] = result
            if result.error or not result.bars:
                failures.append(result.error or f"{spec.display}: no candles")
                continue
            last = result.bars[-1]
            row = db.get(LastPrice, symbol_id)
            if row is None:
                db.add(LastPrice(symbol_id=symbol_id, close=last.close, updated_at=now))
            else:
                row.close = last.close
                row.updated_at = now
        db.flush()

        users = db.query(User).all()
        user_settings = {s.user_id: s for s in db.query(Settings).all()}

        for symbol_id, result in fetched.items():
            spec = get_symbol(symbol_id)
            if spec is None or not result.bars:
                continue
            active = (
                db.query(Signal)
                .filter(Signal.symbol_id == symbol_id, Signal.status == "active")
                .all()
            )
            for signal in active:
                resolved = _resolve(signal, result.bars, now, cfg.signal_expiry_hours)
                if not resolved:
                    continue
                outcome, price = resolved
                signal.status = outcome
                signal.close_price = price
                signal.closed_at = now
                if not signal.close_telegram_sent:
                    if telegram_send(close_message(spec, signal.side, outcome, price)):
                        signal.close_telegram_sent = True
            db.flush()

            still = (
                db.query(Signal)
                .filter(Signal.symbol_id == symbol_id, Signal.status == "active")
                .first()
            )
            if still is not None:
                if not still.telegram_sent:
                    still.telegram_sent = _announce(db, spec, still)
                continue
            recent = (
                db.query(Signal)
                .filter(Signal.symbol_id == symbol_id)
                .order_by(Signal.candle_time.desc())
                .first()
            )
            draft = evaluate(result.bars, spec, params)
            if draft is None:
                continue
            if recent is not None:
                gap = draft.candle_time - recent.candle_time
                if gap < timedelta(hours=cfg.min_hours_between):
                    continue
            signal = Signal(
                symbol_id=spec.id,
                side=draft.side,
                entry=draft.entry,
                sl=draft.sl,
                tp=draft.tp,
                atr=draft.atr,
                rsi=draft.rsi,
                candle_time=draft.candle_time,
                source=result.source,
                rationale=rationale(spec, draft.side, draft.rsi),
                status="active",
                created_at=now,
            )
            try:
                with db.begin_nested():
                    db.add(signal)
                    db.flush()
                    for user in users:
                        settings = user_settings.get(user.id)
                        if settings is None:
                            continue
                        status, message = _delivery_status(settings, spec.id, spec.mt5_only)
                        db.add(
                            Delivery(
                                signal_id=signal.id,
                                user_id=user.id,
                                status=status,
                                message=message,
                                created_at=now,
                                updated_at=now,
                            )
                        )
                    db.flush()
            except IntegrityError:
                continue
            signal.telegram_sent = _announce(db, spec, signal)
            created += 1

        if ids and not any(r.bars for r in fetched.values()):
            ok = False
            message = "No market data. " + " ".join(failures)
        else:
            ok = True
            message = f"Checked {len(ids)} markets. New signals: {created}."
            if failures:
                message += " Data failed: " + "; ".join(failures[:6])
        run.ok = ok
        run.message = message[:2000]
        run.signals_created = created
        run.finished_at = utcnow()
        db.commit()
        return {"status": "ok" if ok else "degraded", "message": run.message, "signals_created": created}
    except Exception:
        log.exception("scan failed")
        db.rollback()
        try:
            fail = ScanRun(
                started_at=now,
                finished_at=utcnow(),
                ok=False,
                message="The scan stopped on an unexpected error.",
                signals_created=created,
            )
            db.add(fail)
            db.commit()
        except Exception:
            db.rollback()
        return {"status": "error", "message": "The scan stopped on an unexpected error.", "signals_created": created}
    finally:
        db.close()
