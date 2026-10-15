"""Shared-password login with stateless, HMAC-signed bearer tokens.

Token format: base64url(json payload) + "." + base64url(hmac_sha256(payload)).
Stdlib only - no JWT dependency for a single-claim token.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

from fastapi import Header, HTTPException, Request

from backend import config

# Fallback key for local development when auth is enabled but no secret was
# configured; tokens then simply stop validating after a server restart.
_signing_key = (config.SECRET_KEY or secrets.token_urlsafe(48)).encode()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: bytes) -> str:
    return _b64(hmac.new(_signing_key, payload, hashlib.sha256).digest())


def check_password(password: str) -> bool:
    return hmac.compare_digest(password.encode(), config.ACCESS_PASSWORD.encode())


def issue_token() -> tuple[str, int]:
    expires_at = int(time.time() + config.TOKEN_TTL_HOURS * 3600)
    payload = json.dumps({"exp": expires_at, "jti": secrets.token_hex(8)}).encode()
    return f"{_b64(payload)}.{_sign(payload)}", expires_at


def verify_token(token: str) -> dict | None:
    try:
        payload_b64, signature = token.split(".", 1)
        payload = _unb64(payload_b64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(signature, _sign(payload)):
        return None
    try:
        claims = json.loads(payload)
    except json.JSONDecodeError:
        return None
    if claims.get("exp", 0) < time.time():
        return None
    return claims


def require_auth(authorization: str | None = Header(default=None)) -> None:
    """FastAPI dependency guarding every /api route except login."""
    if not config.AUTH_ENABLED:
        return
    scheme, _, token = (authorization or "").partition(" ")
    claims = verify_token(token) if scheme.lower() == "bearer" else None
    if claims is None:
        raise HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def client_ip(request: Request) -> str:
    # Render (and most PaaS) terminate TLS at a proxy that appends the real client to
    # X-Forwarded-For. Read from the right: the leftmost entries are client-controlled.
    forwarded = [h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()]
    if forwarded and config.TRUSTED_PROXY_HOPS > 0:
        return forwarded[-min(config.TRUSTED_PROXY_HOPS, len(forwarded))]
    return request.client.host if request.client else "unknown"
