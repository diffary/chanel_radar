# channel-radar

> 🔗 **Live service:** _TODO: paste public URL here at the very top (graded)_

Live dashboard for public Telegram channel analytics. Add a channel by username, watch it
collect posts and metric history, read an LLM digest — all at a public URL.

> _This README is a skeleton. Fill each section during Task 7. Live link goes first._

## Run locally
```
python -m venv .venv && source .venv/Scripts/activate   # Windows Git Bash
pip install -r requirements.txt
cp .env.example .env   # fill DATABASE_URL, GEMINI_API_KEY, COLLECT_SECRET
uvicorn app.main:app --reload
```

## Tests (no network)
```
pytest
```

## Data model
_TODO: schema + why. Natural key `(channel_id, message_id)`; metric snapshots store dynamics over time._

## AI layer
_TODO: what it does (digest / categorize) and what happens when Gemini is down or rate-limited (dashboard stays up)._

## Hosting
_TODO: chosen host + why, its limits (cold start / sleep), and how the scheduled collection wakes it (external cron via GitHub Actions)._

Tables are created with `Base.metadata.create_all` on startup — a deliberate simplification for this project; production would use Alembic migrations.

## What's not done and why
_TODO._
