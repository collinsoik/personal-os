"""Google Calendar OAuth + API client.

OAuth flow mirrors spotify.py:
    build_authorize_url() -> redirect user here
    exchange_code(code)   -> /callback swaps code for tokens
    save_tokens(db, ...)  -> persists to OAuthToken (provider="google")
    get_valid_access_token(db) -> loads latest, refreshes if expiring

Snapshot:
    fetch_calendar_snapshot(db) -> dict matching the dashboard `calendar` shape
"""
from __future__ import annotations

import asyncio
import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote, urlencode
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from . import models
from .config import settings

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"

SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

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
        "client_id": settings().google_client_id,
        "response_type": "code",
        "redirect_uri": settings().google_redirect_uri,
        "scope": " ".join(SCOPES),
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def consume_state(state: str | None) -> bool:
    if not state:
        return False
    _purge_states()
    return _pending_states.pop(state, None) is not None


async def exchange_code(code: str) -> dict[str, Any]:
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": settings().google_redirect_uri,
        "client_id": settings().google_client_id,
        "client_secret": settings().google_client_secret,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(TOKEN_URL, data=data)
        r.raise_for_status()
        return r.json()


async def _refresh(refresh_token: str) -> dict[str, Any]:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": settings().google_client_id,
        "client_secret": settings().google_client_secret,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(TOKEN_URL, data=data)
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
        .filter_by(provider="google", account=account)
        .one_or_none()
    )
    if row is None:
        row = models.OAuthToken(provider="google", account=account)
        db.add(row)
    row.access_token = payload["access_token"]
    if payload.get("refresh_token"):
        row.refresh_token = payload["refresh_token"]
    row.expires_at = expires_at
    row.scope = payload.get("scope")
    db.commit()
    db.refresh(row)
    return row


async def get_valid_access_token(db: Session) -> str | None:
    row = (
        db.query(models.OAuthToken)
        .filter_by(provider="google")
        .order_by(models.OAuthToken.id.desc())
        .first()
    )
    if row is None:
        return None
    if row.expires_at and row.expires_at - timedelta(seconds=60) <= datetime.utcnow():
        if not row.refresh_token:
            log.warning("Google token expired and no refresh_token on file")
            return None
        try:
            payload = await _refresh(row.refresh_token)
        except httpx.HTTPError as e:
            log.warning("Google refresh failed: %s", e)
            return None
        row.access_token = payload["access_token"]
        # Google usually does NOT return a new refresh_token on refresh — keep the existing one.
        if payload.get("refresh_token"):
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
    if r.status_code == 401:
        log.warning("Google 401 on %s", path)
        return None
    r.raise_for_status()
    return r.json()


def _fmt_time(dt: datetime) -> tuple[str, str]:
    """Return (time_head, time_tail) — e.g. ("10:30", " AM")."""
    h = dt.hour % 12 or 12
    mm = f"{dt.minute:02d}"
    suffix = " AM" if dt.hour < 12 else " PM"
    return f"{h}:{mm}", suffix


def _parse_event_dt(value: str, tz: ZoneInfo) -> datetime:
    """Google returns RFC3339 with offset. Normalize to tz-aware in local tz."""
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(tz)


async def fetch_calendar_snapshot(db: Session) -> dict | None:
    token = await get_valid_access_token(db)
    if not token:
        return None

    tz = ZoneInfo(settings().personal_tz)
    now_local = datetime.now(tz)
    today = now_local.date()

    # Week window: Mon 00:00 → next Mon 00:00 (local).
    week_start_local = datetime.combine(
        today - timedelta(days=now_local.weekday()),
        datetime.min.time(),
        tz,
    )
    week_end_local = week_start_local + timedelta(days=7)
    today_start_local = datetime.combine(today, datetime.min.time(), tz)
    today_end_local = today_start_local + timedelta(days=1)

    time_min = week_start_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    time_max = week_end_local.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    async with httpx.AsyncClient(timeout=10.0) as client:
        cal_list = await _get(client, token, "/users/me/calendarList")
        if not cal_list:
            return None
        calendars = cal_list.get("items", [])

        async def fetch_cal(cal):
            cal_id = cal.get("id")
            if not cal_id:
                return cal, []
            data = await _get(
                client,
                token,
                f"/calendars/{quote(cal_id, safe='')}/events",
                {
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "maxResults": 100,
                },
            )
            return cal, (data or {}).get("items", []) or []

        results = await asyncio.gather(*(fetch_cal(c) for c in calendars))

    # One bucket per weekday (Mon..Sun). Each bucket collects events that start on that day.
    buckets: list[list[dict[str, Any]]] = [[] for _ in range(7)]

    def bucket_index(d) -> int | None:
        delta = (d - week_start_local.date()).days
        return delta if 0 <= delta < 7 else None

    for cal, items in results:
        cal_name = cal.get("summaryOverride") or cal.get("summary") or ""
        for ev in items:
            start = ev.get("start", {}) or {}
            end = ev.get("end", {}) or {}
            is_all_day = "date" in start and "dateTime" not in start

            if is_all_day:
                try:
                    start_date = datetime.fromisoformat(start["date"]).date()
                    end_date = datetime.fromisoformat(end["date"]).date()
                except (KeyError, ValueError):
                    continue
                # All-day event spans [start_date, end_date); add one entry per covered day in the week.
                cur = start_date
                while cur < end_date:
                    idx = bucket_index(cur)
                    if idx is not None:
                        buckets[idx].append({
                            "time_head": "All",
                            "time_tail": " day",
                            "title": ev.get("summary") or "(untitled)",
                            "desc": cal_name,
                            "now": False,
                            "_sort": datetime.combine(cur, datetime.min.time(), tz),
                        })
                    cur += timedelta(days=1)
            else:
                try:
                    start_dt = _parse_event_dt(start["dateTime"], tz)
                    end_dt = _parse_event_dt(end["dateTime"], tz)
                except (KeyError, ValueError):
                    continue

                idx = bucket_index(start_dt.date())
                if idx is None:
                    continue

                head, tail = _fmt_time(start_dt)
                is_now = start_dt <= now_local < end_dt
                desc_bits = []
                if cal_name:
                    desc_bits.append(cal_name)
                loc = ev.get("location")
                if loc:
                    desc_bits.append(loc)
                buckets[idx].append({
                    "time_head": head,
                    "time_tail": tail,
                    "title": ev.get("summary") or "(untitled)",
                    "desc": " · ".join(desc_bits),
                    "now": is_now,
                    "_sort": start_dt,
                })

    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = []
    for i in range(7):
        d = (week_start_local + timedelta(days=i)).date()
        bucket = sorted(buckets[i], key=lambda e: e["_sort"])
        for e in bucket:
            e.pop("_sort", None)
        days.append({
            "label": day_labels[i],
            "date": d.isoformat(),
            "is_today": d == today,
            "events": bucket,
        })

    return {
        "today_label": now_local.strftime("%A, %B ") + str(now_local.day),
        "days": days,
    }
