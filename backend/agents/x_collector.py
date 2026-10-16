"""X step of the Data Collector agent (see data_collector_agent.py).

For each official SBA X account (backend/sba_channels.py), read the account's
own posts (no reposts/replies) and store them in the same `channels` /
`videos` / `video_snapshots` tables as YouTube, with platform = "x".

X bills per post returned, so this step is built to read every post ONCE:
- Newer posts: only posts newer than the newest one stored (`since_id`).
- Older posts: until an account's stored posts reach the lookback cutoff, keep
  paging back from the oldest one stored (`until_id`). On the first run both
  are the same thing: a backfill from now back to the cutoff.
- Per run, an account reads at most X_MAX_POSTS_PER_ACCOUNT posts (newer first).
  Stored posts are never re-read, so their metrics are as of collection time.
- Every page is stored as soon as it arrives, so posts already billed are kept
  even if the credit runs out mid-account.
- Hard budget: a run reads at most X_MAX_POSTS_PER_RUN posts, and all runs
  together at most X_TOTAL_POST_BUDGET (counted from the stored X snapshots,
  one per post read). Account ids are looked up once and then reused from the
  database, since user lookups are billed too.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.engine import Engine

from backend import config, db
from backend.agents.x_client import MIN_PAGE, XClient, parse_timestamp
from backend.sba_channels import BY_ENTITY, SBA_X_ACCOUNTS
from backend.topics import classify_by_rules

logger = logging.getLogger("sada.collector.x")

# Follower counts are re-read once a day (a billed user lookup, ~$0.01 per account).
FOLLOWER_REFRESH_EVERY = timedelta(hours=24)

# Attached media show up in entities.urls as .../status/<id>/photo/1 or .../video/1.
_MEDIA_URL_RE = re.compile(r"/status/\d+/(photo|video)/\d+$")


def classify_content_type(post: dict[str, Any]) -> str:
    kinds = [
        m.group(1)
        for u in (post.get("entities") or {}).get("urls") or []
        if (m := _MEDIA_URL_RE.search(u.get("expanded_url") or ""))
    ]
    if "video" in kinds:
        return "video"
    if len(kinds) > 1:
        return "carousel"
    if kinds or (post.get("attachments") or {}).get("media_keys"):
        return "image"
    return "text"


def _int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None


def parse_post(post: dict[str, Any], channel_id: str, username: str, default_topic: str, now: datetime) -> dict[str, Any] | None:
    published = parse_timestamp(post.get("created_at"))
    if published is None:
        return None
    text = post.get("text") or ""
    metrics = post.get("public_metrics") or {}
    return {
        "video_id": post["id"],
        "platform": "x",
        "channel_id": channel_id,
        "title": text,
        "url": f"https://x.com/{username}/status/{post['id']}",
        "published_at": published,
        "duration_seconds": None,
        "content_type": classify_content_type(post),
        "topic": classify_by_rules(text, default_topic),
        "topic_source": "rule",
        "view_count": _int_or_none(metrics.get("impression_count")),  # X "views" = impressions
        "like_count": _int_or_none(metrics.get("like_count")),
        "comment_count": _int_or_none(metrics.get("reply_count")),
        "first_seen_at": now,
        "stats_updated_at": now,
    }


def posts_read_so_far(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(func.count())
            .select_from(db.video_snapshots.join(db.videos, db.video_snapshots.c.video_id == db.videos.c.video_id))
            .where(db.videos.c.platform == "x")
        ).scalar() or 0


def _stored_accounts(engine: Engine) -> dict[str, dict[str, Any]]:
    """entity_key -> stored channel row, so ids aren't looked up (and billed) again."""
    with engine.connect() as conn:
        return {r.entity_key: r._asdict() for r in conn.execute(select(db.channels).where(db.channels.c.platform == "x"))}


def _edge_post(engine: Engine, channel_id: str, newest: bool) -> tuple[str, datetime] | None:
    """(id, published_at) of the account's newest or oldest stored post."""
    order = db.videos.c.published_at.desc() if newest else db.videos.c.published_at.asc()
    with engine.connect() as conn:
        row = conn.execute(
            select(db.videos.c.video_id, db.videos.c.published_at)
            .where(db.videos.c.channel_id == channel_id)
            .order_by(order)
            .limit(1)
        ).first()
    return (row.video_id, db.as_utc(row.published_at)) if row else None


