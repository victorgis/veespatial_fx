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
from app.strategy import SignalDraft, StrategyParams, bar_hit
from app.strategy import evaluate_intraday as evaluate
from app.symbols import get_symbol
from app.telegram_svc import send as telegram_send
from app.wording import rationale, telegram_message
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


def open_trade_limit(value: int | None) -> int:
    """Automatic accounts stay between 1 and 5 open trades. 3 is the usual number."""
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 3
    if parsed < 1:
        return 1
    if parsed > 5:
        return 5
    return parsed


def _open_auto_count(db, user_id: int) -> int:  # type: ignore[no-untyped-def]
    return (
        db.query(Delivery)
        .join(Signal, Delivery.signal_id == Signal.id)
        .filter(
            Delivery.user_id == user_id,
            Delivery.status.in_(("queued", "paused", "placed")),
            Signal.status == "active",
        )
        .count()
    )


def _delivery_status(user_settings: Settings, spec_id: str, spec_mt5_only: bool, open_auto: int) -> tuple[str, str]:
    enabled = {p.strip() for p in (user_settings.enabled_symbols or "").split(",") if p.strip()}
    if spec_id not in enabled:
        return "off", "This market is turned off on your account."
    if user_settings.trade_mode != "auto":
        return "for_you", "Signals only. Place this yourself if you want it."
    if user_settings.platform == "xm":
        return "for_you", "The XM app cannot attach the copier. Place this yourself."
    if spec_mt5_only and user_settings.platform == "mt4":
        return "not_placed", "This cash market is on MT5 at XM. It was not sent to MT4."
    limit = open_trade_limit(getattr(user_settings, "max_open_trades", 3))
    if open_auto >= limit:
        return (
            "capped",
            f"You already have {limit} automatic trades open. This signal is on Telegram for you to place by hand.",
        )
    return "queued", "Waiting for your platform."


def _split_decision(checked: object) -> tuple[SignalDraft | None, str | None]:
    if isinstance(checked, SignalDraft):
        return checked, None
    if checked is None:
        return None, None
    return getattr(checked, "draft", None), getattr(checked, "log_line", None)


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

    current_sl = signal.sl

    for bar in future:
        if signal.side == "buy":
            if bar.low <= current_sl:
                outcome = "breakeven" if current_sl >= signal.entry else "stopped"
                return outcome, current_sl
            if bar.high >= signal.tp:
                return "target", signal.tp
        else:
            if bar.high >= current_sl:
                outcome = "breakeven" if current_sl <= signal.entry else "stopped"
                return outcome, current_sl
            if bar.low <= signal.tp:
                return "target", signal.tp

    age = now - (signal.candle_time if signal.candle_time.tzinfo else signal.candle_time.replace(tzinfo=timezone.utc))
    if age > timedelta(hours=expiry_hours) and bars:
        return "expired", bars[-1].close
    return None


def run_scan() -> dict:
    if not _lock.acquire(blocking=False):
        log.info("Scan skipped, the previous pass is still running")
        return {"status": "busy", "message": "A scan is already running.", "signals_created": 0}
    try:
        return _run()
    finally:
        _lock.release()


def _record_failure(now: datetime, created: int) -> None:
    db = session_scope()
    try:
        db.add(
            ScanRun(
                started_at=now,
                finished_at=utcnow(),
                ok=False,
                message="The scan stopped on an unexpected error.",
                signals_created=created,
            )
        )
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


