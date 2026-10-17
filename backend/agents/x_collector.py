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
from backend.agents.x_client import ARCHIVE_MIN_PAGE, MAX_PAGE, MIN_PAGE, XClient, parse_timestamp
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

    accounts: list[tuple[str, str, str]] = []  # (channel_id, username, default_topic)
    for entry in SBA_X_ACCOUNTS:
        entity_key = entry["entity_key"]
        if (user := looked_up.get(entry["username"].lower())) is not None:
            _store_channel(engine, user, entity_key, now)  # new account, or its daily follower refresh
            accounts.append((user["id"], user["username"], BY_ENTITY[entity_key]["default_topic"]))
        elif entity_key in stored:
            accounts.append((stored[entity_key]["channel_id"], stored[entity_key]["handle"].lstrip("@"), BY_ENTITY[entity_key]["default_topic"]))
        # else: not found - already reported

    read: dict[str, int] = {}

    def read_page(account: tuple[str, str, str], window: dict[str, Any], token: str | None) -> tuple[list[dict[str, Any]], str | None]:
        """One page (timeline, or full-archive search when `window` has an end_time) within the
        account's and the run's caps; stored as soon as it arrives."""
        nonlocal remaining
        channel_id, username, default_topic = account
        archive = "end_time" in window
        cap = min(MAX_PAGE, config.X_MAX_POSTS_PER_ACCOUNT - read.get(channel_id, 0), remaining)
        if cap < (ARCHIVE_MIN_PAGE if archive else MIN_PAGE):
            return [], None
        if archive:
            posts, token = client.archive_posts(username, cap, pagination_token=token, **window)
        else:
            posts, token = client.user_posts(channel_id, cap, pagination_token=token, **window)
        read[channel_id] = read.get(channel_id, 0) + len(posts)
        remaining -= len(posts)
        rows = [r for p in posts if (r := parse_post(p, channel_id, username, default_topic, now)) is not None]
        new, updated = _store_posts(engine, rows, now)
        result["new"] += new
        result["updated"] += updated
        return rows, (token if posts else None)

    # Pass 1 - what's new since the last run, for every account first, so "now" stays fresh everywhere.
    backfill: list[dict[str, Any]] = []
    skipped = False
    for account in accounts:
        newest = _edge_post(engine, account[0], newest=True)
        if newest is None:
            backfill.append({"edge": now, "account": account, "window": {"start_time": cutoff}, "token": None})
            continue  # first run: the backfill below reads now -> cutoff
        if remaining < MIN_PAGE:
            skipped = True
            break
        token: str | None = None
        while True:
            _, token = read_page(account, {"since_id": newest[0]}, token)
            if not token:
                break
        oldest = _edge_post(engine, account[0], newest=False)
        if oldest[1] > cutoff + timedelta(days=1):
            backfill.append({"edge": oldest[1], "account": account,
                             "window": {"until_id": oldest[0], "start_time": cutoff}, "token": None})

    # Pass 2 - backfill toward the cutoff one page at a time, always for the account whose history
    # is currently shortest, so a limited budget evens out how far back the accounts reach.
    while backfill:
        if remaining < MIN_PAGE:
            skipped = True
            break
        item = max(backfill, key=lambda b: b["edge"])
        rows, item["token"] = read_page(item["account"], item["window"], item["token"])
        if rows:
            item["edge"] = min(r["published_at"] for r in rows)
        if item["token"]:
            continue
        cap_left = config.X_MAX_POSTS_PER_ACCOUNT - read.get(item["account"][0], 0) >= ARCHIVE_MIN_PAGE
        if "end_time" not in item["window"] and cap_left and item["edge"] > cutoff + timedelta(days=1):
            # The timeline ended before the cutoff: it only reaches the latest ~3,200 tweets.
            # Continue from the oldest post stored so far through full-archive search.
            item["window"] = {"start_time": cutoff, "end_time": item["edge"]}
            continue
        backfill.remove(item)  # window complete, or the account's cap reached

    if skipped:
        result["errors"].append("x: post budget reached (X_MAX_POSTS_PER_RUN / X_TOTAL_POST_BUDGET) - remaining backfill waits for the next run")
    return result
