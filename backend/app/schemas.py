"""JSON shapes the website consumes."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    email: str
    name: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    token: str
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    email: str
    name: str
    is_admin: bool


class SettingsIn(BaseModel):
    trade_mode: str
    account_type: str
    platform: str
    risk_percent: float
    max_lot: float
    planning_balance: float
    enabled_symbols: list[str]
    alias_overrides: str = ""
    onboarding_done: bool
    risk_accepted: bool
    trust_platform_size: bool = False
    max_open_trades: int = 3


class SettingsOut(BaseModel):
    trade_mode: str
    account_type: str
    platform: str
    risk_percent: float
    max_lot: float
    planning_balance: float
    enabled_symbols: list[str]
    alias_overrides: str
    onboarding_done: bool
    risk_accepted: bool
    trust_platform_size: bool
    max_open_trades: int
    ea_key_prefix: str | None


class SettingsSaved(BaseModel):
    settings: SettingsOut
    ea_key: str | None = None


class KeyOut(BaseModel):
    ea_key: str
    ea_key_prefix: str


class ConnectionOut(BaseModel):
    online: bool
    last_seen: datetime | None
    broker: str | None
    account_login: str | None
    balance: float | None
    equity: float | None
    currency: str
    ea_platform: str | None
    fx_symbol: str | None
    fx_contract: float | None
    detected_account_type: str | None
    mismatch: bool
    mismatch_message: str | None


class MeOut(BaseModel):
    user: UserOut
    settings: SettingsOut
    connection: ConnectionOut
    telegram_configured: bool
    telegram_error: str = ""
    status_line: str
    watchlist: list[str]


class QuoteOut(BaseModel):
    lots: float | None
    units: float | None
    unit: str
    risk_cash: float
    currency: str
    min_lot: float
    too_small: bool
    reason: str | None
    approximate: bool
    standard_lots: float | None
    micro_lots: float | None
    scales_with_account: bool
    uses_live_contract: bool
    contract_size: float | None
    balance_source: str
    balance: float
    blocked: bool


class SignalOut(BaseModel):
    id: int
    symbol_id: str
    display: str
    pair: str
    group: str
    digits: int
    unit: str
    mt5_only: bool
    note: str
    side: str
    entry: float
    sl: float
    tp: float
    rsi: float
    status: str
    rationale: str
    source: str
    created_at: datetime
    closed_at: datetime | None
    close_price: float | None
    delivery_id: int | None
    delivery_status: str | None
    delivery_message: str | None
    ticket: str | None
    fill_price: float | None
    placed_lots: float | None
    broker_symbol: str | None
    quote: QuoteOut | None
    copy_text: str


class ScanOut(BaseModel):
    started_at: datetime | None
    finished_at: datetime | None
    ok: bool | None
    message: str
    signals_created: int


class DashboardOut(BaseModel):
    me: MeOut
    scan: ScanOut
    signals: list[SignalOut]
    recent: list[SignalOut]


class MarkIn(BaseModel):
    action: str = Field(description="you_placed or you_skipped")


class MarketOut(BaseModel):
    id: str
    display: str
    pair: str
    group: str
    mt5_only: bool
    aliases: list[str]
    scales_with_account: bool
    unit: str
    note: str
    contract_standard: float
    contract_micro: float


class WatchlistIn(BaseModel):
    enabled_symbols: list[str]


class ScanResultOut(BaseModel):
    status: str
    message: str
    signals_created: int
