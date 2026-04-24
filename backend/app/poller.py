"""Background pollers.

- Spotify: self-paced async loop, 5s while playing (1.5s near end-of-track),
  30s while paused/idle. Diffs new snapshot vs previous and broadcasts an
  SSE "music" event on change.
- Calendar: every 5 minutes via APScheduler.

Writes poller output to CachedPayload so /api/dashboard can serve it
without blocking on the upstream APIs.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from . import events, gcal, models, spotify
from .db import SessionLocal

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_spotify_task: asyncio.Task | None = None

# Adaptive poll delays (seconds)
_POLL_PLAYING = 5.0
_POLL_NEAR_END = 1.5
_POLL_IDLE = 30.0
_NEAR_END_THRESHOLD_MS = 5_000


def _write_cache(db: Session, key: str, payload: dict) -> None:
    row = db.get(models.CachedPayload, key)
    if row is None:
        db.add(models.CachedPayload(key=key, payload=payload))
    else:
        row.payload = payload
        row.updated_at = datetime.utcnow()
    db.commit()


def _should_broadcast(prev: dict | None, new: dict) -> bool:
    if prev is None:
        return True
    for k in ("title", "artist", "album", "playing"):
        if prev.get(k) != new.get(k):
            return True
    return False


def _next_delay(snap: dict | None) -> float:
    if not snap or not snap.get("playing"):
        return _POLL_IDLE
    duration = int(snap.get("duration_ms") or 0)
    progress = int(snap.get("progress_ms") or 0)
    if duration and duration - progress < _NEAR_END_THRESHOLD_MS:
        return _POLL_NEAR_END
    return _POLL_PLAYING


async def poll_spotify() -> dict | None:
    """One snapshot pull. Returns the new snapshot (or None on no-op/failure)."""
    try:
        with SessionLocal() as db:
            snap = await spotify.fetch_music_snapshot(db)
            if snap is None:
                return None
            prev = db.get(models.CachedPayload, "spotify")
            prev_payload = prev.payload if prev else None
            _write_cache(db, "spotify", snap)
        if _should_broadcast(prev_payload, snap):
            events.broadcast("music", snap)
        return snap
    except Exception:
        log.exception("Spotify poll failed")
        return None


async def _spotify_loop() -> None:
    while True:
        snap = await poll_spotify()
        delay = _next_delay(snap)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return


async def poll_calendar() -> None:
    try:
        with SessionLocal() as db:
            snap = await gcal.fetch_calendar_snapshot(db)
            if snap is None:
                return
            _write_cache(db, "calendar", snap)
    except Exception:
        log.exception("Calendar poll failed")


def start() -> None:
    global _scheduler, _spotify_task
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        poll_calendar,
        "interval",
        seconds=300,
        id="calendar_poll",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    _scheduler.start()
    _spotify_task = asyncio.create_task(_spotify_loop())
    log.info("Scheduler + spotify loop started")


def stop() -> None:
    global _scheduler, _spotify_task
    if _spotify_task is not None:
        _spotify_task.cancel()
        _spotify_task = None
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