def _run() -> dict:
    cfg = get_settings()
    now = utcnow()
    created = 0
    db = session_scope()
    try:
        ids = _watched_ids(db)
    finally:
        db.close()

    # Downloads can take minutes. The database stays closed until the prices are in hand,
    # so a signup is not blocked behind the scan.
    market = get_market()
    params = params_from_settings()
    fetched = {}
    failures: list[str] = []
    log.info("Scan started for %s markets", len(ids))
    try:
        for symbol_id in ids:
            spec = get_symbol(symbol_id)
            if spec is None:
                continue
            result = market.fetch(spec)
            fetched[symbol_id] = result
            if result.bars:
                log.info(
                    "%s: %s closed 15-minute candles through %s UTC",
                    spec.display,
                    len(result.bars),
                    result.bars[-1].time.strftime("%H:%M"),
                )
            if result.error:
                failures.append(result.error)
            elif not result.bars and not result.hourly:
                failures.append(result.skip_reason or f"{spec.display}: no candles")
    except Exception:
        log.exception("scan failed")
        _record_failure(now, created)
        return {"status": "error", "message": "The scan stopped on an unexpected error.", "signals_created": created}

    db = session_scope()
    try:
        run = ScanRun(started_at=now, ok=False, message="", signals_created=0)
        db.add(run)
        db.flush()
        for symbol_id, result in fetched.items():
            price_bars = result.bars or result.hourly
            if not price_bars:
                spec = get_symbol(symbol_id)
                if spec is not None:
                    log.info("%s: check skipped, %s", spec.display, result.error or result.skip_reason or "no candles")
                continue
            last = price_bars[-1]
            row = db.get(LastPrice, symbol_id)
            if row is None:
                db.add(LastPrice(symbol_id=symbol_id, close=last.close, updated_at=now))
            else:
                row.close = last.close
                row.updated_at = now
        db.flush()

        users = db.query(User).all()
        user_settings = {s.user_id: s for s in db.query(Settings).all()}

        # Close finished ideas before counting open automatic trades, so a slot
        # that just freed can be used by a signal found in this same pass.
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
                # Telegram carries the call only. Stops, targets, and expiries stay on the desk.
                signal.close_telegram_sent = True
        db.flush()

        for symbol_id, result in fetched.items():
            spec = get_symbol(symbol_id)
            if spec is None or not result.bars:
                continue
            still = (
                db.query(Signal)
                .filter(Signal.symbol_id == symbol_id, Signal.status == "active")
                .first()
            )
            if not result.tradable:
                if still is not None and not still.telegram_sent:
                    still.telegram_sent = _announce(db, spec, still)
                log.info("%s: %s", spec.display, result.skip_reason or "no new 15-minute trade")
                continue
            checked = evaluate(
                result.bars,
                spec,
                params,
                hourly=result.hourly,
                m15=result.m15,
                m1=result.m1,
            )
            draft, note = _split_decision(checked)
            if note:
                log.info("%s", note)
            if still is not None:
                if not still.telegram_sent:
                    still.telegram_sent = _announce(db, spec, still)
                log.info("%s: not taken, this market already has an open signal", spec.display)
                continue
            if draft is None:
                continue

            recent = (
                db.query(Signal)
                .filter(Signal.symbol_id == symbol_id)
                .order_by(Signal.candle_time.desc())
                .first()
            )
            if recent is not None:
                gap = draft.candle_time - recent.candle_time
                if gap < timedelta(minutes=cfg.min_minutes_between):
                    log.info(
                        "%s: not taken, %s minutes since the last signal on this market",
                        spec.display,
                        cfg.min_minutes_between,
                    )
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
                        status, message = _delivery_status(
                            settings, spec.id, spec.mt5_only, _open_auto_count(db, user.id)
                        )
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
            log.info(
                "🎉🔥 SIGNAL CREATED for %s (%s) @ Yahoo Finance Price: %s (SL: %s, TP: %s) — Dispatched to Telegram & Copiers!",
                spec.display,
                signal.side.upper(),
                signal.entry,
                signal.sl,
                signal.tp,
            )
            created += 1

        if ids and not any(r.bars or r.hourly for r in fetched.values()):
            ok = False
            message = "No market data. " + " ".join(failures)
        else:
            ok = True
            message = f"Checked {len(ids)} markets. New signals: {created}."
            if failures:
                message += " Data failed: " + "; ".join(failures[:6])
        log.info("%s", message)
        run.ok = ok
        run.message = message[:2000]
        run.signals_created = created
        run.finished_at = utcnow()
        db.commit()
        return {"status": "ok" if ok else "degraded", "message": run.message, "signals_created": created}
    except Exception:
        log.exception("scan failed")
        db.rollback()
        db.close()
        _record_failure(now, created)
        return {"status": "error", "message": "The scan stopped on an unexpected error.", "signals_created": created}
    finally:
        db.close()
