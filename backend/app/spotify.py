"""Spotify OAuth + Web API client.

OAuth flow:
    build_authorize_url() -> redirect user here
    exchange_code(code)   -> /callback swaps code for tokens
    save_tokens(db, ...)  -> persists to OAuthToken
    get_valid_access_token(db) -> loads latest, refreshes if expiring

Snapshot:
    fetch_music_snapshot(db) -> dict matching the dashboard `music` shape
"""
from __future__ import annotations

import base64
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.orm import Session

from . import models
from .config import settings

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
API_BASE = "https://api.spotify.com/v1"

SCOPES = [
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-top-read",
]

# In-memory CSRF states. Single-process uvicorn; restart mid-flow just means retry.
_pending_states: dict[str, float] = {}
_STATE_TTL_SEC = 600


def _purge_states() -> None:
    now = time.time()
    for s in [s for s, t in _pending_states.items() if now - t > _STATE_TTL_SEC]:
        _pending_states.pop(s, None)


def build_authorize_url() -> str:
    _purge_states()
    state = secrets.token_urlsafe(24)
    _pending_states[state] = time.time()
    params = {
        "client_id": settings().spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings().spotify_redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "show_dialog": "false",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def consume_state(state: str | None) -> bool:
    if not state:
        return False
    _purge_states()
    return _pending_states.pop(state, None) is not None


def _basic_auth_header() -> dict[str, str]:
    s = settings()
    token = base64.b64encode(
        f"{s.spotify_client_id}:{s.spotify_client_secret}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


async def exchange_code(code: str) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings().spotify_redirect_uri,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(TOKEN_URL, data=data, headers=_basic_auth_header())
        r.raise_for_status()
        return r.json()


async def _refresh(refresh_token: str) -> dict[str, Any]:
    data = {"grant_type": "refresh_token", "refresh_token": refresh_token}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(TOKEN_URL, data=data, headers=_basic_auth_header())
        r.raise_for_status()
        return r.json()


def save_tokens(
    db: Session, payload: dict[str, Any], account: str = "me"
) -> models.OAuthToken:
    expires_at = datetime.utcnow() + timedelta(
        seconds=int(payload.get("expires_in", 3600))
    )
    row = (
        db.query(models.OAuthToken)
        .filter_by(provider="spotify", account=account)
        .one_or_none()
    )
    if row is None:
        row = models.OAuthToken(provider="spotify", account=account)
        db.add(row)
    row.access_token = payload["access_token"]
    if "refresh_token" in payload:
        row.refresh_token = payload["refresh_token"]
    row.expires_at = expires_at
    row.scope = payload.get("scope")
    db.commit()
    db.refresh(row)
    return row


async def get_valid_access_token(db: Session) -> str | None:
    row = (
        db.query(models.OAuthToken)
        .filter_by(provider="spotify")
        .order_by(models.OAuthToken.id.desc())
        .first()
    )
    if row is None:
        return None
    # Refresh if expiring in next 60s.
    if row.expires_at and row.expires_at - timedelta(seconds=60) <= datetime.utcnow():
        if not row.refresh_token:
            log.warning("Spotify token expired and no refresh_token on file")
            return None
        try:
            payload = await _refresh(row.refresh_token)
        except httpx.HTTPError as e:
            log.warning("Spotify refresh failed: %s", e)
            return None
        row.access_token = payload["access_token"]
        if "refresh_token" in payload:
            row.refresh_token = payload["refresh_token"]
        row.expires_at = datetime.utcnow() + timedelta(
            seconds=int(payload.get("expires_in", 3600))
        )
        row.scope = payload.get("scope") or row.scope
        db.commit()
    return row.access_token


async def _get(
    client: httpx.AsyncClient,
    token: str,
    path: str,
    params: dict | None = None,
) -> dict | None:
    r = await client.get(
        f"{API_BASE}{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
    )
    if r.status_code == 204:
        return None  # no content — nothing currently playing
    if r.status_code == 401:
        log.warning("Spotify 401 on %s", path)
        return None
    r.raise_for_status()
    return r.json()


def _artists(artists: list[dict]) -> str:
    return ", ".join(a["name"] for a in artists if a.get("name"))


def _hours_this_week(recently_played: list[dict]) -> float:
    now = datetime.now(timezone.utc)
    monday = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    total_ms = 0
    for item in recently_played:
        played_at = item.get("played_at")
        if not played_at:
            continue
        try:
            t = datetime.fromisoformat(played_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t < monday:
            continue
        total_ms += int((item.get("track") or {}).get("duration_ms") or 0)
    return round(total_ms / 3_600_000, 1)


async def fetch_music_snapshot(db: Session) -> dict | None:
    token = await get_valid_access_token(db)
    if not token:
        return None

    async with httpx.AsyncClient(timeout=10.0) as client:
        playback = await _get(client, token, "/me/player")
        top = await _get(
            client, token, "/me/top/tracks", {"limit": 5, "time_range": "short_term"}
        )
        recent = await _get(
            client, token, "/me/player/recently-played", {"limit": 50}
        )

    payload: dict[str, Any] = {
        "playing": False,
        "title": "—",
        "artist": "—",
        "album": None,
        "cover_url": None,
        "progress_ms": 0,
        "duration_ms": 0,
        "top_tracks": [],
        "hours_this_week": 0,
    }

    if playback and playback.get("item"):
        item = playback["item"]
        payload["playing"] = bool(playback.get("is_playing"))
        payload["title"] = item.get("name") or "—"
        payload["artist"] = _artists(item.get("artists") or []) or "—"
        album = item.get("album") or {}
        payload["album"] = album.get("name")
        images = album.get("images") or []
        if images:
            payload["cover_url"] = images[0].get("url")
        payload["progress_ms"] = int(playback.get("progress_ms") or 0)
        payload["duration_ms"] = int(item.get("duration_ms") or 0)

    if top and top.get("items"):
        payload["top_tracks"] = [
            {"title": t.get("name"), "artist": _artists(t.get("artists") or [])}
            for t in top["items"][:5]
        ]

    if recent and recent.get("items"):
        payload["hours_this_week"] = _hours_this_week(recent["items"])

    return payload