def _store_channel(engine: Engine, user: dict[str, Any], entity_key: str, now: datetime) -> None:
    spec = BY_ENTITY[entity_key]
    metrics = user.get("public_metrics") or {}
    row = {
        "channel_id": user["id"],
        "platform": "x",
        "entity_key": entity_key,
        "handle": f"@{user['username']}",
        "name_ar": spec["name_ar"],
        "title": user.get("name") or spec["name_ar"],
        "uploads_playlist_id": None,
        "subscriber_count": _int_or_none(metrics.get("followers_count")),
        "video_count": _int_or_none(metrics.get("tweet_count")),
        "view_count": None,
        "updated_at": now,
    }
    with engine.begin() as conn:
        db.upsert(conn, db.channels, [row], "channel_id", [c for c in row if c != "channel_id"])
        db.record_followers(conn, [row], now)


def _store_posts(engine: Engine, rows: list[dict[str, Any]], now: datetime) -> tuple[int, int]:
    if not rows:
        return 0, 0
    with engine.begin() as conn:
        ids = [r["video_id"] for r in rows]
        existing = set(conn.execute(select(db.videos.c.video_id).where(db.videos.c.video_id.in_(ids))).scalars())
        db.upsert(
            conn, db.videos, rows, "video_id",
            ["title", "url", "content_type", "view_count", "like_count", "comment_count", "stats_updated_at"],
        )
        conn.execute(
            insert(db.video_snapshots),
            [
                {"video_id": r["video_id"], "captured_at": now, "view_count": r["view_count"],
                 "like_count": r["like_count"], "comment_count": r["comment_count"]}
                for r in rows
            ],
        )
    new = sum(1 for r in rows if r["video_id"] not in existing)
    return new, len(rows) - new


def collect(engine: Engine, client: XClient, now: datetime, cutoff: datetime, result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Collect every registered account within the post budget. Per-account problems are
    reported, not raised; auth and rate-limit errors propagate so the caller stops the X step.
    Pass `result` to keep the counts of posts stored before such an error."""
    result = result if result is not None else {}
    result.update({"new": 0, "updated": 0, "errors": []})
    remaining = min(config.X_MAX_POSTS_PER_RUN, config.X_TOTAL_POST_BUDGET - posts_read_so_far(engine))
    if remaining < MIN_PAGE:
        result["errors"].append(f"x: total post budget reached (X_TOTAL_POST_BUDGET={config.X_TOTAL_POST_BUDGET}) - nothing read")
        return result

    stored = _stored_accounts(engine)
    stale = {k for k, row in stored.items() if row["updated_at"] is None or db.as_utc(row["updated_at"]) < now - FOLLOWER_REFRESH_EVERY}
    to_lookup = [a["username"] for a in SBA_X_ACCOUNTS if a["entity_key"] not in stored or a["entity_key"] in stale]
    looked_up: dict[str, dict[str, Any]] = {}
    if to_lookup:
        looked_up, missing = client.users_by_username(to_lookup)
        for username in missing:
            msg = f"x @{username}: account not found"
            logger.warning(msg)
            result["errors"].append(msg)

    for entry in SBA_X_ACCOUNTS:
        if remaining < MIN_PAGE:
            result["errors"].append("x: run post budget reached (X_MAX_POSTS_PER_RUN) - remaining accounts skipped")
            break
        entity_key = entry["entity_key"]
        if (user := looked_up.get(entry["username"].lower())) is not None:
            _store_channel(engine, user, entity_key, now)  # new account, or its daily follower refresh
            channel_id, username = user["id"], user["username"]
        elif entity_key in stored:
            channel_id, username = stored[entity_key]["channel_id"], stored[entity_key]["handle"].lstrip("@")
        else:
            continue  # not found - already reported

        default_topic = BY_ENTITY[entity_key]["default_topic"]
        newest = _edge_post(engine, channel_id, newest=True)
        oldest = _edge_post(engine, channel_id, newest=False)
        windows: list[dict[str, Any]] = []
        if newest is None:
            windows.append({"start_time": cutoff})  # first run: backfill now -> cutoff
        else:
            windows.append({"since_id": newest[0]})
            if oldest[1] > cutoff + timedelta(days=1):
                windows.append({"until_id": oldest[0], "start_time": cutoff})  # keep going back

        cap = min(config.X_MAX_POSTS_PER_ACCOUNT, remaining)
        read = 0
        for window in windows:
            token: str | None = None
            while cap - read >= MIN_PAGE:
                posts, token = client.user_posts(channel_id, cap - read, pagination_token=token, **window)
                read += len(posts)
                remaining -= len(posts)
                rows = [r for p in posts if (r := parse_post(p, channel_id, username, default_topic, now)) is not None]
                new, updated = _store_posts(engine, rows, now)
                result["new"] += new
                result["updated"] += updated
                if not token or not posts:
                    break
    return result
