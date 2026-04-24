"""Spotify playback control routes. Require the write secret."""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import events, models, spotify
from .db import get_session
from .deps import require_secret

log = logging.getLogger(__name__)
router = APIRouter(dependencies=[Depends(require_secret)])


async def _do(action_fn, db: Session):
    try:
        await action_fn(db)
    except spotify.ControlError as e:
        raise HTTPException(status_code=e.status, detail={"error": str(e)})

    snap = await spotify.fetch_music_snapshot(db)
    if snap is not None:
        row = db.get(models.CachedPayload, "spotify")
        if row is None:
            db.add(models.CachedPayload(key="spotify", payload=snap))
        else:
            row.payload = snap
            row.updated_at = datetime.utcnow()
        db.commit()
        events.broadcast("music", snap)
    return {"ok": True, "music": snap}


@router.post("/spotify/play")
async def spotify_play(db: Session = Depends(get_session)):
    return await _do(spotify.play, db)


@router.post("/spotify/pause")
async def spotify_pause(db: Session = Depends(get_session)):
    return await _do(spotify.pause, db)


@router.post("/spotify/next")
async def spotify_next(db: Session = Depends(get_session)):
    return await _do(spotify.next_track, db)


@router.post("/spotify/previous")
async def spotify_previous(db: Session = Depends(get_session)):
    return await _do(spotify.previous_track, db)
