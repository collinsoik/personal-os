"""Shared FastAPI dependencies."""
from fastapi import Header, HTTPException

from .config import settings


def require_secret(x_po_secret: str | None = Header(default=None)) -> None:
    if x_po_secret != settings().write_secret:
        raise HTTPException(status_code=401, detail="bad secret")
