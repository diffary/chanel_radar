"""Fetch and parse the public Telegram web preview (https://t.me/s/<channel>).

This module only does HTTP + HTML parsing and returns plain dicts.
No database, no LLM. `parse_channel` is deterministic for a given HTML string,
so it is tested against saved fixtures in tests/fixtures/.
"""
import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

TELEGRAM_HOST = "t.me"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
TIMEOUT_SECONDS = 15.0
PARSER = "lxml"
# Telegram usernames: 5-32 characters, letters/digits/underscore.
USERNAME_RE = re.compile(r"[A-Za-z0-9_]{5,32}")
# "18.8M", "585K", "102" -> number part + optional K/M suffix.
COUNT_RE = re.compile(r"(\d+(?:\.\d+)?)([KkMm]?)")


class ScrapeError(Exception):
    """Base class for scraper failures."""


class ChannelNotFound(ScrapeError):
    """The channel does not exist (Telegram redirects to telegram.org)."""


class ChannelUnavailable(ScrapeError):
    """The channel exists but has no readable posts (private, empty, blocked)."""


# --- small helpers -----------------------------------------------------------


def normalize_username(raw: str) -> str:
    """Turn '@durov', 'https://t.me/s/durov/' or ' durov ' into 'durov'.

    Raises ValueError when the result is not a valid Telegram username
    (this is caller input, so routes can answer 400).
    """
    name = raw.strip()
    for prefix in ("https://", "http://"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    if name.startswith("t.me/"):
        name = name[len("t.me/"):]
    if name.startswith("s/"):
        name = name[len("s/"):]
    # keep only the first path segment, drop any query string
    name = name.split("/")[0].split("?")[0]
    if name.startswith("@"):
        name = name[1:]
    if not USERNAME_RE.fullmatch(name):
        raise ValueError(f"invalid channel username: {raw!r}")
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
    match = COUNT_RE.fullmatch(cleaned)
    if match is None:
        return 0  # negatives, unknown suffixes like "5B", junk -> 0

    number, suffix = match.groups()
    multiplier = 1
    if suffix in ("K", "k"):
        multiplier = 1_000
    elif suffix in ("M", "m"):
        multiplier = 1_000_000
    return int(float(number) * multiplier)


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

    Each reaction looks like <span class="tgme_reaction"><i><b>emoji</b></i>190</span>.
    The emoji lives in child tags, so we read only the span's own text nodes.
    """
    total = 0
    for reaction in message.select(".tgme_reaction"):
        own_text = "".join(reaction.find_all(string=True, recursive=False))
        total += parse_count(own_text)
    return total


def _parse_posted_at(message):
    """Return a tz-aware datetime, or None when the post has no <time datetime>."""
    time_tag = message.select_one(".tgme_widget_message_date time")
    if time_tag is None or not time_tag.get("datetime"):
        return None
    # Example value: 2026-06-15T18:58:13+00:00 (already tz-aware)
    return datetime.fromisoformat(time_tag["datetime"])


def _parse_post(message):
    """Return a post dict, or None when the block is malformed."""
    # data-post looks like "durov/528": channel username + message id.
    parts = message.get("data-post", "").split("/")
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    channel_name, message_id = parts

    posted_at = _parse_posted_at(message)
    if posted_at is None:
        return None

    return {
        "message_id": int(message_id),
        "text": _text_of(message, ".tgme_widget_message_text"),
        "posted_at": posted_at,
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
    soup = BeautifulSoup(html, PARSER)

    if soup.select_one(".tgme_channel_info") is None:
        raise ChannelNotFound("page has no channel info block")

    posts = []
    for message in soup.select(".tgme_widget_message"):
        if not message.get("data-post"):
            continue  # service messages (pinned, joined, ...) have no data-post
        post = _parse_post(message)
        if post is None:
            continue  # malformed post; don't fail the whole channel
        posts.append(post)

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
    # TODO(collector): pass a shared client when scraping many channels per run
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
