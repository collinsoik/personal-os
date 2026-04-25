"""Server-Sent Events pub/sub.

One asyncio.Queue per subscriber. Callers (control routes, pollers) invoke
`broadcast(name, data)`; `GET /api/events` opens a long-lived SSE stream.

Single-process uvicorn, single event loop — no Redis needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from . import models
from .db import SessionLocal

log = logging.getLogger(__name__)
router = APIRouter()

_QUEUE_MAX = 8
_subscribers: set[asyncio.Queue[tuple[str, Any]]] = set()


def subscribe() -> asyncio.Queue[tuple[str, Any]]:
    q: asyncio.Queue[tuple[str, Any]] = asyncio.Queue(maxsize=_QUEUE_MAX)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue[tuple[str, Any]]) -> None:
    _subscribers.discard(q)


def broadcast(name: str, data: Any) -> None:
    """Non-blocking fan-out. Drops events for slow subscribers."""
    for q in list(_subscribers):
        try:
            q.put_nowait((name, data))
        except asyncio.QueueFull:
            log.warning("SSE queue full; dropping event for one subscriber")


def _format(name: str, data: Any) -> str:
    return f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _current_snapshot(key: str) -> Any | None:
    with SessionLocal() as db:  # type: Session
        row = db.get(models.CachedPayload, key)
        return row.payload if row else None


async def _stream(request: Request):
    q = subscribe()
    try:
        # Replay the latest cached snapshots immediately so late joiners
        # don't see a blank card.
        initial = _current_snapshot("spotify")
        if initial is not None:
            yield _format("music", initial)
        routine_snap = _current_snapshot("routine")
        if routine_snap is not None:
            yield _format("routine", routine_snap)

        # Heartbeat + event loop. The heartbeat keeps intermediaries (Cloudflare,
        # etc.) from closing the connection during idle periods.
        while True:
            if await request.is_disconnected():
                return
            try:
                name, data = await asyncio.wait_for(q.get(), timeout=20.0)
                yield _format(name, data)
            except asyncio.TimeoutError:
                yield ": heartbeat\n\n"
    finally:
        unsubscribe(q)


@router.get("/events")
async def events(request: Request):
    return StreamingResponse(
        _stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # disable nginx buffering if present
            "Connection": "keep-alive",
        },
    )
