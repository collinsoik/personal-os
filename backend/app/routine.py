"""Email Routine digest ingest.

Cloud routine (3x/day) classifies Gmail and submits a digest payload either
via the HTTP endpoint (legacy, X-PO-Secret) or via the MCP tool exposed at
/mcp. Both paths land here in `persist_digest`, which writes to
CachedPayload(key='routine') and broadcasts the SSE 'routine' event.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import events, models
from .db import get_session
from .deps import require_secret

router = APIRouter(dependencies=[Depends(require_secret)])


class RoutineDigest(BaseModel):
    scanned: int = 0
    flagged: int = 0
    ranAt: str | None = None
    nextAt: str | None = None
    urgent: list[dict[str, Any]] = []
    high: list[dict[str, Any]] = []
    fyi: list[dict[str, Any]] = []


def persist_digest(db: Session, payload: dict[str, Any]) -> None:
    now = datetime.utcnow()
    row = db.get(models.CachedPayload, "routine")
    if row is None:
        db.add(models.CachedPayload(key="routine", payload=payload, updated_at=now))
    else:
        row.payload = payload
        row.updated_at = now
    db.commit()
    events.broadcast("routine", payload)


@router.post("/routine/digest")
def ingest_digest(digest: RoutineDigest, db: Session = Depends(get_session)) -> dict[str, Any]:
    persist_digest(db, digest.model_dump())
    return {"ok": True}
