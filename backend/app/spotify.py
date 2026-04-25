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
    "user-modify-playback-state",
]


class ControlError(Exception):
    def __init__(self, msg: str, status: int = 500):
        super().__init__(msg)
        self.status = status

# In-memory CSRF states. Single-process uvicorn; restart mid-flow just means retry.
_pending_states: dict[str, float] = {}
_STATE_TTL_SEC = 600

# Set by `_get` on 429; `fetch_music_snapshot` short-circuits until this passes so
# we honor Retry-After without an extra timer (poller idles 30s on a None return).
_backoff_until: float = 0.0

# TTL caches for slow-moving endpoints. Refetching `/me/top/tracks` and
# `/me/player/recently-played` every 5s under the active poll cadence is what
# earns us the rate limit; these change at most every minute or two.
_top_cache: dict | None = None
_top_cache_at: float = 0.0
_TOP_TTL_SEC = 300

_recent_cache: dict | None = None
_recent_cache_at: float = 0.0
_RECENT_TTL_SEC = 60


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
    if r.status_code == 429:
        retry_after = int(r.headers.get("Retry-After", "5"))
        global _backoff_until
        _backoff_until = time.time() + retry_after
        log.warning("Spotify 429 on %s — backing off for %ds", path, retry_after)
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
    if time.time() < _backoff_until:
        return None

    token = await get_valid_access_token(db)
    if not token:
        return None

    global _top_cache, _top_cache_at, _recent_cache, _recent_cache_at
    now = time.time()

    async with httpx.AsyncClient(timeout=10.0) as client:
        playback = await _get(client, token, "/me/player")

        if _top_cache is None or now - _top_cache_at > _TOP_TTL_SEC:
            fresh = await _get(
                client, token, "/me/top/tracks", {"limit": 5, "time_range": "short_term"}
            )
            if fresh is not None:
                _top_cache = fresh
                _top_cache_at = now
        top = _top_cache

        if _recent_cache is None or now - _recent_cache_at > _RECENT_TTL_SEC:
            fresh = await _get(
                client, token, "/me/player/recently-played", {"limit": 50}
            )
            if fresh is not None:
                _recent_cache = fresh
                _recent_cache_at = now
        recent = _recent_cache

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


async def _control(db: Session, method: str, path: str) -> None:
    token = await get_valid_access_token(db)
    if not token:
        raise ControlError("no spotify token", status=401)
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.request(
            method,
            f"{API_BASE}{path}",
            headers={"Authorization": f"Bearer {token}"},
        )
    if r.status_code == 404:
        raise ControlError("no active device", status=409)
    if r.status_code == 403:
        raise ControlError("premium required", status=403)
    if r.status_code == 401:
        raise ControlError("spotify auth expired", status=401)
    r.raise_for_status()


async def play(db: Session) -> None:
    await _control(db, "PUT", "/me/player/play")


async def pause(db: Session) -> None:
    await _control(db, "PUT", "/me/player/pause")


async def next_track(db: Session) -> None:
    await _control(db, "POST", "/me/player/next")


async def previous_track(db: Session) -> None:
    await _control(db, "POST", "/me/player/previous")
