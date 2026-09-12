from app.db import make_engine_url


def test_neon_url_is_converted_for_asyncpg():
    raw = "postgresql://user:pw@host.neon.tech/db?sslmode=require&channel_binding=require"
    url, connect_args = make_engine_url(raw)
    assert url.drivername == "postgresql+asyncpg"
    assert "sslmode" not in url.query
    assert "channel_binding" not in url.query
    assert connect_args == {"ssl": "require"}
    assert url.host == "host.neon.tech"
    assert url.username == "user"
    assert url.database == "db"


def test_quoted_url_is_accepted():
    url, _ = make_engine_url('"postgresql://user:pw@host/db?sslmode=require"')
    assert url.drivername == "postgresql+asyncpg"
    assert url.host == "host"
    assert "sslmode" not in url.query


def test_asyncpg_url_stays_asyncpg():
    url, connect_args = make_engine_url("postgresql+asyncpg://user:pw@host/db")
    assert url.drivername == "postgresql+asyncpg"
    assert connect_args == {"ssl": "require"}


def test_sqlite_url_untouched():
    raw = "sqlite+aiosqlite:///:memory:"
    url, connect_args = make_engine_url(raw)
    assert str(url) == raw
    assert connect_args == {}


def test_required_ssl_flag():
    url, connect_args = make_engine_url("postgresql://user:pw@host/db?sslmode=require", required_ssl=False)
    assert url.drivername == "postgresql+asyncpg"
    assert connect_args == {}