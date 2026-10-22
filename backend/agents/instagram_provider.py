"""Chooses which Instagram client the Data Collector uses (INSTAGRAM_PROVIDER in backend/.env)."""

from __future__ import annotations

from typing import Any

from backend import config
from backend.agents.apify_instagram_client import ApifyInstagramClient
from backend.agents.instagram_client import InstagramClient


def make_client() -> Any:
    """Meta Business Discovery by default; Apify's scraper when INSTAGRAM_PROVIDER=apify."""
    if config.INSTAGRAM_PROVIDER == "apify":
        return ApifyInstagramClient(
            config.APIFY_API_TOKEN,
            actor=config.APIFY_INSTAGRAM_ACTOR,
            lookback_days=config.COLLECTOR_LOOKBACK_DAYS,
            refresh_days=config.INSTAGRAM_REFRESH_DAYS,
            results_limit=config.APIFY_RESULTS_LIMIT_PER_ACCOUNT,
            min_interval_minutes=config.APIFY_MIN_INTERVAL_MINUTES,
        )
    return InstagramClient(config.META_ACCESS_TOKEN, config.INSTAGRAM_BUSINESS_ACCOUNT_ID, config.META_GRAPH_API_VERSION)
