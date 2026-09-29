"""Runtime settings. Environment variables override the defaults."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        extra="ignore",
    )

    app_name: str = "Signal Desk"
    # Dev default is obvious and refused in production by the startup check when
    # it is still this value and ENV is production.
    jwt_secret: str = "dev-only-change-me"
    env: str = "development"
    database_url: str = "sqlite:///./data/app.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    scheduler_enabled: bool = True
    # A closed 5-minute candle should be seen within a minute.
    scan_interval_seconds: int = 60
    signal_expiry_hours: int = 6
    # Kept so an old environment variable does not crash. The scan uses minutes.
    min_hours_between: int = 6
    min_minutes_between: int = 15
    telegram_bot_token: str = ""
    telegram_channel_id: str = ""
    cron_key: str = ""
    massive_api_key: str = ""
    static_dir: str = ""
    experts_dir: str = ""
    # Reference used only in the shared Telegram post. Each account is sized
    # from its own balance on the dashboard and in the copier.
    telegram_reference_balance: float = 1000.0
    telegram_reference_risk: float = 1.0

    ema_fast: int = 20
    ema_slow: int = 50
    ema_trend: int = 200
    rsi_period: int = 14
    atr_period: int = 14
    sl_atr: float = 1.5
    tp_atr: float = 3.0

    @property
    def cors_origin_list(self) -> list[str]:
        return [p.strip() for p in self.cors_origins.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
