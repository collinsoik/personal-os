from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from . import models, poller
from .config import settings
from .control import router as control_router
from .dashboard import build_dashboard
from .db import get_session, init_db
from .deps import require_secret
from .events import router as events_router
from .mcp_server import mcp, mcp_app
from .oauth import router as oauth_router
from .routine import router as routine_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    poller.start()
    async with mcp.session_manager.run():
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
app.include_router(control_router, prefix="/api")
app.include_router(events_router, prefix="/api")
app.include_router(routine_router, prefix="/api")

app.mount("/mcp", mcp_app)


@app.get("/api/health")
def health():
    return {"ok": True, "now": datetime.utcnow().isoformat() + "Z"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_session)):
    return build_dashboard(db)


@app.post("/api/presence/ping")
def presence_ping(db: Session = Depends(get_session)):
    now = datetime.utcnow()
    row = db.get(models.CachedPayload, "presence")
    if row:
        row.payload = {"last_seen": now.isoformat() + "Z"}
        row.updated_at = now
    else:
        db.add(models.CachedPayload(key="presence", payload={"last_seen": now.isoformat() + "Z"}, updated_at=now))
    db.commit()
    return {"ok": True}


# Placeholder write route so we can smoke-test the shared-secret guard.
@app.post("/api/ping", dependencies=[Depends(require_secret)])
def ping():
    return {"pong": True}
