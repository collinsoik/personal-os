"""Inbound OAuth 2.1 authorization server.

claude.ai's MCP connector flow expects standard OAuth 2.1 with PKCE and
a pre-registered client (no DCR). The user pastes our client_id +
client_secret into the connector form once; from then on, claude.ai
runs the authorization-code + PKCE flow against the endpoints below
and uses the issued bearer to call /mcp/.

Single-user, single-client — credentials are hardcoded in env. No
consent UI; /authorize auto-approves anything with a matching client_id.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from . import models
from .config import settings
from .db import get_session

router = APIRouter()

CODE_TTL = timedelta(minutes=10)
ACCESS_TOKEN_TTL = timedelta(hours=1)
REFRESH_TOKEN_TTL = timedelta(days=30)


def _issuer() -> str:
    """Issuer URL with a trailing slash."""
    iss = settings().oauth_issuer or ""
    return iss if iss.endswith("/") else iss + "/"


def _verify_pkce(verifier: str, challenge: str) -> bool:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    encoded = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return secrets.compare_digest(encoded, challenge)


def _verify_client(client_id: str | None, client_secret: str | None) -> None:
    cfg = settings()
    if not cfg.oauth_client_id or not cfg.oauth_client_secret:
        raise HTTPException(status_code=503, detail={"error": "server_misconfigured"})
    if client_id != cfg.oauth_client_id or client_secret != cfg.oauth_client_secret:
        raise HTTPException(status_code=401, detail={"error": "invalid_client"})


def _client_creds_from_request(
    request: Request,
    client_id_form: str | None,
    client_secret_form: str | None,
) -> tuple[str | None, str | None]:
    """Extract client credentials from Basic auth header or POST body."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(auth[6:]).decode("utf-8")
            cid, _, csec = decoded.partition(":")
            return cid, csec
        except Exception:
            return None, None
    return client_id_form, client_secret_form


@router.get("/.well-known/oauth-authorization-server")
def authorization_server_metadata() -> dict:
    base = _issuer().rstrip("/")
    return {
        "issuer": _issuer(),
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"],
        "scopes_supported": ["mcp"],
    }


@router.get("/.well-known/oauth-protected-resource/mcp")
def protected_resource_metadata() -> dict:
    base = _issuer().rstrip("/")
    return {
        "resource": f"{base}/mcp",
        "authorization_servers": [_issuer()],
        "scopes_supported": ["mcp"],
        "bearer_methods_supported": ["header"],
    }


@router.get("/authorize")
def authorize(
    request: Request,
    db: Session = Depends(get_session),
):
    params = request.query_params
    response_type = params.get("response_type")
    client_id = params.get("client_id")
    redirect_uri = params.get("redirect_uri")
    code_challenge = params.get("code_challenge")
    code_challenge_method = params.get("code_challenge_method")
    state = params.get("state", "")
    scope = params.get("scope", "mcp")

    if response_type != "code":
        raise HTTPException(status_code=400, detail={"error": "unsupported_response_type"})
    if client_id != settings().oauth_client_id:
        raise HTTPException(status_code=400, detail={"error": "invalid_client"})
    if not redirect_uri:
        raise HTTPException(status_code=400, detail={"error": "invalid_request", "error_description": "missing redirect_uri"})
    if not code_challenge or code_challenge_method != "S256":
        raise HTTPException(status_code=400, detail={"error": "invalid_request", "error_description": "PKCE S256 required"})

    code = secrets.token_urlsafe(32)
    db.add(
        models.OAuthInboundCode(
            code=code,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scope=scope,
            expires_at=datetime.utcnow() + CODE_TTL,
            used=False,
        )
    )
    db.commit()

    sep = "&" if "?" in redirect_uri else "?"
    target = f"{redirect_uri}{sep}code={code}"
    if state:
        target += f"&state={state}"
    return RedirectResponse(target, status_code=302)


def _mint_token_pair(db: Session, scope: str) -> dict:
    access = secrets.token_urlsafe(48)
    refresh = secrets.token_urlsafe(48)
    db.add(
        models.OAuthInboundToken(
            access_token=access,
            refresh_token=refresh,
            expires_at=datetime.utcnow() + ACCESS_TOKEN_TTL,
            scope=scope,
            revoked=False,
        )
    )
    db.commit()
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TOKEN_TTL.total_seconds()),
        "refresh_token": refresh,
        "scope": scope,
    }


@router.post("/token")
def token_endpoint(
    request: Request,
    grant_type: str = Form(...),
    code: str | None = Form(None),
    redirect_uri: str | None = Form(None),
    code_verifier: str | None = Form(None),
    refresh_token: str | None = Form(None),
    client_id: str | None = Form(None),
    client_secret: str | None = Form(None),
    db: Session = Depends(get_session),
):
    cid, csec = _client_creds_from_request(request, client_id, client_secret)
    _verify_client(cid, csec)

    if grant_type == "authorization_code":
        if not code or not code_verifier or not redirect_uri:
            raise HTTPException(status_code=400, detail={"error": "invalid_request"})
        row = db.get(models.OAuthInboundCode, code)
        if row is None or row.used or row.expires_at < datetime.utcnow():
            raise HTTPException(status_code=400, detail={"error": "invalid_grant"})
        if row.redirect_uri != redirect_uri:
            raise HTTPException(status_code=400, detail={"error": "invalid_grant", "error_description": "redirect_uri mismatch"})
        if not _verify_pkce(code_verifier, row.code_challenge):
            raise HTTPException(status_code=400, detail={"error": "invalid_grant", "error_description": "PKCE failed"})
        row.used = True
        db.commit()
        return _mint_token_pair(db, row.scope)

    if grant_type == "refresh_token":
        if not refresh_token:
            raise HTTPException(status_code=400, detail={"error": "invalid_request"})
        old = (
            db.query(models.OAuthInboundToken)
            .filter_by(refresh_token=refresh_token, revoked=False)
            .first()
        )
        if old is None:
            raise HTTPException(status_code=400, detail={"error": "invalid_grant"})
        # Rotate: revoke old token pair, mint a new one.
        old.revoked = True
        db.commit()
        return _mint_token_pair(db, old.scope)

    raise HTTPException(status_code=400, detail={"error": "unsupported_grant_type"})


def validate_access_token(db: Session, token: str) -> models.OAuthInboundToken | None:
    row = db.get(models.OAuthInboundToken, token)
    if row is None or row.revoked or row.expires_at < datetime.utcnow():
        return None
    return row
