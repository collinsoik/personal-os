"""OAuth login/callback routes.

Spotify flow (task #6):
    GET /api/oauth/spotify/login?s=<write_secret>  -> redirect to Spotify
    GET /api/oauth/spotify/callback?code&state     -> save tokens, snapshot, confirm
"""
from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from . import models, spotify
from .config import settings
from .db import SessionLocal

log = logging.getLogger(__name__)
router = APIRouter()


def _require_secret(s: str | None) -> None:
    if s != settings().write_secret:
        raise HTTPException(status_code=401, detail="bad secret")


@router.get("/oauth/spotify/login")
def spotify_login(s: str | None = Query(default=None)):
    _require_secret(s)
    if not settings().spotify_client_id:
        raise HTTPException(status_code=500, detail="SPOTIFY_CLIENT_ID not configured")
    return RedirectResponse(spotify.build_authorize_url(), status_code=302)


@router.get("/oauth/spotify/callback")
async def spotify_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify auth error: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="missing code")
    if not spotify.consume_state(state):
        raise HTTPException(status_code=400, detail="invalid state")

    try:
        token_payload = await spotify.exchange_code(code)
    except Exception as e:
        log.exception("Spotify token exchange failed")
        raise HTTPException(status_code=502, detail=f"token exchange failed: {e}")

    with SessionLocal() as db:
        spotify.save_tokens(db, token_payload)
        snap = await spotify.fetch_music_snapshot(db)
        if snap:
            row = db.get(models.CachedPayload, "spotify")
            if row is None:
                db.add(models.CachedPayload(key="spotify", payload=snap))
            else:
                row.payload = snap
                row.updated_at = datetime.utcnow()
            db.commit()

    front = settings().frontend_url
    html = f"""<!doctype html>
<meta charset="utf-8">
<title>Spotify connected</title>
<style>
  body{{font-family:system-ui,sans-serif;padding:48px;max-width:520px;color:#222}}
  h1{{font-weight:500;letter-spacing:-.01em}}
  a{{color:#222}}
</style>
<h1>Spotify connected.</h1>
<p>Tokens saved. The dashboard will pick up a fresh snapshot within 30 seconds.</p>
<p><a href="{front}">Back to Personal OS</a></p>
"""
    return HTMLResponse(html)
