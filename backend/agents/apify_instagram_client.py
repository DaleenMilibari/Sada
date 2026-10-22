"""Instagram client backed by Apify's Instagram Scraper (alternative to Meta Business Discovery).

It exposes the same surface the Instagram collector already uses, `media_page(username, after)`
and `calls`, and returns posts in the Graph API's shape, so instagram_collector.py needs no
changes. Enable it with INSTAGRAM_PROVIDER=apify and APIFY_API_TOKEN (see DEPLOYMENT.md section 3.6).

Differences from Business Discovery that matter:
- Works on any public account, not only business/creator ones.
- It is a scraper: it breaks Instagram's terms of use and can stop working whenever Instagram
  changes its pages. Meta's official API stays the default.
- Apify bills per result (about $2.70 per 1,000 on the free plan), and the collector runs every
  30 minutes, so each account is fetched at most once per APIFY_MIN_INTERVAL_MINUTES. Between
  fetches media_page() returns no posts, so the collector stores nothing new rather than
  duplicate snapshots.
- Hidden like counts arrive as -1 and are mapped to None. Missing is never stored as a number.
- Views (videoViewCount) are passed through as `video_view_count` but not stored yet: the
  collector's performance_index for Instagram is still likes + comments.

Run `python -m backend.agents.apify_instagram_client sbagovsa` for a one-account smoke test.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from backend.agents.instagram_client import (
    InstagramAccountNotFound,
    InstagramApiError,
    InstagramAuthError,
    InstagramRateLimited,
)

# The token travels in a header, but keep request URLs out of logs anyway.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_URL = "https://api.apify.com/v2"
DEFAULT_ACTOR = "apify~instagram-scraper"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_MEDIA_TYPES = {"Image": "IMAGE", "Video": "VIDEO", "Sidecar": "CAROUSEL_ALBUM"}


class ApifyInstagramClient:
    def __init__(
        self,
        api_token: str,
        *,
        actor: str = DEFAULT_ACTOR,
        lookback_days: int = 60,
        refresh_days: int = 7,
        results_limit: int = 300,
        min_interval_minutes: int = 360,
        http: httpx.Client | None = None,
        max_retries: int = 2,
        backoff_seconds: float = 2.0,
        now=lambda: datetime.now(timezone.utc),
    ):
        if not api_token:
            raise InstagramApiError("APIFY_API_TOKEN must be set.")
        self._token = api_token
        self._actor = actor
        self._lookback_days = lookback_days
        self._refresh_days = refresh_days
        self._results_limit = results_limit
        self._min_interval = timedelta(minutes=min_interval_minutes)
        # Actor runs can take a while; the sync endpoint itself caps at 5 minutes.
        self._http = http or httpx.Client(timeout=330)
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self._now = now
        self.calls = 0  # Apify actor runs, shown as "instagram_calls" in collector status
        self._seen: dict[str, tuple[datetime, dict[str, Any]]] = {}

    # -- Apify HTTP ---------------------------------------------------------------

    def _run_actor(self, actor_input: dict[str, Any]) -> list[dict[str, Any]]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                res = self._http.post(
                    f"{API_URL}/acts/{self._actor}/run-sync-get-dataset-items",
                    params={"format": "json", "clean": "true"},
                    headers={"Authorization": f"Bearer {self._token}"},
                    json=actor_input,
                )
            except httpx.TransportError as e:
                last_error = e
            else:
                self.calls += 1
                if res.status_code in (200, 201):
                    data = res.json()
                    return data if isinstance(data, list) else []
                if res.status_code in (401, 403):
                    raise InstagramAuthError("Apify API token is invalid or lacks access - create a new one in Apify Console.")
                if res.status_code in (402, 429):
                    raise InstagramRateLimited(f"Apify refused the run ({res.status_code}): out of credits or rate limited.")
                if res.status_code < 500:
                    raise InstagramApiError(f"Apify API error {res.status_code}: {_message(res)}")
                last_error = InstagramApiError(f"Apify API error {res.status_code}")
            if attempt < self._max_retries:
                time.sleep(self._backoff * (2**attempt))
        raise InstagramApiError(f"Apify request failed after {self._max_retries + 1} attempts: {last_error}")

    # -- Collector surface ----------------------------------------------------------

    def media_page(self, username: str, after: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
        """(account profile, posts newest-first, next cursor). The cursor is always None:
        one Apify run returns the whole window."""
        if not _USERNAME_RE.match(username):
            raise InstagramApiError(f"Invalid Instagram username: {username!r}")
        if after is not None:
            return self._seen.get(username, (None, {}))[1], [], None

        now = self._now()
        seen = self._seen.get(username)
        if seen and now - seen[0] < self._min_interval:
            return seen[1], [], None  # fetched recently: skip, to keep Apify spend down

        url = f"https://www.instagram.com/{username}/"
        details = self._run_actor({"directUrls": [url], "resultsType": "details", "resultsLimit": 1})
        profile = next((d for d in details if d.get("username") and not d.get("error")), None)
        if profile is None or not profile.get("id"):
            raise InstagramAccountNotFound(f"@{username} not found, private, or returned no profile data")
        account = {
            "id": str(profile["id"]),
            "username": profile["username"],
            "name": profile.get("fullName"),
            "followers_count": profile.get("followersCount"),
            "media_count": profile.get("postsCount"),
        }

        # The first fetch of an account in this process covers the full lookback window
        # (a backfill); later fetches only re-read recent posts, as Meta's flow does.
        days = self._refresh_days if seen else self._lookback_days
        newer_than = (now - timedelta(days=days)).date().isoformat()
        posts = self._run_actor(
            {
                "directUrls": [url],
                "resultsType": "posts",
                "resultsLimit": self._results_limit,
                "onlyPostsNewerThan": newer_than,
            }
        )
        items = [item for item in (_to_graph_item(p) for p in posts if not p.get("error")) if item]
        items.sort(key=lambda i: i["timestamp"], reverse=True)
        self._seen[username] = (now, account)
        return account, items, None


def _count(value: Any) -> int | None:
    """Apify reports hidden or unavailable counts as -1 or null. Never store those as numbers."""
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


def _to_graph_item(post: dict[str, Any]) -> dict[str, Any] | None:
    raw_ts = post.get("timestamp")
    post_id = post.get("id") or post.get("shortCode")
    if not raw_ts or not post_id:
        return None
    try:
        published = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    short_code = post.get("shortCode")
    return {
        "id": str(post_id),
        "caption": post.get("caption"),
        "media_type": _MEDIA_TYPES.get(post.get("type") or "", "IMAGE"),
        "media_product_type": "REELS" if post.get("productType") == "clips" else "FEED",
        "timestamp": published.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+0000"),
        "like_count": _count(post.get("likesCount")),
        "comments_count": _count(post.get("commentsCount")),
        "permalink": post.get("url") or (f"https://www.instagram.com/p/{short_code}/" if short_code else None),
        # Not stored by the collector yet; kept so views can be added without touching this client.
        "video_view_count": _count(post.get("videoViewCount") if post.get("videoViewCount") is not None else post.get("videoPlayCount")),
    }


def _message(res: httpx.Response) -> str:
    try:
        err = res.json().get("error") or {}
        return str(err.get("message", ""))
    except (ValueError, AttributeError):
        return ""


if __name__ == "__main__":
    import sys

    from backend import config

    if not config.APIFY_API_TOKEN:
        sys.exit("Set APIFY_API_TOKEN in backend/.env first (DEPLOYMENT.md section 3.6).")
    handle = sys.argv[1] if len(sys.argv) > 1 else "sbagovsa"
    client = ApifyInstagramClient(
        config.APIFY_API_TOKEN,
        actor=config.APIFY_INSTAGRAM_ACTOR,
        lookback_days=7,  # smoke test: keep the bill tiny
        results_limit=10,
    )
    try:
        account, items, _ = client.media_page(handle)
    except InstagramApiError as e:
        sys.exit(f"FAIL @{handle}: {e}")
    print(f"OK @{account['username']} | {account['name']} | {account['followers_count']} followers | {len(items)} posts in the last 7 days")
    for item in items[:5]:
        print(f"  {item['timestamp']}  likes={item['like_count']}  comments={item['comments_count']}  {item['media_product_type']}  {item['permalink']}")
