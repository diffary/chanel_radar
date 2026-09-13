"""Collector tests: no network, no HTML. The scraper is replaced by a fake
`async def` that returns a ready-made payload dict, injected through the
`scrape=` parameter of the collector functions.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.collector import collect_all_active, collect_channel
from app.db import Base
from app.models import Channel, ChannelMetricSnapshot, Post, PostMetricSnapshot
from app.scraper import ChannelNotFound

UTC = timezone.utc


@pytest.fixture
async def session():
    """Fresh in-memory SQLite per test.

    We build a brand-new engine here instead of reusing app.db.engine so every
    test starts from empty tables and nothing leaks between tests. The engine
    is disposed at teardown, which throws the in-memory database away.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


def make_post(message_id: int, views: int, reactions: int, text: str | None = None) -> dict:
    return {
        "message_id": message_id,
        "text": text or f"post {message_id}",
        "posted_at": datetime(2026, 9, 1, 12, 0, tzinfo=UTC) + timedelta(minutes=message_id),
        "views": views,
        "reactions": reactions,
        "link": f"https://t.me/testchan/{message_id}",
    }


@pytest.fixture
def payload() -> dict:
    return {
        "title": "Test Channel",
        "subscribers": 1000,
        "posts": [make_post(10, views=100, reactions=5), make_post(11, views=200, reactions=6)],
    }


def fake_scrape_returning(payload: dict):
    async def fake_scrape(username: str) -> dict:
        return payload

    return fake_scrape


async def count(session, model) -> int:
    return len((await session.execute(select(model))).scalars().all())


# --- 1. first run ---------------------------------------------------------------


async def test_first_run_creates_channel_posts_and_snapshots(session, payload):
    channel = await collect_channel(session, "@testchan", scrape=fake_scrape_returning(payload))

    assert channel.username == "testchan"
    assert channel.status == "active"
    assert channel.title == "Test Channel"
    assert channel.subscribers == 1000
    assert channel.last_collected_at is not None
    assert channel.error_reason is None

    assert await count(session, Channel) == 1
    assert await count(session, Post) == 2
    assert await count(session, PostMetricSnapshot) == 2
    assert await count(session, ChannelMetricSnapshot) == 1

    snap = (await session.execute(select(ChannelMetricSnapshot))).scalar_one()
    assert snap.subscribers == 1000
    assert snap.post_count == 2


# --- 2. idempotency ---------------------------------------------------------------


async def test_second_run_same_payload_creates_no_duplicate_posts(session, payload):
    scrape = fake_scrape_returning(payload)
    await collect_channel(session, "testchan", scrape=scrape)
    await collect_channel(session, "testchan", scrape=scrape)

    assert await count(session, Channel) == 1
    assert await count(session, Post) == 2
    assert await count(session, PostMetricSnapshot) == 4  # 2 posts x 2 runs
    assert await count(session, ChannelMetricSnapshot) == 2  # 1 per run


# --- 3. changed payload -----------------------------------------------------------


async def test_second_run_with_changed_payload_updates_metrics_and_adds_post(session, payload):
    await collect_channel(session, "testchan", scrape=fake_scrape_returning(payload))
    post10_before = (
        await session.execute(select(Post).where(Post.message_id == 10))
    ).scalar_one()
    first_seen_before = post10_before.first_seen_at
    text_before = post10_before.text

    changed = {
        "title": "Test Channel",
        "subscribers": 1100,
        "posts": [
            make_post(10, views=100, reactions=5),
            make_post(11, views=250, reactions=6),
            make_post(12, views=10, reactions=0),
        ],
    }
    await collect_channel(session, "testchan", scrape=fake_scrape_returning(changed))

    assert await count(session, Post) == 3

    post11 = (await session.execute(select(Post).where(Post.message_id == 11))).scalar_one()
    snaps = (
        await session.execute(
            select(PostMetricSnapshot)
            .where(PostMetricSnapshot.post_id == post11.id)
            .order_by(PostMetricSnapshot.id)
        )
    ).scalars().all()
    assert [s.views for s in snaps] == [200, 250]

    post10 = (await session.execute(select(Post).where(Post.message_id == 10))).scalar_one()
    assert post10.text == text_before
    assert post10.first_seen_at == first_seen_before

    last_channel_snap = (
        await session.execute(
            select(ChannelMetricSnapshot).order_by(ChannelMetricSnapshot.id.desc())
        )
    ).scalars().first()
    assert last_channel_snap.subscribers == 1100
    assert last_channel_snap.post_count == 3


# --- 4. scrape error --------------------------------------------------------------


async def test_scrape_error_marks_channel_error_without_raising(session):
    async def failing_scrape(username: str) -> dict:
        raise ChannelNotFound("nope")

    channel = await collect_channel(session, "testchan", scrape=failing_scrape)

    assert channel.status == "error"
    assert "nope" in channel.error_reason
    assert channel.last_collected_at is None
    assert await count(session, Post) == 0
    assert await count(session, ChannelMetricSnapshot) == 0


# --- 5. recovery from error -------------------------------------------------------


async def test_channel_recovers_from_error_on_successful_scrape(session, payload):
    async def failing_scrape(username: str) -> dict:
        raise ChannelNotFound("nope")

    await collect_channel(session, "testchan", scrape=failing_scrape)
    channel = await collect_channel(session, "testchan", scrape=fake_scrape_returning(payload))

    assert channel.status == "active"
    assert channel.error_reason is None
    assert await count(session, Channel) == 1
    assert await count(session, Post) == 2


# --- 6. collect_all_active --------------------------------------------------------


async def test_collect_all_active_skips_error_channels(session, payload):
    session.add_all(
        [
            Channel(username="pending_one", status="pending"),
            Channel(username="active_one", status="active"),
            Channel(username="broken_one", status="error", error_reason="old failure"),
        ]
    )
    await session.commit()

    called: list[str] = []

    async def recording_scrape(username: str) -> dict:
        called.append(username)
        return payload

    collected = await collect_all_active(session, scrape=recording_scrape)

    assert sorted(called) == ["active_one", "pending_one"]
    assert sorted(c.username for c in collected) == ["active_one", "pending_one"]
    assert all(c.status == "active" for c in collected)


# --- 7. the DB enforces the natural key -------------------------------------------


async def test_unique_constraint_on_channel_and_message_id(session):
    channel = Channel(username="testchan")
    session.add(channel)
    await session.flush()

    posted_at = datetime(2026, 9, 1, tzinfo=UTC)
    session.add(Post(channel_id=channel.id, message_id=1, text="a", posted_at=posted_at, link="l"))
    await session.flush()

    session.add(Post(channel_id=channel.id, message_id=1, text="b", posted_at=posted_at, link="l"))
    with pytest.raises(IntegrityError):
        await session.flush()
    await session.rollback()
