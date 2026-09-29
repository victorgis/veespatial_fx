"""Tables. Timestamps are stored in UTC."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, DateTime

from app.database import Base
from app.symbols import ALL_IDS


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(80))
    password_hash: Mapped[str] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Settings(Base):
    __tablename__ = "settings"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    trade_mode: Mapped[str] = mapped_column(String(16), default="manual")
    account_type: Mapped[str] = mapped_column(String(16), default="standard")
    platform: Mapped[str] = mapped_column(String(16), default="mt5")
    risk_percent: Mapped[float] = mapped_column(Float, default=0.5)
    max_lot: Mapped[float] = mapped_column(Float, default=0.5)
    planning_balance: Mapped[float] = mapped_column(Float, default=1000)
    enabled_symbols: Mapped[str] = mapped_column(Text, default=",".join(ALL_IDS))
    alias_overrides: Mapped[str] = mapped_column(Text, default="")
    onboarding_done: Mapped[bool] = mapped_column(Boolean, default=False)
    risk_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    trust_platform_size: Mapped[bool] = mapped_column(Boolean, default=False)
    ea_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    ea_key_prefix: Mapped[str | None] = mapped_column(String(16), nullable=True)
    balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    equity: Mapped[float | None] = mapped_column(Float, nullable=True)
    account_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    broker: Mapped[str | None] = mapped_column(String(80), nullable=True)
    account_login: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ea_platform: Mapped[str | None] = mapped_column(String(16), nullable=True)
    ea_last_seen: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fx_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fx_contract: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_ea_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class BotConfig(Base):
    __tablename__ = "bot_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled_symbols: Mapped[str] = mapped_column(Text, default=",".join(ALL_IDS))


class LastPrice(Base):
    __tablename__ = "last_prices"

    symbol_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    close: Mapped[float] = mapped_column(Float)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class BrokerSpec(Base):
    __tablename__ = "broker_specs"
    __table_args__ = (UniqueConstraint("user_id", "broker_symbol"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    broker_symbol: Mapped[str] = mapped_column(String(32))
    contract_size: Mapped[float] = mapped_column(Float)
    tick_size: Mapped[float] = mapped_column(Float)
    tick_value: Mapped[float] = mapped_column(Float)
    min_lot: Mapped[float] = mapped_column(Float)
    max_lot: Mapped[float] = mapped_column(Float)
    lot_step: Mapped[float] = mapped_column(Float)
    digits: Mapped[int] = mapped_column(Integer)
    bid: Mapped[float] = mapped_column(Float, default=0)
    ask: Mapped[float] = mapped_column(Float, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Signal(Base):
    __tablename__ = "signals"
    __table_args__ = (UniqueConstraint("symbol_id", "candle_time"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[str] = mapped_column(String(16), index=True)
    side: Mapped[str] = mapped_column(String(8))
    entry: Mapped[float] = mapped_column(Float)
    sl: Mapped[float] = mapped_column(Float)
    tp: Mapped[float] = mapped_column(Float)
    atr: Mapped[float] = mapped_column(Float)
    rsi: Mapped[float] = mapped_column(Float)
    candle_time: Mapped[datetime] = mapped_column(UTCDateTime)
    source: Mapped[str] = mapped_column(String(80), default="")
    rationale: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="active", index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    close_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    telegram_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    close_telegram_sent: Mapped[bool] = mapped_column(Boolean, default=False)


class Delivery(Base):
    __tablename__ = "deliveries"
    __table_args__ = (UniqueConstraint("signal_id", "user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    signal_id: Mapped[int] = mapped_column(ForeignKey("signals.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(24), default="for_you")
    message: Mapped[str] = mapped_column(Text, default="")
    ticket: Mapped[str | None] = mapped_column(String(32), nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    placed_lots: Mapped[float | None] = mapped_column(Float, nullable=True)
    broker_symbol: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ScanRun(Base):
    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    ok: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str] = mapped_column(Text, default="")
    signals_created: Mapped[int] = mapped_column(Integer, default=0)


def ensure_bot_config(db) -> BotConfig:  # type: ignore[no-untyped-def]
    row = db.get(BotConfig, 1)
    if row is None:
        row = BotConfig(id=1, enabled_symbols=",".join(ALL_IDS))
        db.add(row)
        db.flush()
    return row


def new_settings(user_id: int) -> Settings:
    return Settings(
        user_id=user_id,
        trade_mode="manual",
        account_type="standard",
        platform="mt5",
        risk_percent=0.5,
        max_lot=0.5,
        planning_balance=1000,
        enabled_symbols=",".join(ALL_IDS),
        alias_overrides="",
        onboarding_done=False,
        risk_accepted=False,
        trust_platform_size=False,
    )
