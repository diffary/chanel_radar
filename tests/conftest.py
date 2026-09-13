"""Shared test setup.

DATABASE_URL is forced to an in-memory SQLite BEFORE the app is imported,
so no test ever needs Postgres or the network.
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
from sqlalchemy import delete
from httpx import ASGITransport, AsyncClient

from app.db import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402  (must come after the env override)
from app.models import Channel  # noqa: E402


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


@pytest.fixture(autouse=True)
async def clean_channels(client):
    """The app's in-memory SQLite lives for the whole pytest process (StaticPool,
    one shared connection), so rows added by one test would leak into the next.
    Wipe the channels table before every test. Depends on `client` so the
    lifespan has already run create_all. API tests create no posts/snapshots,
    so deleting channels alone is enough.
    """
    async with SessionLocal() as session:
        await session.execute(delete(Channel))
        await session.commit()
