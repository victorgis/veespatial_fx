from sqlalchemy import inspect, text

from app.database import get_engine, normalize_db_url, postgres_connect_args, reset_engine


def test_neon_pooler_url_keeps_ssl_and_disables_prepared_statements():
    raw = (
        "postgresql://user:secret@ep-example-pooler.c-6.us-east-2.aws.neon.tech/"
        "neondb?sslmode=require&channel_binding=require"
    )
    url = normalize_db_url(raw)
    assert url.startswith("postgresql+psycopg://")
    assert "sslmode=require" in url
    assert "channel_binding=require" in url
    assert postgres_connect_args(url) == {"prepare_threshold": None}


def test_direct_postgres_keeps_prepared_statements():
    url = normalize_db_url("postgres://user:secret@localhost:5432/signaldesk")
    assert url.startswith("postgresql+psycopg://")
    assert postgres_connect_args(url) == {}


def test_existing_settings_table_gains_the_open_trade_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'old.db'}")
    from app.config import get_settings
    from app.database import _ensure_max_open_trades

    get_settings.cache_clear()
    reset_engine()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE settings (user_id INTEGER PRIMARY KEY, trade_mode VARCHAR(16))"))
    _ensure_max_open_trades()
    columns = {column["name"] for column in inspect(engine).get_columns("settings")}
    assert "max_open_trades" in columns
    reset_engine()
    get_settings.cache_clear()
