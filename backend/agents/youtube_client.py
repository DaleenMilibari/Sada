"""Thin YouTube Data API v3 client used by the Data Collector agent.

Every method here costs 1 quota unit per call (channels.list, playlistItems.list,
videos.list). The client counts units spent so the agent can stay inside its
per-run budget, retries transient failures, and raises QuotaExceeded as soon as
Google reports the daily quota is gone.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Iterator

import httpx

# The API key travels in the query string, and httpx logs full request URLs at
# INFO - keep it out of server logs.
logging.getLogger("httpx").setLevel(logging.WARNING)

BASE_URL = "https://www.googleapis.com/youtube/v3"
MAX_IDS_PER_CALL = 50


class YouTubeApiError(RuntimeError):
    pass


class CommentsDisabled(YouTubeApiError):
    """The video's owner turned comments off."""


class QuotaExceeded(YouTubeApiError):
    pass


class YouTubeClient:
    def __init__(self, api_key: str, http: httpx.Client | None = None, max_retries: int = 3, backoff_seconds: float = 1.0):
        if not api_key:
            raise YouTubeApiError("YOUTUBE_API_KEY is not set.")
        self._key = api_key
        self._http = http or httpx.Client(timeout=20)
        self._max_retries = max_retries
        self._backoff = backoff_seconds
        self.units_used = 0

    def _get(self, resource: str, params: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                res = self._http.get(f"{BASE_URL}/{resource}", params={**params, "key": self._key})
            except httpx.TransportError as e:
                last_error = e
            else:
                self.units_used += 1
                if res.status_code == 200:
                    return res.json()
                reason = _error_reason(res)
                if res.status_code == 403 and reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded"):
                    raise QuotaExceeded(f"YouTube quota exhausted ({reason}).")
                if res.status_code == 403 and reason == "commentsDisabled":
                    raise CommentsDisabled("Comments are disabled for this video.")
                if res.status_code < 500 and res.status_code != 429:
                    raise YouTubeApiError(f"{resource} failed: HTTP {res.status_code} {reason or ''}".strip())
                last_error = YouTubeApiError(f"{resource} failed: HTTP {res.status_code}")
            if attempt < self._max_retries:
                time.sleep(self._backoff * (2**attempt))
        raise YouTubeApiError(f"{resource} failed after {self._max_retries + 1} attempts: {last_error}")

    def channel_by_handle(self, handle: str) -> dict[str, Any] | None:
        data = self._get(
            "channels", {"part": "snippet,statistics,contentDetails", "forHandle": handle.lstrip("@")}
        )
        items = data.get("items") or []
        return items[0] if items else None

    def iter_uploads(self, playlist_id: str) -> Iterator[dict[str, Any]]:
        """Yield {videoId, videoPublishedAt} newest-first, one page (1 unit) at a time."""
        page_token: str | None = None
        while True:
            params = {"part": "contentDetails", "playlistId": playlist_id, "maxResults": MAX_IDS_PER_CALL}
            if page_token:
                params["pageToken"] = page_token
            data = self._get("playlistItems", params)
            for item in data.get("items") or []:
                yield item["contentDetails"]
            page_token = data.get("nextPageToken")
            if not page_token:
                return

    def videos(self, video_ids: list[str]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for i in range(0, len(video_ids), MAX_IDS_PER_CALL):
            batch = video_ids[i : i + MAX_IDS_PER_CALL]
            data = self._get(
                "videos",
                {"part": "snippet,statistics,contentDetails,liveStreamingDetails", "id": ",".join(batch), "maxResults": MAX_IDS_PER_CALL},
            )
            out.extend(data.get("items") or [])
        return out


def top_comments(client: YouTubeClient, video_id: str, max_results: int = 100) -> list[dict[str, Any]]:
    """One commentThreads.list call (1 unit): the video's most relevant top-level comments.

    Returns {comment_id, text, published_at, like_count} only - author fields are dropped here,
    so they never reach the database."""
    data = client._get(
        "commentThreads",
        {"part": "snippet", "videoId": video_id, "order": "relevance", "textFormat": "plainText",
         "maxResults": max(1, min(100, max_results))},
    )
    out = []
    for item in data.get("items") or []:
        s = item["snippet"]["topLevelComment"]["snippet"]
        out.append({
            "comment_id": item["id"],
            "text": s.get("textDisplay") or "",
            "published_at": s.get("publishedAt"),
            "like_count": s.get("likeCount"),
        })
    return out


def _error_reason(res: httpx.Response) -> str | None:
    try:
        errors = res.json()["error"]["errors"]
        return errors[0].get("reason")
    except (ValueError, KeyError, IndexError, TypeError):
        return None


_DURATION_RE = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?")


def parse_duration(iso: str | None) -> int | None:
    """ISO-8601 duration ("PT1H2M3S", "P1DT2H") -> seconds."""
    if not iso:
        return None
    m = _DURATION_RE.fullmatch(iso)
    if not m:
        return None
    d, h, mi, s = (int(x) if x else 0 for x in m.groups())
    return d * 86400 + h * 3600 + mi * 60 + s
