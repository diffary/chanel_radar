"""Async SQLAlchemy engine, session factory, declarative base and FastAPI dependency."""
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


def make_engine_url(raw: str) -> tuple[URL, dict]:
    """Turn the DATABASE_URL from env into (url, connect_args) for create_async_engine.

    Neon hands out `postgresql://...?sslmode=require&channel_binding=require`;
    asyncpg rejects those query params, so we strip them and pass ssl via connect_args.
    Non-Postgres URLs (sqlite in tests) are returned unchanged.
    """
    url = make_url(raw)
    if not url.drivername.startswith("postgresql"):
        return url, {}
    query = {k: v for k, v in url.query.items() if k not in ("sslmode", "channel_binding")}
    url = url.set(drivername="postgresql+asyncpg", query=query)
    return url, {"ssl": "require"}


_url, _connect_args = make_engine_url(settings.DATABASE_URL)
engine = create_async_engine(_url, connect_args=_connect_args, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    """Create tables on startup. Deliberate simplification instead of migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session():
    """FastAPI dependency: one session per request."""
    async with SessionLocal() as session:
        yield session
