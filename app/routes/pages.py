"""HTML pages. Thin layer: load rows, render templates, redirect."""
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Channel
from app.routes import channels

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/")
async def index(request: Request, session: AsyncSession = Depends(get_session)):
    rows = (
        await session.execute(select(Channel).order_by(Channel.added_at.desc()))
    ).scalars().all()
    return templates.TemplateResponse(
        request,
        "index.html",
        {"channels": rows, "error": request.query_params.get("error")},
    )


@router.post("/add")
async def add_from_form(
    background_tasks: BackgroundTasks,
    username: str = Form(...),
    session: AsyncSession = Depends(get_session),
):
    """HTML form target. Same logic as POST /channels, but answers with a redirect
    (303 = "now GET this URL") so a browser refresh does not re-submit the form."""
    try:
        await channels.add_channel(session, username, background_tasks)
    except ValueError as e:
        return RedirectResponse("/?" + urlencode({"error": str(e)}), status_code=303)
    return RedirectResponse("/", status_code=303)
