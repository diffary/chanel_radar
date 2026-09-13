"""SQLAlchemy models. Tables only, no business logic."""
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    """Default for timestamp columns: tz-aware 'now' in UTC."""
    return datetime.now(timezone.utc)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subscribers: Mapped[int] = mapped_column(Integer, default=0)
    # pending -> never collected yet; active -> last run ok; error -> last run failed
    status: Mapped[str] = mapped_column(String(16), default="pending")
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    posts: Mapped[list["Post"]] = relationship(back_populates="channel")


class Post(Base):
    __tablename__ = "posts"
    # Idempotency key: a Telegram message is unique per channel by its message_id.
    __table_args__ = (UniqueConstraint("channel_id", "message_id", name="uq_post_channel_message"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    message_id: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    link: Mapped[str] = mapped_column(String(255))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    channel: Mapped["Channel"] = relationship(back_populates="posts")
    snapshots: Mapped[list["PostMetricSnapshot"]] = relationship(back_populates="post")


class PostMetricSnapshot(Base):
    """One row per post per collection run -> metric dynamics over time."""

    __tablename__ = "post_metric_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    views: Mapped[int] = mapped_column(Integer)
    reactions: Mapped[int] = mapped_column(Integer)

    post: Mapped["Post"] = relationship(back_populates="snapshots")


class ChannelMetricSnapshot(Base):
    """One row per channel per collection run."""

    __tablename__ = "channel_metric_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    subscribers: Mapped[int] = mapped_column(Integer)
    post_count: Mapped[int] = mapped_column(Integer)
