"""HTML pages. Thin layer: render templates only."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")
