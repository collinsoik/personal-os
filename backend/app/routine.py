"""Email Routine digest ingest.

Cloud routine (3x/day) classifies Gmail and submits a digest payload either
via the HTTP endpoint (legacy, X-PO-Secret) or via the MCP tool exposed at
/mcp. Both paths land here in `persist_digest`, which writes to
CachedPayload(key='routine') and broadcasts the SSE 'routine' event.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

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


class DismissRequest(BaseModel):
    id: str
    action: str | None  # "done" | "snoozed" | null (null clears)


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


@router.post("/routine/dismiss")
def dismiss_item(req: DismissRequest, db: Session = Depends(get_session)) -> dict[str, Any]:
    if req.action not in (None, "done", "snoozed"):
        raise HTTPException(status_code=400, detail={"error": "action must be 'done', 'snoozed', or null"})

    row = db.get(models.CachedPayload, "routine")
    if row is None:
        raise HTTPException(status_code=404, detail={"error": "no_digest"})

    payload = row.payload
    found = False
    for bucket in ("urgent", "high", "fyi"):
        for item in payload.get(bucket) or []:
            if item.get("id") == req.id:
                if req.action is None:
                    item.pop("dismissed", None)
                else:
                    item["dismissed"] = req.action
                found = True
                break
        if found:
            break

    if not found:
        raise HTTPException(status_code=404, detail={"error": "id_not_found"})

    flag_modified(row, "payload")
    row.updated_at = datetime.utcnow()
    db.commit()
    events.broadcast("routine", payload)
    return {"ok": True}
