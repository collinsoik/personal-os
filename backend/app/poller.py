"""APScheduler-driven background pollers.

Writes poller output to CachedPayload so /api/dashboard can serve it
without blocking on the upstream APIs.
"""
from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.orm import Session

from . import models, spotify
from .db import SessionLocal

log = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


def _write_cache(db: Session, key: str, payload: dict) -> None:
    row = db.get(models.CachedPayload, key)
    if row is None:
        db.add(models.CachedPayload(key=key, payload=payload))
    else:
        row.payload = payload
        row.updated_at = datetime.utcnow()
    db.commit()


async def poll_spotify() -> None:
    try:
        with SessionLocal() as db:
            snap = await spotify.fetch_music_snapshot(db)
            if snap is None:
                return
            _write_cache(db, "spotify", snap)
    except Exception:
        log.exception("Spotify poll failed")


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        poll_spotify,
        "interval",
        seconds=20,
        id="spotify_poll",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(),
    )
    _scheduler.start()
    log.info("Scheduler started")


def stop() -> None:
    global _scheduler
    if _scheduler is None:
        return
    _scheduler.shutdown(wait=False)
    _scheduler = None
