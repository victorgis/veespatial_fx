from app.database import normalize_db_url, postgres_connect_args


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
