"""Email Routine digest ingest.

Cloud routine (3x/day) classifies Gmail and POSTs a digest payload here.
Persisted in CachedPayload(key='routine'); served via /api/dashboard and
broadcast over SSE so the frontend can re-render without polling.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from . import events, models
from .db import get_session
from .deps import require_secret

router = APIRouter(dependencies=[Depends(require_secret)])


class RoutineItem(BaseModel):
    id: str
    from_: str = Field(alias="from")
    subject: str
    summary: str | None = None
    action: str | None = None
    time: str | None = None
    mono: str | None = None
    tone: str | None = None

    class Config:
        populate_by_name = True


class RoutineDigest(BaseModel):
    scanned: int = 0
    flagged: int = 0
    ranAt: str | None = None
    nextAt: str | None = None
    urgent: list[dict[str, Any]] = []
    high: list[dict[str, Any]] = []
    fyi: list[dict[str, Any]] = []


@router.post("/routine/digest")
def ingest_digest(digest: RoutineDigest, db: Session = Depends(get_session)) -> dict[str, Any]:
    payload = digest.model_dump()
    now = datetime.utcnow()
    row = db.get(models.CachedPayload, "routine")
    if row is None:
        db.add(models.CachedPayload(key="routine", payload=payload, updated_at=now))
    else:
        row.payload = payload
        row.updated_at = now
    db.commit()
    events.broadcast("routine", payload)
    return {"ok": True}
