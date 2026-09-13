"""JSON API for channels. Thin layer: validate input, call collector, return schemas."""
import logging
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app import collector, scraper
from app.db import SessionLocal, get_session
from app.models import Channel, utcnow
from app.schemas import ChannelCreate, ChannelOut

log = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["channels"])

RECOLLECT_AFTER = timedelta(seconds=60)


async def run_collection(username: str) -> None:
    """Background task: collect one channel.

    Runs after the response is sent, when the request's session is already
    closed, so it must open its own session. A background task must never
    crash the server: every error is logged and swallowed (collect_channel
    itself already records scrape failures on the channel row).
    """
    try:
        async with SessionLocal() as session:
            await collector.collect_channel(session, username)
    except Exception:
        log.exception("background collection failed for %r", username)


async def add_channel(
    session: AsyncSession, raw_username: str, background_tasks: BackgroundTasks
) -> tuple[Channel, bool]:
    """Shared by the JSON route and the HTML form route.

    Returns (channel, created). Raises ValueError on an invalid username.
    """
    username = scraper.normalize_username(raw_username)
    channel = (
        await session.execute(select(Channel).where(Channel.username == username))
    ).scalar_one_or_none()
    created = channel is None
    if created:
        channel = await collector.get_or_create_channel(session, username)
        try:
            await session.commit()
        except IntegrityError:
            # someone else inserted the same username first: use their row
            await session.rollback()
            channel = (
                await session.execute(select(Channel).where(Channel.username == username))
            ).scalar_one()
            created = False
    # Re-adding refreshes the channel, but not more than once a minute.
    # Time-based rather than status-based so a row stuck in "pending" can be
    # un-stuck by simply adding it again.
    if channel.last_collected_at is None or utcnow() - channel.last_collected_at > RECOLLECT_AFTER:
        # `run_collection` is looked up on this module at call time, so tests can patch it
        background_tasks.add_task(run_collection, username)
    return channel, created


@router.post("", response_model=ChannelOut)
async def create_channel(
    body: ChannelCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    try:
        channel, created = await add_channel(session, body.username, background_tasks)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    response.status_code = 201 if created else 200
    return channel


@router.get("", response_model=list[ChannelOut])
async def list_channels(session: AsyncSession = Depends(get_session)):
    return (
        await session.execute(select(Channel).order_by(Channel.added_at.desc()))
    ).scalars().all()


@router.get("/{username}", response_model=ChannelOut)
async def get_channel(username: str, session: AsyncSession = Depends(get_session)):
    channel = (
        await session.execute(select(Channel).where(Channel.username == username))
    ).scalar_one_or_none()
    if channel is None:
        raise HTTPException(status_code=404, detail="channel not found")
    return channel
