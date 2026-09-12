# channel-radar — agent working agreement

Live dashboard that scrapes public Telegram channels via the anonymous web preview
(`t.me/s/<channel>`), stores posts + metric history, enriches with an LLM, and shows a
dashboard at a public URL.

This file is the contract for how code is organized. It is NOT a copy of the README.

## Layer boundaries (do not cross)

- `app/scraper.py` — pure fetch + parse of `t.me/s/<channel>` HTML into plain dicts.
  No DB, no LLM. Deterministic given HTML input, so it can be tested on saved fixtures.
- `app/collector.py` — orchestrates a collection run: calls scraper, upserts channel/posts
  **idempotently** (natural key `(channel_id, message_id)`), appends metric snapshots.
  No HTTP parsing here, no web-request handling.
- `app/ai.py` — LLM calls only (Gemini). Every public function MUST degrade gracefully:
  on API error or rate limit it returns `None`/cached value and never raises to the caller.
- `app/analytics.py` — pure metric math over stored rows (growth, deltas, period filter).
  No DB writes, no network. Fully unit-testable.
- `app/routes/` — thin HTTP layer. Routes call collector/analytics/ai, never parse HTML
  or talk to the LLM directly with inline logic.
- `app/models.py` — SQLAlchemy models only. `app/schemas.py` — Pydantic I/O only.
- `app/templates/` — Jinja2. Presentation only, no business logic.

## Hard rules (these are graded / are stop-factors)

- **No secrets in git.** Gemini key + DB URL come from env. `.env.example` has placeholders only.
- **Tests never touch the network.** Scraper tests use saved HTML fixtures in `tests/fixtures/`.
  LLM calls are mocked. If a test needs the network, the design is wrong.
- **Idempotent collection.** Running collection twice on the same data creates zero duplicates.
- **The deployed URL must work at review time.** Deploy early, keep it alive (see README hosting note).
- **Every non-trivial piece must be explainable out loud.** No cleverness the author cannot defend
  on a live call. Simple and defensible beats smart and opaque.

## Stack

Python 3.12, FastAPI, SQLAlchemy 2 (async) + asyncpg, PostgreSQL (Neon), httpx + BeautifulSoup,
Jinja2 + Chart.js (CDN), google-generativeai (Gemini free tier), pytest + pytest-asyncio.

## Definition of done for any task

Test written first and failing → minimal code → test passes → committed. No task is "done"
until its tests pass with no network access.
