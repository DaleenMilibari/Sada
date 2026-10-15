"""Runtime configuration, read once from the environment (and backend/.env if present).

Every production-relevant knob lives here so deployment (see render.yaml) is
purely a matter of setting env vars - no code edits per environment.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv(dotenv_path=Path(__file__).parent / ".env")
except ImportError:
    pass


def _csv(value: str) -> list[str]:
    return [v.strip().rstrip("/") for v in value.split(",") if v.strip()]


ENV = os.environ.get("SADA_ENV", "development")
IS_PRODUCTION = ENV == "production"

CORS_ORIGINS = _csv(os.environ.get("CORS_ORIGINS", "http://localhost:5173"))

# Shared team password for the login screen. When unset outside production,
# auth is disabled so local development keeps working with zero setup.
ACCESS_PASSWORD = os.environ.get("SADA_ACCESS_PASSWORD", "")
SECRET_KEY = os.environ.get("SADA_SECRET_KEY", "")
TOKEN_TTL_HOURS = float(os.environ.get("SADA_TOKEN_TTL_HOURS", "12"))
AUTH_ENABLED = bool(ACCESS_PASSWORD)

# Per-client request budgets (requests / minute).
LLM_RATE_LIMIT_PER_MINUTE = int(os.environ.get("SADA_LLM_RATE_LIMIT_PER_MINUTE", "20"))
LOGIN_RATE_LIMIT_PER_MINUTE = int(os.environ.get("SADA_LOGIN_RATE_LIMIT_PER_MINUTE", "5"))
# Number of reverse proxies in front of the app that append to X-Forwarded-For
# (1 on Render). 0 = ignore the header and use the socket peer address.
TRUSTED_PROXY_HOPS = int(os.environ.get("SADA_TRUSTED_PROXY_HOPS", "0"))


def validate() -> None:
    """Fail fast at startup rather than serving an insecure production instance."""
    if not IS_PRODUCTION:
        return
    missing = [
        name
        for name, value in (("SADA_ACCESS_PASSWORD", ACCESS_PASSWORD), ("SADA_SECRET_KEY", SECRET_KEY))
        if not value
    ]
    if missing:
        raise RuntimeError(f"SADA_ENV=production requires: {', '.join(missing)}")
    if len(SECRET_KEY) < 32:
        raise RuntimeError("SADA_SECRET_KEY must be at least 32 characters in production.")
