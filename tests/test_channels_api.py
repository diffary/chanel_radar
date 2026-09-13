"""API + form tests for adding channels. No network: the background collection
runner `app.routes.channels.run_collection` is monkeypatched with a fake that
only records which username it was asked to collect.
"""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import Channel, utcnow
from app.routes import channels


@pytest.fixture
def collected(monkeypatch) -> list[str]:
    """Replace the real background runner with a fake that records usernames.
    `add_task(run_collection, ...)` looks the name up on the module at request
    time, so patching the module attribute is enough."""
    calls: list[str] = []

    async def fake_run_collection(username: str) -> None:
        calls.append(username)

    monkeypatch.setattr(channels, "run_collection", fake_run_collection)
    return calls


async def test_post_valid_creates_pending_channel(client, collected):
    r = await client.post("/channels", json={"username": "@durov"})
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "durov"
    assert body["status"] == "pending"
    assert collected == ["durov"]


async def test_post_same_channel_twice_is_idempotent(client, collected):
    first = await client.post("/channels", json={"username": "durov"})
    second = await client.post("/channels", json={"username": "https://t.me/durov"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]

    r = await client.get("/channels")
    assert r.status_code == 200
    usernames = [c["username"] for c in r.json()]
    assert usernames == ["durov"]
    # collection is (re)scheduled on every add, so the user gets fresh data
    assert collected == ["durov", "durov"]


async def test_post_invalid_username_returns_422(client, collected):
    r = await client.post("/channels", json={"username": "bad name!"})
    assert r.status_code == 422
    assert "invalid channel username" in r.json()["detail"]
    assert collected == []


async def test_get_unknown_channel_returns_404(client, collected):
    r = await client.get("/channels/unknown_xyz")
    assert r.status_code == 404


async def test_form_add_redirects_and_shows_pending_row(client, collected):
    r = await client.post("/add", data={"username": "t.me/telegram"})
    assert r.status_code == 303
    assert r.headers["location"] == "/"
    assert collected == ["telegram"]

    page = await client.get("/")
    assert page.status_code == 200
    assert "telegram" in page.text
    assert "collecting" in page.text


async def test_form_invalid_redirects_with_error_message(client, collected):
    r = await client.post("/add", data={"username": "bad name!"})
    assert r.status_code == 303
    location = r.headers["location"]
    assert location.startswith("/?error=")
    assert collected == []

    page = await client.get(location)
    assert page.status_code == 200
    assert "invalid channel username" in page.text


async def test_run_collection_swallows_exceptions(monkeypatch):
    async def exploding_collect_channel(session, username):
        raise RuntimeError("boom")

    monkeypatch.setattr(channels.collector, "collect_channel", exploding_collect_channel)
    await channels.run_collection("durov")  # must not raise


async def test_post_lost_insert_race_returns_existing_row(client, collected, monkeypatch):
    """Two first-time adds racing: the other request inserts the row between our
    select and our commit. Simulated by a fake get_or_create_channel that commits
    the row through its own session and hands back a second, unsaved copy."""

    async def racing_get_or_create(session, username):
        async with SessionLocal() as other:
            other.add(Channel(username=username, status="pending"))
            await other.commit()
        duplicate = Channel(username=username, status="pending")
        session.add(duplicate)
        return duplicate

    monkeypatch.setattr(channels.collector, "get_or_create_channel", racing_get_or_create)

    r = await client.post("/channels", json={"username": "racechan"})
    assert r.status_code == 200
    assert r.json()["username"] == "racechan"
    async with SessionLocal() as session:
        rows = (await session.execute(select(Channel).where(Channel.username == "racechan"))).scalars().all()
    assert len(rows) == 1
    assert r.json()["id"] == rows[0].id


async def set_last_collected(username: str, when) -> None:
    async with SessionLocal() as session:
        channel = (await session.execute(select(Channel).where(Channel.username == username))).scalar_one()
        channel.last_collected_at = when
        await session.commit()


async def test_recent_channel_is_not_recollected(client, collected):
    await client.post("/channels", json={"username": "durov"})
    await set_last_collected("durov", utcnow())
    collected.clear()

    r = await client.post("/channels", json={"username": "durov"})
    assert r.status_code == 200
    assert collected == []


async def test_stale_channel_is_recollected(client, collected):
    await client.post("/channels", json={"username": "durov"})
    await set_last_collected("durov", utcnow() - timedelta(minutes=5))
    collected.clear()

    r = await client.post("/channels", json={"username": "durov"})
    assert r.status_code == 200
    assert collected == ["durov"]
