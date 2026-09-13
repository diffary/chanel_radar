"""Pydantic request/response shapes. I/O only, no logic."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ChannelCreate(BaseModel):
    # raw user input: '@durov', 't.me/durov', 'durov' -- normalized in the route
    username: str = Field(min_length=1)


class ChannelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    title: str | None
    subscribers: int
    status: str
    error_reason: str | None
    last_collected_at: datetime | None
