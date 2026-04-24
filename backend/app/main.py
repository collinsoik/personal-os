from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import poller
from .config import settings
from .dashboard import build_dashboard
from .db import get_session, init_db
from .oauth import router as oauth_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    poller.start()
    try:
        yield
    finally:
        poller.stop()


app = FastAPI(title="Personal OS API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings().allowed_origins,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

app.include_router(oauth_router, prefix="/api")


def require_secret(x_po_secret: str | None = Header(default=None)):
    if x_po_secret != settings().write_secret:
        raise HTTPException(status_code=401, detail="bad secret")


@app.get("/api/health")
def health():
    return {"ok": True, "now": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_session)):
    return build_dashboard(db)


# Placeholder write route so we can smoke-test the shared-secret guard.
@app.post("/api/ping", dependencies=[Depends(require_secret)])
def ping():
    return {"pong": True}
