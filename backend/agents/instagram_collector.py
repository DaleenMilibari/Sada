"""Instagram step of the Data Collector agent (see data_collector_agent.py).

For each official SBA Instagram account (backend/sba_channels.py), read posts
newest-first through Business Discovery and store them in the same `channels` /
`videos` / `video_snapshots` tables as YouTube, with platform = "instagram".

Decision logic:
- Until an account's lookback window is backfilled, page back to the cutoff.
- After that, only re-read the last INSTAGRAM_REFRESH_DAYS. Older posts barely
  move, and Business Discovery has a per-hour call limit.
Every post read gets a snapshot, so likes/comments velocity is available.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, insert, select
from sqlalchemy.engine import Engine

from backend import config, db
from backend.agents.instagram_client import (
    InstagramAccountNotFound,
    InstagramClient,
    parse_timestamp,
)
from backend.sba_channels import BY_ENTITY, SBA_INSTAGRAM_ACCOUNTS
from backend.topics import classify_by_rules

logger = logging.getLogger("sada.collector.instagram")

_CONTENT_TYPES = {"IMAGE": "image", "VIDEO": "video", "CAROUSEL_ALBUM": "carousel"}


def classify_content_type(item: dict[str, Any]) -> str:
    if item.get("media_product_type") == "REELS":
        return "short"
    return _CONTENT_TYPES.get(item.get("media_type", ""), "image")


def _int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None


def parse_media(item: dict[str, Any], channel_id: str, default_topic: str, now: datetime) -> dict[str, Any] | None:
    published = parse_timestamp(item.get("timestamp"))
    if published is None:
        return None
    caption = item.get("caption") or ""
    return {
        "video_id": item["id"],
        "platform": "instagram",
        "channel_id": channel_id,
        "title": caption,
        "url": item.get("permalink"),
        "published_at": published,
        "duration_seconds": None,
        "content_type": classify_content_type(item),
        "topic": classify_by_rules(caption, default_topic),
        "topic_source": "rule",
        "view_count": None,  # not exposed for accounts we don't own
        "like_count": _int_or_none(item.get("like_count")),  # absent when the account hides likes
        "comment_count": _int_or_none(item.get("comments_count")),
        "first_seen_at": now,
        "stats_updated_at": now,
    }


def _is_backfilled(engine: Engine, channel_id: str, cutoff: datetime) -> bool:
    with engine.connect() as conn:
        oldest = conn.execute(
            select(func.min(db.videos.c.published_at)).where(
                and_(db.videos.c.channel_id == channel_id, db.videos.c.platform == "instagram")
            )
        ).scalar()
    return oldest is not None and db.as_utc(oldest) <= cutoff + timedelta(days=1)


def _store(engine: Engine, account: dict[str, Any], entity_key: str, rows: list[dict[str, Any]], now: datetime) -> tuple[int, int]:
    spec = BY_ENTITY[entity_key]
    channel_row = {
        "channel_id": account["id"],
        "platform": "instagram",
        "entity_key": entity_key,
        "handle": f"@{account.get('username', '')}",
        "name_ar": spec["name_ar"],
        "title": account.get("name") or spec["name_ar"],
        "uploads_playlist_id": None,
        "subscriber_count": _int_or_none(account.get("followers_count")),
        "video_count": _int_or_none(account.get("media_count")),
        "view_count": None,
        "updated_at": now,
    }
    with engine.begin() as conn:
        db.upsert(conn, db.channels, [channel_row], "channel_id", [c for c in channel_row if c != "channel_id"])
        if not rows:
            return 0, 0
        ids = [r["video_id"] for r in rows]
        existing = set(conn.execute(select(db.videos.c.video_id).where(db.videos.c.video_id.in_(ids))).scalars())
        db.upsert(
            conn, db.videos, rows, "video_id",
            ["title", "url", "content_type", "like_count", "comment_count", "stats_updated_at"],
        )
        conn.execute(
            insert(db.video_snapshots),
            [
                {"video_id": r["video_id"], "captured_at": now, "view_count": None,
                 "like_count": r["like_count"], "comment_count": r["comment_count"]}
                for r in rows
            ],
        )
    new = sum(1 for r in rows if r["video_id"] not in existing)
    return new, len(rows) - new


def collect(engine: Engine, client: InstagramClient, now: datetime, cutoff: datetime) -> dict[str, Any]:
    """Collect every registered account. Per-account problems are reported, not raised;
    rate-limit and auth errors propagate so the caller can stop the Instagram step."""
    result = {"new": 0, "updated": 0, "errors": []}
    for entry in SBA_INSTAGRAM_ACCOUNTS:
        entity_key, username = entry["entity_key"], entry["username"]
        default_topic = BY_ENTITY[entity_key]["default_topic"]
        try:
            account, items, after = client.media_page(username)
        except InstagramAccountNotFound:
            msg = f"instagram @{username}: not found or not a business account"
            logger.warning(msg)
            result["errors"].append(msg)
            continue

        stop_at = cutoff if not _is_backfilled(engine, account["id"], cutoff) else max(
            cutoff, now - timedelta(days=config.INSTAGRAM_REFRESH_DAYS)
        )
        rows: list[dict[str, Any]] = []
        pages = 1
        while True:
            reached_stop = False
            for item in items:
                row = parse_media(item, account["id"], default_topic, now)
                if row is None:
                    continue
                if row["published_at"] < stop_at:
                    reached_stop = True
                    break
                rows.append(row)
            if reached_stop or not after or pages >= config.INSTAGRAM_MAX_PAGES_PER_ACCOUNT:
                break
            _, items, after = client.media_page(username, after)
            pages += 1

        new, updated = _store(engine, account, entity_key, rows, now)
        result["new"] += new
        result["updated"] += updated
    return result
