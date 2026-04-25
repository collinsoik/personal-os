from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


class OAuthToken(Base):
    __tablename__ = "oauth_tokens"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)  # google, spotify
    account: Mapped[str] = mapped_column(String(128))  # email or spotify user id
    access_token: Mapped[str] = mapped_column(Text)
    refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class CachedPayload(Base):
    """Generic cache slot for poller output (calendar, spotify, email, etc.)."""
    __tablename__ = "cached_payloads"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    payload: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Habit(Base):
    __tablename__ = "habits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)  # write, meditate, run, no-phone-am
    label: Mapped[str] = mapped_column(String(64))
    order: Mapped[int] = mapped_column(Integer, default=0)


class HabitTick(Base):
    __tablename__ = "habit_ticks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    habit_id: Mapped[int] = mapped_column(Integer, index=True)
    day: Mapped[str] = mapped_column(String(10), index=True)  # YYYY-MM-DD
    level: Mapped[int] = mapped_column(Integer, default=3)  # 0 miss, 1-3 strength


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(128))
    subtitle: Mapped[str | None] = mapped_column(String(256), nullable=True)
    due: Mapped[str | None] = mapped_column(String(32), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(String(256))
    done: Mapped[bool] = mapped_column(default=False)
    order: Mapped[int] = mapped_column(Integer, default=0)


class Reading(Base):
    __tablename__ = "reading"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256))
    author: Mapped[str] = mapped_column(String(128))
    page: Mapped[int] = mapped_column(Integer, default=0)
    total_pages: Mapped[int] = mapped_column(Integer, default=0)
    up_next: Mapped[str | None] = mapped_column(String(256), nullable=True)
    current: Mapped[bool] = mapped_column(default=True)


class HealthSnapshot(Base):
    __tablename__ = "health_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    payload: Mapped[dict] = mapped_column(JSON)


class OAuthInboundCode(Base):
    """Single-use authorization codes issued by /authorize, exchanged at /token."""
    __tablename__ = "oauth_inbound_codes"
    code: Mapped[str] = mapped_column(String(128), primary_key=True)
    redirect_uri: Mapped[str] = mapped_column(Text)
    code_challenge: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(128), default="mcp")
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    used: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OAuthInboundToken(Base):
    """Bearer access tokens minted by /token; presented on /mcp/* requests."""
    __tablename__ = "oauth_inbound_tokens"
    access_token: Mapped[str] = mapped_column(String(128), primary_key=True)
    refresh_token: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    scope: Mapped[str] = mapped_column(String(128), default="mcp")
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
