# channel-radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.
> **For the author (Serhii):** after each task, read the code and explain it back in your own words before moving on. The final call is a stop-factor on "can't explain your own code." Simple > clever.

**Goal:** A deployed dashboard where a user adds a public Telegram channel by username and, within seconds, sees it collecting posts + metric history, with an LLM digest, all live at a public URL.

**Architecture:** FastAPI app. `scraper` parses `t.me/s/<channel>` HTML → dicts. `collector` upserts channels/posts idempotently by natural key and appends metric snapshots. `analytics` is pure math over stored rows. `ai` wraps Gemini with graceful fallback. Jinja2 + Chart.js render the dashboard. A `/internal/collect` endpoint is triggered on a schedule by GitHub Actions (host sleeps, so an external cron wakes it).

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2 async + asyncpg, PostgreSQL (Neon), httpx + BeautifulSoup, Jinja2 + Chart.js, google-generativeai, pytest + pytest-asyncio.

**Grading weights (build to these):** add-channel-from-UI 25%, data model 20%, live service 15%, AI quality 15%, communication/docs 15%, tests 10%.

---

## Data model (locked in Task 2)

- `channels`: id, username (unique — natural key), title, subscribers, status (`pending|active|error`), error_reason, added_at, last_collected_at
- `posts`: id, channel_id FK, message_id (int), text, posted_at, link, first_seen_at — **unique (channel_id, message_id)** = idempotency key
- `post_metric_snapshots`: id, post_id FK, collected_at, views, reactions — **one row per collection run** → this is how metric *dynamics over time* are stored, not just the latest value
- `channel_metric_snapshots`: id, channel_id FK, collected_at, subscribers, post_count

---

## Task 0: Project skeleton + live deploy (do FIRST — 15% is "it's alive")

**Files:** `app/main.py`, `app/config.py`, `app/db.py`, `requirements.txt`, `render.yaml`, `.env.example`, `.gitignore`, `README.md`

- [ ] FastAPI app with `GET /health` → `{"status":"ok"}` and `GET /` → placeholder page
- [ ] `config.py` reads `DATABASE_URL`, `GEMINI_API_KEY` from env (pydantic-settings)
- [ ] `db.py`: async engine + session factory; `init_db()` runs `create_all` on startup (deliberate simplification for test scope — note in README; Alembic in prod)
- [ ] Create Neon Postgres, wire `DATABASE_URL`; deploy to Render; confirm the public URL serves `/health`
- [ ] Commit. **Checkpoint: the URL is live before writing more.**

## Task 1: Scraper (pure, fixture-tested)

**Files:** `app/scraper.py`, `tests/test_scraper.py`, `tests/fixtures/*.html`

- [ ] Save 1-2 real `t.me/s/<channel>` HTML pages into `tests/fixtures/` (do this once, by hand)
- [ ] **Test first:** `parse_channel(html) -> {title, subscribers, posts:[{message_id, text, posted_at, views, reactions, link}]}` asserts exact values from a fixture
- [ ] Run test → fails
- [ ] Implement `fetch(username) -> html` (httpx, real network, NOT under test) + `parse_channel(html)` (BeautifulSoup, pure)
- [ ] Handle: channel not found / private / empty → raise a typed error the collector maps to `status=error`
- [ ] Tests pass with no network. Commit.

## Task 2: Models + idempotent collector

**Files:** `app/models.py`, `app/collector.py`, `tests/test_collector.py`

- [ ] Define the 4 models above
- [ ] **Test first:** collecting the same parsed payload twice creates posts once (no dupes) and appends a new metric snapshot each run (views history grows)
- [ ] Implement `collect_channel(session, username)`: fetch→parse→upsert channel→upsert posts by `(channel_id, message_id)`→insert metric snapshots→update `last_collected_at`
- [ ] On scraper error → set channel `status=error`, don't crash
- [ ] Tests pass (in-memory/temp DB, no network — parsed payload passed as fixture). Commit.

## Task 3: Add channel from UI (25% — the headline feature)

**Files:** `app/routes/channels.py`, `app/routes/pages.py`, `app/templates/index.html`, `tests/test_channels_api.py`

- [ ] **Test first:** `POST /channels {username}` with a valid channel → 201, channel row with `status=pending`; unknown/private → 4xx with clear message; duplicate → no second row
- [ ] Implement endpoint: validate → insert `pending` → kick first collection via `BackgroundTasks` (no Celery) → return immediately
- [ ] `index.html`: add-channel form + channel list; a `pending` channel shows "collecting…"; polling or refresh flips it to active once data lands
- [ ] Handle nonexistent/private in the UI (show the error, don't hang)
- [ ] Tests pass (collection mocked). Commit.

## Task 4: Dashboard pages

**Files:** `app/routes/pages.py`, `app/analytics.py`, `templates/channel.html`, `templates/post.html`, `tests/test_analytics.py`

- [ ] **Test first (analytics):** `metrics_over_time(snapshots, period)` and any growth/delta calc — pure, exact numbers
- [ ] Implement analytics; channel page: Chart.js trend of views/subscribers over time + post list with views/reactions + period filter
- [ ] Post page: details, metrics, link to original
- [ ] Overview: channel list with subscribers, post count, last-collected, source "health"
- [ ] Commit.

## Task 5: AI layer (15% — must be graceful)

**Files:** `app/ai.py`, `tests/test_ai.py`

- [ ] **Test first (mocked Gemini):** `channel_digest(posts)` returns text on success; on raised API error returns `None` and caller still renders. `categorize(post)` similar.
- [ ] Implement Gemini calls wrapped in try/except; cache result on the row so it is not recomputed every request; never raise to routes
- [ ] Wire digest into channel page ("what this channel wrote about lately"); show a neutral note if unavailable
- [ ] Tests pass (no real API). Commit.

## Task 6: Scheduled collection (the documented gotcha)

**Files:** `app/routes/internal.py`, `.github/workflows/collect.yml`

- [ ] `POST /internal/collect` (guarded by a shared secret header) → re-collects all active channels, incremental only
- [ ] GitHub Actions cron (e.g. every 30 min) curls that endpoint → wakes the sleeping Render service
- [ ] Document in README why external cron is needed (host sleeps on inactivity)
- [ ] Commit.

## Task 7: Docs (15%)

**Files:** `README.md`, `docs/adr/0001-hosting.md`, `0002-metric-dynamics-schema.md`, `0003-llm-provider.md`

- [ ] README: **live link at the very top**, local run steps, schema + why, AI-layer behavior + fallback, hosting limits + how handled, what's not done + why
- [ ] 3 short ADRs on the costly-to-reverse choices
- [ ] Final check: fresh clone + `.env` → runs; deployed URL works; no secrets in git; `pytest` green with no network
- [ ] Commit.

## Optional (only if time left — pluses, not required)
- Multi-channel comparison on one chart
- "channel hasn't posted in 3 days" alert
- Export slice for LLM

## Submission
Repo link + live URL + 3-5 sentences on the hardest deploy/AI decision. Then a 30-min call:
they add a channel on screen and walk your code. **Drill before it.**
