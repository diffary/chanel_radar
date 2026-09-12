"""Shared test setup.

DATABASE_URL is forced to an in-memory SQLite BEFORE the app is imported,
so no test ever needs Postgres or the network.
"""
import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app  # noqa: E402  (must come after the env override)


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
