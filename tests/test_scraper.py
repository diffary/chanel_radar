"""Scraper tests. Everything runs on saved HTML fixtures — no network."""
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app import scraper
from app.scraper import ChannelNotFound, ChannelUnavailable

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / f"{name}.html").read_text(encoding="utf-8")


# --- parse_count -------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("18.8M", 18_800_000),
        ("9.54M", 9_540_000),
        ("585K", 585_000),
        ("7.61K", 7_610),
        ("102", 102),
        ("1 234", 1234),
        ("1,234", 1234),
        ("", 0),
        (None, 0),
    ],
)
def test_parse_count(text, expected):
    assert scraper.parse_count(text) == expected


# --- normalize_username ------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("durov", "durov"),
        ("@durov", "durov"),
        ("  durov  ", "durov"),
        ("https://t.me/durov", "durov"),
        ("http://t.me/durov", "durov"),
        ("t.me/durov", "durov"),
        ("https://t.me/s/durov", "durov"),
        ("t.me/s/durov/", "durov"),
    ],
)
def test_normalize_username(raw, expected):
    assert scraper.normalize_username(raw) == expected


# --- parse_channel -----------------------------------------------------------


def test_parse_durov_channel_header():
    result = scraper.parse_channel(load_fixture("durov"))

    assert result["title"] == "Pavel Durov"
    assert result["subscribers"] == 10_800_000
    assert len(result["posts"]) == 20


def test_parse_durov_first_post():
    result = scraper.parse_channel(load_fixture("durov"))
    post = result["posts"][0]

    assert post["message_id"] == 528
    assert post["views"] == 18_800_000
    assert post["posted_at"] == datetime(2026, 6, 15, 18, 58, 13, tzinfo=timezone.utc)
    assert post["link"] == "https://t.me/durov/528"
    assert post["text"].startswith("⛔️ The UK government wants to ban")
    # 14.3K (paid stars) + 132K + 39.8K + 24.7K + 22.1K + 754
    assert post["reactions"] == 233_654


def test_parse_durov_posts_sorted_by_message_id():
    result = scraper.parse_channel(load_fixture("durov"))
    ids = [post["message_id"] for post in result["posts"]]

    assert ids == sorted(ids)
    assert ids[-1] == 548


def test_parse_xydessa_channel():
    result = scraper.parse_channel(load_fixture("xydessa_live"))

    assert result["title"] == "XYDESSA LIVE"
    assert result["subscribers"] == 585_000
    assert len(result["posts"]) == 18


def test_parse_xydessa_media_only_post_has_empty_text():
    result = scraper.parse_channel(load_fixture("xydessa_live"))
    post = result["posts"][0]

    assert post["message_id"] == 85856
    assert post["text"] == ""
    assert post["views"] == 83_800
    assert post["reactions"] == 190 + 87 + 23 + 7 + 3
    assert post["link"] == "https://t.me/xydessa_live/85856"


def test_parse_not_found_raises_channel_not_found():
    with pytest.raises(ChannelNotFound):
        scraper.parse_channel(load_fixture("not_found"))


def test_parse_channel_with_no_posts_raises_unavailable():
    html = (
        '<html><body><div class="tgme_channel_info">'
        '<div class="tgme_channel_info_header_title">Empty</div>'
        "</div></body></html>"
    )
    with pytest.raises(ChannelUnavailable):
        scraper.parse_channel(html)


# --- fetch (mocked transport, no network) -----------------------------------


async def test_fetch_redirect_off_telegram_raises_not_found():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "t.me":
            return httpx.Response(302, headers={"location": "https://telegram.org/"})
        return httpx.Response(200, text="<html><title>Telegram Messenger</title></html>")

    transport = httpx.MockTransport(handler)
    with pytest.raises(ChannelNotFound):
        await scraper.fetch("nope_nope_nope", transport=transport)


async def test_fetch_non_200_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    transport = httpx.MockTransport(handler)
    with pytest.raises(ChannelUnavailable):
        await scraper.fetch("durov", transport=transport)


async def test_fetch_returns_body_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://t.me/s/durov"
        return httpx.Response(200, text="<html>ok</html>")

    transport = httpx.MockTransport(handler)
    assert await scraper.fetch("durov", transport=transport) == "<html>ok</html>"
