"""Audience step of the Data Collector agent: what the audience says about SBA posts.

- YouTube: the most relevant top-level comments (one commentThreads call = 1 quota
  unit, up to 100 comments) for the most-viewed videos published 1-7 days ago.
- X: other people's replies to the most-seen SBA posts published 12h-6.5d ago
  (X's recent search only reaches 7 days back). Billed per reply like posts, so
  X_REPLY_BUDGET is a hard cap across all runs, counted from stored replies.

Each post is read once. Only the comment text, time and like count are stored -
no author name, handle or id - so the analysis is about the audience as a whole,
never about individuals. Classification happens later in audience_agent.py.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.engine import Engine

from backend import config, db
from backend.agents.x_client import XClient
from backend.agents.x_client import parse_timestamp as parse_x_timestamp
from backend.agents.youtube_client import CommentsDisabled, YouTubeClient, top_comments

logger = logging.getLogger("sada.collector.audience")


def _parse_youtube_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def _candidates(engine: Engine, platform: str, newest: datetime, oldest: datetime, limit: int) -> list[dict[str, Any]]:
    """Most-viewed posts in [oldest, newest] that have comments and none collected yet."""
    v, c, a = db.videos.c, db.channels.c, db.audience_comments.c
    stmt = (
        select(v.video_id, v.view_count, c.handle)
        .join(db.channels, v.channel_id == c.channel_id)
        .where(v.platform == platform, v.published_at >= oldest, v.published_at <= newest)
        .where(func.coalesce(v.comment_count, 0) > 0)
        .where(~exists().where(a.video_id == v.video_id))
        .order_by(func.coalesce(v.view_count, 0).desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        return [r._asdict() for r in conn.execute(stmt)]


def _store(engine: Engine, rows: list[dict[str, Any]]) -> int:
    rows = [r for r in rows if r["text"].strip() and r["published_at"] is not None]
    if not rows:
        return 0
    with engine.begin() as conn:
        db.upsert(conn, db.audience_comments, rows, "comment_id", ["like_count"])
    return len(rows)


def collect_youtube(engine: Engine, client: YouTubeClient, now: datetime) -> int:
    """Returns comments stored. QuotaExceeded propagates so the caller ends the YouTube step."""
    stored = 0
    for post in _candidates(engine, "youtube", now - timedelta(days=1), now - timedelta(days=7), config.AUDIENCE_YT_VIDEOS_PER_RUN):
        try:
            comments = top_comments(client, post["video_id"], config.AUDIENCE_YT_COMMENTS_PER_VIDEO)
        except CommentsDisabled:
            continue
        stored += _store(engine, [
            {"comment_id": f"yt:{c['comment_id']}", "platform": "youtube", "video_id": post["video_id"],
             "text": c["text"], "published_at": _parse_youtube_ts(c["published_at"]),
             "like_count": c["like_count"], "collected_at": now}
            for c in comments
        ])
    return stored


def replies_read_so_far(engine: Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            select(func.count()).select_from(db.audience_comments).where(db.audience_comments.c.platform == "x")
        ).scalar() or 0


def collect_x(engine: Engine, client: XClient, now: datetime) -> dict[str, Any]:
    """Returns {"stored": n, "errors": [...]}. Auth/credit errors propagate (pages already stored are kept)."""
    result: dict[str, Any] = {"stored": 0, "errors": []}
    remaining = config.X_REPLY_BUDGET - replies_read_so_far(engine)
    if config.X_REPLY_BUDGET <= 0:
        return result
    if remaining < 10:  # recent search returns at least 10 per call
        result["errors"].append(f"x replies: budget reached (X_REPLY_BUDGET={config.X_REPLY_BUDGET})")
        return result
    posts = _candidates(engine, "x", now - timedelta(hours=12), now - timedelta(days=6, hours=12), config.AUDIENCE_X_POSTS_PER_RUN)
    for post in posts:
        if remaining < 10:
            result["errors"].append("x replies: budget reached mid-run")
            break
        replies = client.replies(post["video_id"], post["handle"].lstrip("@"), min(config.X_REPLIES_PER_POST, remaining))
        remaining -= len(replies)
        result["stored"] += _store(engine, [
            {"comment_id": f"x:{r['id']}", "platform": "x", "video_id": post["video_id"], "text": r.get("text") or "",
             "published_at": parse_x_timestamp(r.get("created_at")),
             "like_count": (r.get("public_metrics") or {}).get("like_count"), "collected_at": now}
            for r in replies
        ])
    return result
