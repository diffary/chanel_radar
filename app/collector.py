"""Collection run: scrape a channel and store the result idempotently.

The scraper is passed in as `scrape=` so tests can inject a fake that returns
a payload dict; the default is the real `app.scraper.scrape`.
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import scraper
from app.models import Channel, ChannelMetricSnapshot, Post, PostMetricSnapshot, utcnow
from app.scraper import ScrapeError


async def get_or_create_channel(session: AsyncSession, username: str) -> Channel:
    """Find the channel row by username or create it with status 'pending'."""
    channel = (
        await session.execute(select(Channel).where(Channel.username == username))
    ).scalar_one_or_none()
    if channel is None:
        channel = Channel(username=username, status="pending")
        session.add(channel)
        await session.flush()  # assigns channel.id so posts can reference it
    return channel


async def upsert_posts(session: AsyncSession, channel: Channel, posts: list[dict]) -> None:
    """Insert new posts, refresh text/link of known ones, snapshot metrics for all."""
    for data in posts:
        post = (
            await session.execute(
                select(Post).where(
                    Post.channel_id == channel.id, Post.message_id == data["message_id"]
                )
            )
        ).scalar_one_or_none()
        if post is None:
            post = Post(
                channel_id=channel.id,
                message_id=data["message_id"],
                text=data["text"],
                posted_at=data["posted_at"],
                link=data["link"],
            )
            session.add(post)
            await session.flush()  # assigns post.id for the snapshot
        else:
            post.text = data["text"]
            post.link = data["link"]
        session.add(PostMetricSnapshot(post_id=post.id, views=data["views"], reactions=data["reactions"]))


async def count_posts(session: AsyncSession, channel: Channel) -> int:
    return (
        await session.execute(select(func.count(Post.id)).where(Post.channel_id == channel.id))
    ).scalar_one()


async def collect_channel(session: AsyncSession, username: str, scrape=scraper.scrape) -> Channel:
    """Run one collection for a channel. Never raises on scrape failure:
    the failure is recorded on the channel row (status='error') instead."""
    username = scraper.normalize_username(username)
    channel = await get_or_create_channel(session, username)

    try:
        payload = await scrape(username)
    except ScrapeError as e:
        channel.status = "error"
        channel.error_reason = str(e)
        await session.commit()
        return channel

    await upsert_posts(session, channel, payload["posts"])
    session.add(
        ChannelMetricSnapshot(
            channel_id=channel.id,
            subscribers=payload["subscribers"],
            post_count=await count_posts(session, channel),
        )
    )

    channel.title = payload["title"]
    channel.subscribers = payload["subscribers"]
    channel.status = "active"
    channel.error_reason = None
    channel.last_collected_at = utcnow()
    await session.commit()
    return channel


async def collect_all_active(session: AsyncSession, scrape=scraper.scrape) -> list[Channel]:
    """Collect every pending/active channel one after another. Error channels are skipped."""
    channels = (
        await session.execute(select(Channel).where(Channel.status.in_(("active", "pending"))))
    ).scalars().all()
    return [await collect_channel(session, c.username, scrape=scrape) for c in channels]
