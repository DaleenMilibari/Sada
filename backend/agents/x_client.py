"""Thin X API v2 client for the Data Collector agent.

Uses an app-only bearer token from *our* developer account - no SBA login is
needed, because public accounts' posts and public metrics (impressions, likes,
replies, reposts) are readable by any app.

X bills pay-per-use, per resource returned: ~$0.005 per post read and ~$0.010
per user looked up. `posts_read` / `users_read` count what this client was
billed for, so the collector can enforce a hard budget.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx

# The bearer token travels in a header, but keep request URLs out of logs anyway.
logging.getLogger("httpx").setLevel(logging.WARNING)

API_URL = "https://api.x.com/2"
MIN_PAGE, MAX_PAGE = 5, 100  # bounds for max_results on the user timeline
ARCHIVE_MIN_PAGE = 10  # full-archive search returns at least 10 per call
ARCHIVE_MIN_INTERVAL_S = 1.1
TWEET_FIELDS = "created_at,public_metrics,entities,attachments,lang"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_ID_RE = re.compile(r"^[0-9]{1,25}$")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


class XApiError(RuntimeError):
    pass


class XAuthError(XApiError):
    """Bearer token invalid/revoked, or the account has no credits left - a person must fix it."""


class XRateLimited(XApiError):
    pass


class XClient:
    def __init__(
        self,
        bearer_token: str,
        http: httpx.Client | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        if not bearer_token:
            raise XApiError("X_BEARER_TOKEN must be set.")
        self._http = http or httpx.Client(timeout=20, headers={"Authorization": f"Bearer {bearer_token}"})
        if http is not None:
            self._http.headers["Authorization"] = f"Bearer {bearer_token}"
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self.calls = 0
        self.posts_read = 0
        self.users_read = 0
        self._last_archive_call = 0.0

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                res = self._http.get(f"{API_URL}{path}", params=params)
            except httpx.TransportError as e:
                last_error = e
            else:
                self.calls += 1
                if res.status_code == 200:
                    return res.json()
                if res.status_code in (401, 402, 403):
                    raise XAuthError(
                        f"X API refused the request ({res.status_code}): check X_BEARER_TOKEN and the "
                        f"account's credit balance in the developer console. {_detail(res)}".strip()
                    )
                if res.status_code == 429:
                    raise XRateLimited("X API rate limit reached.")
                if res.status_code < 500:
                    raise XApiError(f"X API error {res.status_code}: {_detail(res)}".strip())
                last_error = XApiError(f"X API error {res.status_code}")
            if attempt < self._max_retries:
                time.sleep(self._backoff * (2**attempt))
        raise XApiError(f"X request failed after {self._max_retries + 1} attempts: {last_error}")

    def users_by_username(self, usernames: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """One call for all accounts: ({lowercase username: user}, usernames X couldn't find)."""
        for u in usernames:
            if not _USERNAME_RE.match(u):
                raise XApiError(f"Invalid X username: {u!r}")
        data = self._get("/users/by", {"usernames": ",".join(usernames), "user.fields": "public_metrics,name"})
        users = data.get("data") or []
        self.users_read += len(users)
        found = {u["username"].lower(): u for u in users}
        missing = [u for u in usernames if u.lower() not in found]
        return found, missing

    def user_posts(
        self,
        user_id: str,
        max_results: int,
        *,
        start_time: datetime | None = None,
        since_id: str | None = None,
        until_id: str | None = None,
        pagination_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page of the account's own posts, newest first (no reposts or replies). Returns (posts, next token)."""
        if not all(_ID_RE.match(i) for i in (user_id, since_id, until_id) if i is not None):
            raise XApiError("Invalid X id")
        if pagination_token is not None and not _TOKEN_RE.match(pagination_token):
            raise XApiError("Invalid paging token")
        params: dict[str, Any] = {
            "max_results": max(MIN_PAGE, min(MAX_PAGE, max_results)),
            "exclude": "retweets,replies",
            "tweet.fields": TWEET_FIELDS,
        }
        if start_time is not None:
            params["start_time"] = start_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        if since_id is not None:
            params["since_id"] = since_id
        if until_id is not None:
            params["until_id"] = until_id
        if pagination_token is not None:
            params["pagination_token"] = pagination_token
        data = self._get(f"/users/{user_id}/tweets", params)
        posts = data.get("data") or []
        self.posts_read += len(posts)
        return posts, (data.get("meta") or {}).get("next_token")

    def archive_posts(
        self,
        username: str,
        max_results: int,
        *,
        start_time: datetime,
        end_time: datetime,
        pagination_token: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page of the account's own posts from full-archive search, newest first, published in [start_time, end_time).

        The user timeline only reaches an account's ~3,200 latest tweets (replies and reposts
        included), which for a busy news account is under two weeks; the archive goes further back.
        """
        if not _USERNAME_RE.match(username):
            raise XApiError(f"Invalid X username: {username!r}")
        if pagination_token is not None and not _TOKEN_RE.match(pagination_token):
            raise XApiError("Invalid paging token")
        wait = ARCHIVE_MIN_INTERVAL_S - (time.monotonic() - self._last_archive_call)
        if wait > 0:
            time.sleep(wait)  # full-archive search allows one request per second
        params: dict[str, Any] = {
            "query": f"from:{username} -is:retweet -is:reply",
            "max_results": max(ARCHIVE_MIN_PAGE, min(MAX_PAGE, max_results)),
            "start_time": start_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end_time": end_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tweet.fields": TWEET_FIELDS,
        }
        if pagination_token is not None:
            params["next_token"] = pagination_token
        try:
            data = self._get("/tweets/search/all", params)
        finally:
            self._last_archive_call = time.monotonic()
        posts = data.get("data") or []
        self.posts_read += len(posts)
        return posts, (data.get("meta") or {}).get("next_token")

    def replies(self, post_id: str, author_username: str, max_results: int) -> list[dict[str, Any]]:
        """One page of other people's replies to a post (recent search: posts from the last 7 days).

        Billed per reply returned. Only the reply text, time and likes are requested -
        no author expansion - so no one's identity is read or stored."""
        if not _ID_RE.match(post_id) or not _USERNAME_RE.match(author_username):
            raise XApiError("Invalid X id or username")
        data = self._get("/tweets/search/recent", {
            "query": f"conversation_id:{post_id} is:reply -from:{author_username}",
            "max_results": max(10, min(100, max_results)),
            "sort_order": "relevancy",
            "tweet.fields": "created_at,public_metrics,lang",
        })
        posts = data.get("data") or []
        self.posts_read += len(posts)
        return posts


def _detail(res: httpx.Response) -> str:
    try:
        body = res.json()
    except ValueError:
        return ""
    return str(body.get("detail") or body.get("title") or "")


def parse_timestamp(value: str | None) -> datetime | None:
    """X timestamps look like 2026-10-14T18:30:00.000Z."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
