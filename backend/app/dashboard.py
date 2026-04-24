"""First-cut /api/dashboard.

Returns the same shape the frontend currently hard-codes, populated from
whatever we have: manual-CRUD tables for habits/projects/reading, cached
payloads for calendar/music/email/vitals/thought. Missing integrations
fall back to placeholder/empty structures so the frontend can render.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from . import models

PRESENCE_WINDOW = timedelta(seconds=120)


def _cached(db: Session, key: str) -> dict[str, Any] | None:
    row = db.get(models.CachedPayload, key)
    return row.payload if row else None


def build_dashboard(db: Session) -> dict[str, Any]:
    now = datetime.now().astimezone()

    calendar = _cached(db, "calendar") or {
        "today_label": now.strftime("%A, %B %-d"),
        "days": [],
    }
    music = _cached(db, "spotify") or {
        "playing": False,
        "title": "—",
        "artist": "—",
        "progress_ms": 0,
        "duration_ms": 0,
        "top_tracks": [],
        "hours_this_week": 0,
    }
    email = _cached(db, "email") or {"unread": 0, "items": []}
    vitals = _cached(db, "health") or {
        "steps": None,
        "heart_bpm": None,
        "sleep_hours": None,
        "hrv_ms": None,
        "water_l": None,
        "rings": {"move": None, "exercise": None, "stand": None},
    }
    thought = _cached(db, "thought") or {"text": None, "author": None, "source": None}

    # Manual CRUD tables
    habits_rows = db.query(models.Habit).order_by(models.Habit.order).all()
    habit_ticks = db.query(models.HabitTick).all()
    ticks_by_habit: dict[int, list[dict[str, Any]]] = {}
    for t in habit_ticks:
        ticks_by_habit.setdefault(t.habit_id, []).append({"day": t.day, "level": t.level})
    habits = [
        {
            "key": h.key,
            "label": h.label,
            "ticks": sorted(ticks_by_habit.get(h.id, []), key=lambda x: x["day"]),
        }
        for h in habits_rows
    ]

    project = (
        db.query(models.Project).filter_by(active=True).order_by(models.Project.id.desc()).first()
    )
    project_payload: dict[str, Any] | None = None
    if project:
        tasks = (
            db.query(models.Task)
            .filter_by(project_id=project.id)
            .order_by(models.Task.order)
            .all()
        )
        done = sum(1 for t in tasks if t.done)
        project_payload = {
            "id": project.id,
            "title": project.title,
            "subtitle": project.subtitle,
            "due": project.due,
            "progress": round((done / len(tasks)) * 100) if tasks else 0,
            "tasks": [
                {"id": t.id, "label": t.label, "done": t.done} for t in tasks
            ],
        }

    reading_row = (
        db.query(models.Reading).filter_by(current=True).order_by(models.Reading.id.desc()).first()
    )
    reading = None
    if reading_row:
        pct = (
            round((reading_row.page / reading_row.total_pages) * 100)
            if reading_row.total_pages
            else 0
        )
        reading = {
            "title": reading_row.title,
            "author": reading_row.author,
            "page": reading_row.page,
            "total_pages": reading_row.total_pages,
            "progress": pct,
            "up_next": reading_row.up_next,
        }

    presence_row = db.get(models.CachedPayload, "presence")
    last_seen = presence_row.updated_at if presence_row else None
    presence = {
        "online": bool(last_seen and (datetime.utcnow() - last_seen) < PRESENCE_WINDOW),
        "last_seen": last_seen.isoformat() + "Z" if last_seen else None,
    }

    return {
        "now": now.isoformat(),
        "calendar": calendar,
        "music": music,
        "email": email,
        "vitals": vitals,
        "thought": thought,
        "habits": habits,
        "project": project_payload,
        "reading": reading,
        "presence": presence,
    }
