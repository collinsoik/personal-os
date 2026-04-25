# Personal OS — backend handoff

Snapshot: **2026-04-25** (post goal-#1 ship). Use this to pick up the project in a fresh Claude session.

## Where we are

- **Frontend** (`index.html` + `app.js`) — single static page, deployed to Vercel at `personal-os-sage-tau.vercel.app`. No build step.
- **Backend** (`backend/`) — FastAPI in Docker on Olympus VM (`192.168.1.223`). SQLite at `backend/data/personal-os.db`. Public hostname: `https://personal-os-api.collinsoik.dev`. APScheduler poller + SSE stream.
- **Container**: `personal-os-api`, port `127.0.0.1:3010`. Health: `GET /api/health`. Main payload: `GET /api/dashboard`. Presence write: `POST /api/presence/ping`. Authed write smoke-test: `POST /api/ping` with `X-PO-Secret`.
- **MCP server** (new): `/mcp/` mounted on the same FastAPI app. OAuth 2.1 with PKCE (S256), pre-registered claude.ai client. AS endpoints at `/.well-known/oauth-authorization-server`, `/.well-known/oauth-protected-resource/mcp`, `/authorize`, `/token`. One tool exposed: `submit_routine_digest`.

## Cards — wiring status

| Card | Real data? | Source |
|---|---|---|
| Speaker (presence ONLINE/OFFLINE) | yes | `/api/presence/ping` heartbeat from frontend |
| Session (greeting + clock + weather) | partial | clock client-side; weather hardcoded location |
| Vitals (steps, heart, sleep, HRV, water) | **no** — placeholder | needs ingest |
| Habits (Write / Meditate / Run · 14d dots) | **no** — placeholder | needs ingest |
| Thought (daily quote) | yes | `quotes.json` ingested by `backend/app/scripts/ingest_quotes.py` |
| Calendar (week strip + per-day events) | yes | `backend/app/gcal.py` (Google OAuth) |
| **Routine** (was Inbox) | yes | cloud routine `trig_01E5JYZrgQ5sJ614TRrPLJsU` posts via MCP tool 3×/day; SSE-pushed to dashboard |
| Now Playing (Spotify + SSE) | yes | `backend/app/spotify.py`, SSE via `events.py` |
| Project (active project + tasks) | **no** — placeholder | needs ingest |

## What just shipped (UI-only)

- Removed Activity rings from Vitals; right column now splits 50/50 between Vitals (top) and Project (bottom) via `.right-col` wrapper.
- Replaced Inbox card with **Routine card** (Email Routine UI design A — 330×680, fixed height, internal scroll). Three stacked sections: Urgent / High importance / FYI. Hover schedule popover (06/12/18). Done / Snooze / "+N more" interactions are local-state only.
- Layout swap: Routine took the full center-left column (`grid-column: 2/3; grid-row: 2/4`). Calendar moved to `grid-column: 3/4; grid-row: 2/3` and is internally scrollable.

The mock data for the Routine lives in `app.js` as `ROUTINE_DATA` — Maya Lin, Arc Collective, Theo Harris, Eliza N., Jules Reyes, Stripe / GitHub / Figma / Read.cv. Swap this object for a real digest payload when the backend is ready (see below).

## Backend goals — prioritized

### 1. Email Routine — ✅ done

Live end-to-end. Cloud routine `trig_01E5JYZrgQ5sJ614TRrPLJsU` runs at `0 10,16,22 UTC` (6am/12pm/6pm EDT — see DST note below). Calls `submit_routine_digest` MCP tool on this backend; persisted in `CachedPayload(key='routine')` and SSE-broadcast as `routine` event. Frontend `renderRoutine(digest)` falls back to inline `ROUTINE_DATA` mock if no digest present.

Auth model: claude.ai is a pre-registered OAuth client of the backend. Connector lives at https://claude.ai/settings/connectors/b5772ae4-a52b-4c79-bd29-62aaf54cc5d9. Client_id and client_secret stored in `backend/.env` as `PERSONAL_OS_OAUTH_CLIENT_ID` / `PERSONAL_OS_OAUTH_CLIENT_SECRET`.

**DST gotcha**: cron is UTC-fixed. Update to `0 11,17,23 * * *` on Nov 1, 2026 (DST ends), back to `0 10,16,22 * * *` on Mar 8, 2027.

### 2. Vitals ingest

Steps, heart_bpm, sleep_hours, hrv_ms, water_l. The dashboard payload already has the schema (`backend/app/dashboard.py` reads from `CachedPayload('health')`). Need either an Apple Health export ingest or a manual write endpoint.

### 3. Habits

`Habit` + `HabitTick` tables already exist in `backend/app/models.py`. Need a write endpoint (`POST /api/habits/{key}/tick`) so the user can mark today's tick from the dashboard or another client. The 14-day dot grid in the frontend is already wired to render from `habits[].ticks`.

### 4. Active Project

Same shape — `Project` and `Task` tables exist; `dashboard.py` reads them. Need write endpoints for creating/updating tasks and toggling `done`. Frontend renders progress bar + checklist already.

## Known issues / followups

### Spotify in ~20.8-hour cooldown (2026-04-25)

After the 429-handling fix shipped today (commit `6ed3dd0`, `backend/app/spotify.py`), the first poll after restart logged:

```
Spotify 429 on /me/top/tracks — backing off for 74927s
Spotify 429 on /me/player/recently-played — backing off for 74927s
```

74927s ≈ 20h 49m — much longer than the plan modeled. `_backoff_until` is process-local; snapshot short-circuits until **~2026-04-26 13:25 local**. Until then the music card shows the empty default (`title: "—"`, `playing: false`). Auto-recovers — no action needed unless it's still empty past that window.

**Why the whole card goes blank, not just top/recent:** the backoff check sits at the top of `fetch_music_snapshot`, so `/me/player` (cheap, frequently-changing, almost certainly *not* rate-limited) is also skipped during the window.

**Followup if this recurs** — replace the single global `_backoff_until` with a per-endpoint dict (keyed by path) so `/me/player` keeps updating title/artist/progress even when top/recent are throttled. ~30-line change in `spotify.py`. Skipped today since waiting it out is fine for this round; revisit if the empty-card window happens again.

**Sanity check after the cooldown:**
```
curl -s https://personal-os-api.collinsoik.dev/api/dashboard | jq '.music'
```
Expect `title`/`artist` to populate once playback resumes. If still empty past the window, the backoff logic itself has a bug.

## Useful files / paths

- Frontend: `/home/collin/Personal_OS/personal-os/index.html`, `app.js`
- Backend: `/home/collin/Personal_OS/personal-os/backend/app/`
  - `main.py` — FastAPI entry, lifespan starts/stops poller + MCP session manager
  - `dashboard.py` — `build_dashboard()` aggregator
  - `events.py` — SSE stream
  - `models.py`, `db.py` — SQLAlchemy models + session
  - `gcal.py`, `spotify.py`, `oauth.py` — outbound integrations (Google, Spotify)
  - `oauth_server.py` — **inbound** OAuth 2.1 AS for the MCP connector
  - `mcp_server.py` — FastMCP server mounted at `/mcp`, tool: `submit_routine_digest`
  - `routine.py` — digest endpoint + `persist_digest` shared between HTTP and MCP paths
  - `poller.py` — APScheduler config
- Compose: `backend/compose.yml`. Rebuild: `cd backend && docker compose up -d --build`.
- Deploy: `vercel --prod --yes` from `personal-os/`.

## Conventions / preferences

- New integrations: prefer SSE/WebSocket push over frontend polling.
- Pushes go directly to `main`; no PR flow for this repo.
- "Commit and push" means: stage + commit + push to origin/main + Vercel `--prod` redeploy + (if backend changed) `docker compose up -d --build`.
- Cloud routines write to the backend via the **MCP server**, not curl. The sandbox blocks outbound HTTP to unknown hosts; MCP traffic flows through Anthropic's connector layer. To add a new write path (e.g. for goals 2-4), add a tool to `mcp_server.py` that calls into the relevant persist function.

## Infra notes

- cloudflared runs under systemd as three units: `cloudflared-personal-os`, `cloudflared-email-mcp`, `cloudflared-x-puller`. Edit a tunnel config → `sudo systemctl restart cloudflared-<name>`. They auto-start on reboot. Don't run `cloudflared` from a shell — leftover manual instances with stale config caused a half-hour debug cycle on 2026-04-25.
- Dormant tunnel configs in `~/.cloudflared/`: `config-pathfinder.yml`, `designdash-config.yml`. Add as systemd units following the same pattern if you want them active.
