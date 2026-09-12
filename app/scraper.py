"""Fetch and parse the public Telegram web preview (https://t.me/s/<channel>).

This module only does HTTP + HTML parsing and returns plain dicts.
No database, no LLM. `parse_channel` is deterministic for a given HTML string,
so it is tested against saved fixtures in tests/fixtures/.
"""
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

TELEGRAM_HOST = "t.me"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT_SECONDS = 15.0


class ScrapeError(Exception):
    """Base class for scraper failures."""


class ChannelNotFound(ScrapeError):
    """The channel does not exist (Telegram redirects to telegram.org)."""


class ChannelUnavailable(ScrapeError):
    """The channel exists but has no readable posts (private, empty, blocked)."""


# --- small helpers -----------------------------------------------------------


def normalize_username(raw: str) -> str:
    """Turn '@durov', 'https://t.me/s/durov/' or ' durov ' into 'durov'."""
    name = raw.strip()
    for prefix in ("https://", "http://"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.startswith("t.me/"):
        name = name[len("t.me/"):]
    if name.startswith("s/"):
        name = name[len("s/"):]
    name = name.strip("/")
    if name.startswith("@"):
        name = name[1:]
    return name


def parse_count(text) -> int:
    """Convert a t.me counter like '18.8M', '585K', '1 234' into an int.

    Limitation: t.me shows abbreviated numbers ('18.8M' means roughly
    18.8 million), so values we store are approximations, not exact counts.
    Empty or missing text becomes 0.
    """
    if not text:
        return 0
    cleaned = text.strip().replace(" ", "").replace("\xa0", "").replace(",", "")
    if not cleaned:
        return 0

    multiplier = 1
    if cleaned[-1] in ("K", "k"):
        multiplier = 1_000
        cleaned = cleaned[:-1]
    elif cleaned[-1] in ("M", "m"):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]

    try:
        return int(round(float(cleaned) * multiplier))
    except ValueError:
        return 0


def _text_of(parent, selector: str) -> str:
    """Return the text of the first element matching selector, or ''."""
    element = parent.select_one(selector)
    if element is None:
        return ""
    return element.get_text(" ", strip=True)


def _parse_subscribers(soup) -> int:
    """Find the header counter whose label says 'subscribers'."""
    for counter in soup.select(".tgme_channel_info_counter"):
        label = _text_of(counter, ".counter_type")
        if label == "subscribers":
            return parse_count(_text_of(counter, ".counter_value"))
    return 0


def _parse_reactions(message) -> int:
    """Sum every reaction counter of a message (including paid star reactions).

    Each reaction looks like <span class="tgme_reaction"><i>emoji</i>190</span>,
    so the count is the last piece of content inside the span.
    """
    total = 0
    for reaction in message.select(".tgme_reaction"):
        if not reaction.contents:
            continue
        total += parse_count(str(reaction.contents[-1]))
    return total


def _parse_posted_at(message) -> datetime:
    time_tag = message.select_one(".tgme_widget_message_date time")
    if time_tag is None or not time_tag.get("datetime"):
        raise ChannelUnavailable("message without a datetime")
    # Example value: 2026-06-15T18:58:13+00:00 (already tz-aware)
    return datetime.fromisoformat(time_tag["datetime"])


def _parse_post(message) -> dict:
    # data-post looks like "durov/528": channel username + message id.
    channel_name, message_id = message["data-post"].split("/")
    return {
        "message_id": int(message_id),
        "text": _text_of(message, ".tgme_widget_message_text"),
        "posted_at": _parse_posted_at(message),
        "views": parse_count(_text_of(message, ".tgme_widget_message_views")),
        "reactions": _parse_reactions(message),
        "link": f"https://{TELEGRAM_HOST}/{channel_name}/{message_id}",
    }


# --- public API --------------------------------------------------------------


def parse_channel(html: str) -> dict:
    """Parse a t.me/s/<channel> page into {"title", "subscribers", "posts"}.

    Raises ChannelNotFound when the page has no channel info block, and
    ChannelUnavailable when the channel exists but shows no posts.
    """
    soup = BeautifulSoup(html, "lxml")

    if soup.select_one(".tgme_channel_info") is None:
        raise ChannelNotFound("page has no channel info block")

    posts = []
    for message in soup.select(".tgme_widget_message"):
        if not message.get("data-post"):
            continue  # service messages (pinned, joined, ...) have no data-post
        posts.append(_parse_post(message))

    if not posts:
        raise ChannelUnavailable("channel has no visible posts")

    posts.sort(key=lambda post: post["message_id"])

    return {
        "title": _text_of(soup, ".tgme_channel_info_header_title"),
        "subscribers": _parse_subscribers(soup),
        "posts": posts,
    }


async def fetch(username: str, transport=None) -> str:
    """Download the public preview page for a channel and return its HTML.

    `transport` exists only so tests can plug in httpx.MockTransport.
    """
    url = f"https://{TELEGRAM_HOST}/s/{normalize_username(username)}"
    async with httpx.AsyncClient(
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_SECONDS,
        transport=transport,
    ) as client:
        response = await client.get(url)

    if response.url.host != TELEGRAM_HOST:
        # Unknown channels get redirected to telegram.org
        raise ChannelNotFound(f"{username}: redirected to {response.url}")
    if response.status_code != 200:
        raise ChannelUnavailable(f"{username}: HTTP {response.status_code}")
    return response.text


async def scrape(username: str) -> dict:
    """Convenience for the collector: fetch + parse in one call."""
    return parse_channel(await fetch(username))
