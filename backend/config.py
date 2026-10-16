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


# --- Database ----------------------------------------------------------------
# Render's Postgres sets DATABASE_URL; locally we fall back to a SQLite file.
_DEFAULT_SQLITE = Path(__file__).parent / "store" / "sada.db"
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{_DEFAULT_SQLITE.as_posix()}"

# --- Data Collector agent (YouTube) ------------------------------------------
YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
# Rolling window of uploads to track per channel (SBA channels hold ~276K videos in total).
COLLECTOR_LOOKBACK_DAYS = int(os.environ.get("COLLECTOR_LOOKBACK_DAYS", "60"))
COLLECTOR_MAX_VIDEOS_PER_CHANNEL = int(os.environ.get("COLLECTOR_MAX_VIDEOS_PER_CHANNEL", "3000"))
# YouTube API units one run may spend (free daily quota is 10,000).
COLLECTOR_QUOTA_PER_RUN = int(os.environ.get("COLLECTOR_QUOTA_PER_RUN", "600"))
# Videos per run whose rule-based topic is refined by Gemini (0 disables).
COLLECTOR_LLM_CLASSIFY_PER_RUN = int(os.environ.get("COLLECTOR_LLM_CLASSIFY_PER_RUN", "400"))

# --- Data Collector agent (Instagram, Graph API Business Discovery) ----------
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN", "")
# The id of *our own* Instagram business account that performs the lookups.
INSTAGRAM_BUSINESS_ACCOUNT_ID = os.environ.get("INSTAGRAM_BUSINESS_ACCOUNT_ID", "")
META_GRAPH_API_VERSION = os.environ.get("META_GRAPH_API_VERSION", "v23.0")
# Once an account's window is backfilled, each run re-reads only this many recent days.
INSTAGRAM_REFRESH_DAYS = int(os.environ.get("INSTAGRAM_REFRESH_DAYS", "7"))
INSTAGRAM_MAX_PAGES_PER_ACCOUNT = int(os.environ.get("INSTAGRAM_MAX_PAGES_PER_ACCOUNT", "10"))
# "meta" (official Graph API, the default) or "apify" (third-party scraper, see
# backend/agents/apify_instagram_client.py for the trade-offs).
INSTAGRAM_PROVIDER = os.environ.get("INSTAGRAM_PROVIDER", "meta").strip().lower()
APIFY_API_TOKEN = os.environ.get("APIFY_API_TOKEN", "")
APIFY_INSTAGRAM_ACTOR = os.environ.get("APIFY_INSTAGRAM_ACTOR", "apify~instagram-scraper")
APIFY_RESULTS_LIMIT_PER_ACCOUNT = int(os.environ.get("APIFY_RESULTS_LIMIT_PER_ACCOUNT", "300"))
# Apify bills per result, so each account is fetched at most this often (the collector itself runs more often).
APIFY_MIN_INTERVAL_MINUTES = int(os.environ.get("APIFY_MIN_INTERVAL_MINUTES", "360"))
if INSTAGRAM_PROVIDER == "apify":
    INSTAGRAM_ENABLED = bool(APIFY_API_TOKEN)
else:
    INSTAGRAM_ENABLED = bool(META_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID)

# In-process scheduler. Off by default so local reloads don't burn quota.
COLLECTOR_SCHEDULE_ENABLED = os.environ.get("COLLECTOR_SCHEDULE_ENABLED", "false").lower() == "true"
COLLECTOR_INTERVAL_MINUTES = int(os.environ.get("COLLECTOR_INTERVAL_MINUTES", "30"))


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
