"""MCP server exposing write tools for cloud routines.

Cloud routines run in a sandbox that blocks outbound `curl` to unknown hosts,
but MCP traffic flows through Anthropic's connector layer (already
allowlisted). This server is mounted at /mcp by main.py and gated by a
bearer-token check on the same path.
"""
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import settings
from .db import SessionLocal
from .routine import RoutineDigest, persist_digest


mcp = FastMCP("personal-os", streamable_http_path="/")


@mcp.tool()
def submit_routine_digest(digest: RoutineDigest) -> dict[str, Any]:
    """Submit an email-routine digest to the Personal OS dashboard.

    Persists the digest to the backend cache and broadcasts an SSE event so
    the dashboard re-renders without polling. Returns {"ok": true} on
    success. Empty buckets are valid — pass empty arrays for any of urgent,
    high, or fyi when there's nothing to report.

    Digest fields:
        scanned: total messages scanned this run.
        flagged: urgent.length + high.length.
        ranAt: RFC3339 UTC timestamp of this run.
        nextAt: RFC3339 UTC timestamp of the next scheduled run (10/16/22 UTC).
        urgent[]: items needing action within ~24h. Each:
            {id, from, subject, summary, action, time}.
        high[]: items needing attention this week. Each:
            {id, from, subject, summary, time}.
        fyi[]: informational items. Each: {id, from, subject, time}.
    """
    with SessionLocal() as db:
        persist_digest(db, digest.model_dump())
    return {"ok": True}


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Gate every MCP request on Authorization: Bearer <PERSONAL_OS_MCP_TOKEN>."""

    async def dispatch(self, request, call_next):
        token = settings().mcp_token
        if not token:
            return JSONResponse({"error": "mcp_token_unset"}, status_code=503)
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {token}":
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


mcp_app = mcp.streamable_http_app()
mcp_app.add_middleware(BearerAuthMiddleware)
