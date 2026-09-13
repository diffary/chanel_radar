"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  register tables with Base.metadata
from app.db import init_db
from app.routes import channels, pages


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="channel-radar", lifespan=lifespan)
app.include_router(pages.router)
app.include_router(channels.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
