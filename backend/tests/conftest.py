import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    dbfile = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile}")
    monkeypatch.setenv("JWT_SECRET", "test-secret-test-secret")
    monkeypatch.setenv("SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "")
    monkeypatch.setenv("CRON_KEY", "")
    from app.config import get_settings
    from app.database import reset_engine
    from app.market import set_market_override

    get_settings.cache_clear()
    reset_engine()
    set_market_override(None)
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
    set_market_override(None)
    reset_engine()
    get_settings.cache_clear()
