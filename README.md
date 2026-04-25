# Personal OS

A bento-grid personal dashboard. Frontend is a single static page deployed to Vercel; backend is a FastAPI service running in Docker on the home VM.

## Cards

Speaker · Session · Vitals · Habits · Thought · Calendar · Inbox · Now Playing · Project

## Stack

- **Frontend**: `index.html` + `app.js`, no build step. Fraunces + Inter + JetBrains Mono. Deployed via Vercel.
- **Backend**: FastAPI (`backend/app/`), SQLite (`backend/data/personal-os.db`), APScheduler poller, SSE stream for live music/presence updates.
- **Auth**: OAuth flows for Google Calendar and Spotify; shared-secret header (`X-PO-Secret`) on write routes.

## Integrations

- **Spotify** — Now Playing card with album-art cover, smooth progress, controls, top tracks, weekly hours.
- **Google Calendar** — interactive week strip with per-day events.
- **Weather** — topbar.
- **Quotes** — daily Thought card, ingested via `backend/app/scripts/ingest_quotes.py`.
- **Presence** — Speaker card ONLINE badge driven by a heartbeat ping.

## Run

**Frontend (local):** open `index.html` or serve the folder with any static server.

**Backend:**
```bash
cd backend
cp .env.example .env   # fill in OAuth + secrets
docker compose up -d --build
```

API listens on `127.0.0.1:3010`. Health check: `GET /api/health`. Main payload: `GET /api/dashboard`.
