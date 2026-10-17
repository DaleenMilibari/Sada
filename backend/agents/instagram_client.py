"""Thin Instagram Graph API client (Business Discovery) for the Data Collector agent.

Business Discovery lets *our* Instagram business account read another
business/creator account's public profile and posts: followers, captions,
timestamps, likes (unless hidden) and comment counts. It does not expose
views, reach or shares for accounts we don't own.

Setup (Meta app, token, our account id) is described in DEPLOYMENT.md section 3.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any

import httpx

# The access token travels in the query string - keep request URLs out of logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

GRAPH_URL = "https://graph.facebook.com"
PAGE_SIZE = 50
MEDIA_FIELDS = "id,caption,media_type,media_product_type,timestamp,like_count,comments_count,permalink"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")

# https://developers.facebook.com/docs/graph-api/guides/error-handling
_RATE_LIMIT_CODES = {4, 17, 32, 613, 80002}
_AUTH_CODES = {102, 190}
_NOT_FOUND_SUBCODES = {2207013}


class InstagramApiError(RuntimeError):
    pass


class InstagramAuthError(InstagramApiError):
    """Token expired/revoked - a person must generate a new one."""


class InstagramRateLimited(InstagramApiError):
    pass


class InstagramAccountNotFound(InstagramApiError):
    """Username doesn't exist or isn't a business/creator account."""


class InstagramClient:
    def __init__(
        self,
        access_token: str,
        business_account_id: str,
        api_version: str,
        http: httpx.Client | None = None,
        max_retries: int = 3,
        backoff_seconds: float = 1.0,
    ):
        if not access_token or not business_account_id:
            raise InstagramApiError("META_ACCESS_TOKEN and INSTAGRAM_BUSINESS_ACCOUNT_ID must both be set.")
        self._token = access_token
        self._account_id = business_account_id
        self._version = api_version
        self._http = http or httpx.Client(timeout=20)
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self.calls = 0

    def _get(self, fields: str) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                res = self._http.get(
                    f"{GRAPH_URL}/{self._version}/{self._account_id}",
                    params={"fields": fields, "access_token": self._token},
                )
            except httpx.TransportError as e:
                last_error = e
            else:
                self.calls += 1
                if res.status_code == 200:
                    return res.json()
                err = _error(res)
                code, subcode = err.get("code"), err.get("error_subcode")
                if code in _AUTH_CODES:
                    raise InstagramAuthError("Instagram access token is invalid or expired - generate a new one (DEPLOYMENT.md section 3).")
                if code in _RATE_LIMIT_CODES:
                    raise InstagramRateLimited(f"Instagram API rate limit reached (code {code}).")
                if subcode in _NOT_FOUND_SUBCODES or code == 110:
                    raise InstagramAccountNotFound(err.get("message", "account not found"))
                if res.status_code < 500:
                    raise InstagramApiError(f"Instagram API error {res.status_code}: {err.get('message', '')}".strip())
                last_error = InstagramApiError(f"Instagram API error {res.status_code}")
            if attempt < self._max_retries:
                time.sleep(self._backoff * (2**attempt))
        raise InstagramApiError(f"Instagram request failed after {self._max_retries + 1} attempts: {last_error}")

    def media_page(self, username: str, after: str | None = None) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
        """One call: (account profile, up to PAGE_SIZE posts newest-first, cursor for the next page or None)."""
        if not _USERNAME_RE.match(username):
            raise InstagramApiError(f"Invalid Instagram username: {username!r}")
        if after is not None and not re.fullmatch(r"[A-Za-z0-9_=-]+", after):
            raise InstagramApiError("Invalid paging cursor")
        media_edge = f"media.after({after}).limit({PAGE_SIZE})" if after else f"media.limit({PAGE_SIZE})"
        data = self._get(
            f"business_discovery.username({username}){{id,username,name,followers_count,media_count,{media_edge}{{{MEDIA_FIELDS}}}}}"
        )
        account = data.get("business_discovery") or {}
        media = account.pop("media", None) or {}
        paging = media.get("paging") or {}
        next_after = paging.get("cursors", {}).get("after") if paging.get("next") else None
        return account, media.get("data") or [], next_after


def _error(res: httpx.Response) -> dict[str, Any]:
    try:
        return res.json().get("error") or {}
    except ValueError:
        return {}


def parse_timestamp(value: str | None) -> datetime | None:
    """Instagram timestamps look like 2026-10-14T18:30:00+0000."""
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S%z")
