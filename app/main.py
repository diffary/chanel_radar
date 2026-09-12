"""FastAPI application entry point."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db
from app.routes import pages


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="channel-radar", lifespan=lifespan)
app.include_router(pages.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
