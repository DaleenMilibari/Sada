"""Read queries over the collected data, shared by the API and the analysis agents."""

from __future__ import annotations

import statistics
from datetime import timedelta, timezone
from typing import Any, Literal

from sqlalchemy import and_, func, select

from backend import config, db

VideoSort = Literal["published", "views"]

# Saudi Arabia is UTC+3 all year (no DST) - a fixed offset avoids needing tzdata on Windows.
RIYADH_TZ = timezone(timedelta(hours=3))


def _video_columns():
    v, c = db.videos.c, db.channels.c
    return [
        v.video_id, v.platform, v.channel_id, c.entity_key, c.name_ar.label("channel_name_ar"), v.title, v.url, v.published_at,
        v.duration_seconds, v.content_type, v.topic, v.topic_source, v.view_count, v.like_count,
        v.comment_count, v.stats_updated_at,
    ]


def _video_dict(row) -> dict[str, Any]:
    d = row._asdict()
    d["published_at"] = db.as_utc(d["published_at"])
    d["stats_updated_at"] = db.as_utc(d["stats_updated_at"])
    d["url"] = d["url"] or f"https://www.youtube.com/watch?v={d['video_id']}"
    return d


def list_channels(platform: str | None = None) -> list[dict[str, Any]]:
    counts = (
        select(db.videos.c.channel_id, func.count().label("tracked_videos"))
        .group_by(db.videos.c.channel_id)
        .subquery()
    )
    stmt = (
        select(db.channels, func.coalesce(counts.c.tracked_videos, 0).label("tracked_videos"))
        .outerjoin(counts, counts.c.channel_id == db.channels.c.channel_id)
        .order_by(db.channels.c.platform, db.channels.c.subscriber_count.desc())
    )
    if platform:
        stmt = stmt.where(db.channels.c.platform == platform)
    with db.get_engine().connect() as conn:
        return [{**r._asdict(), "updated_at": db.as_utc(r.updated_at)} for r in conn.execute(stmt)]


def list_videos(
    *,
    platform: str | None = None,
    channel: str | None = None,
    content_type: str | None = None,
    topic: str | None = None,
    days: int | None = None,
    sort: VideoSort = "published",
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, list[dict[str, Any]]]:
    """`channel` is an entity_key from backend/sba_channels.py."""
    conditions = []
    if platform:
        conditions.append(db.videos.c.platform == platform)
    if channel:
        conditions.append(db.channels.c.entity_key == channel)
    if content_type:
        conditions.append(db.videos.c.content_type == content_type)
    if topic:
        conditions.append(db.videos.c.topic == topic)
    if days:
        conditions.append(db.videos.c.published_at >= db.utcnow() - timedelta(days=days))
    where = and_(*conditions) if conditions else None

    base = select(*_video_columns()).join(db.channels, db.videos.c.channel_id == db.channels.c.channel_id)
    count = select(func.count()).select_from(db.videos).join(db.channels, db.videos.c.channel_id == db.channels.c.channel_id)
    if where is not None:
        base, count = base.where(where), count.where(where)
    order = db.videos.c.view_count.desc().nulls_last() if sort == "views" else db.videos.c.published_at.desc()

    with db.get_engine().connect() as conn:
        total = conn.execute(count).scalar() or 0
        rows = conn.execute(base.order_by(order).limit(limit).offset(offset))
        return total, [_video_dict(r) for r in rows]


def get_video(video_id: str) -> dict[str, Any] | None:
    with db.get_engine().connect() as conn:
        row = conn.execute(
            select(*_video_columns())
            .join(db.channels, db.videos.c.channel_id == db.channels.c.channel_id)
            .where(db.videos.c.video_id == video_id)
        ).first()
        if row is None:
            return None
        snaps = conn.execute(
            select(db.video_snapshots.c.captured_at, db.video_snapshots.c.view_count,
                   db.video_snapshots.c.like_count, db.video_snapshots.c.comment_count)
            .where(db.video_snapshots.c.video_id == video_id)
            .order_by(db.video_snapshots.c.captured_at)
        )
        return {
            **_video_dict(row),
            "snapshots": [{**s._asdict(), "captured_at": db.as_utc(s.captured_at)} for s in snaps],
        }


def collector_status(run_limit: int = 10) -> dict[str, Any]:
    with db.get_engine().connect() as conn:
        runs = [
            {**r._asdict(), "started_at": db.as_utc(r.started_at), "finished_at": db.as_utc(r.finished_at)}
            for r in conn.execute(select(db.collector_runs).order_by(db.collector_runs.c.started_at.desc()).limit(run_limit))
        ]
        quota_24h = conn.execute(
            select(func.coalesce(func.sum(db.collector_runs.c.quota_units), 0))
            .where(db.collector_runs.c.started_at >= db.utcnow() - timedelta(hours=24))
        ).scalar()
        ig_calls_24h = conn.execute(
            select(func.coalesce(func.sum(db.collector_runs.c.instagram_calls), 0))
            .where(db.collector_runs.c.started_at >= db.utcnow() - timedelta(hours=24))
        ).scalar()
        return {
            "enabled": bool(config.YOUTUBE_API_KEY) or config.INSTAGRAM_ENABLED or config.X_ENABLED,
            "youtube_enabled": bool(config.YOUTUBE_API_KEY),
            "instagram_enabled": config.INSTAGRAM_ENABLED,
            "x_enabled": config.X_ENABLED,
            "instagram_calls_last_24h": int(ig_calls_24h or 0),
            "schedule_enabled": config.COLLECTOR_SCHEDULE_ENABLED,
            "interval_minutes": config.COLLECTOR_INTERVAL_MINUTES,
            "lookback_days": config.COLLECTOR_LOOKBACK_DAYS,
            "total_channels": conn.execute(select(func.count()).select_from(db.channels)).scalar(),
            "total_videos": conn.execute(select(func.count()).select_from(db.videos)).scalar(),
            "total_snapshots": conn.execute(select(func.count()).select_from(db.video_snapshots)).scalar(),
            "quota_units_last_24h": int(quota_24h or 0),
            "runs": runs,
        }


def analysis_records(days: int = 60, min_age_days: float = 3.0, platform: str | None = None) -> list[dict[str, Any]]:
    """One flat record per post (YouTube video or Instagram post), normalized for fair comparisons.

    Shared input for every analysis agent. Confounds removed up front so slices compare like with like:
    - Account size: `performance_index` = the post's primary metric / the median of the same
      platform + account + content_type (1.0 = typical for that account; 2.0 = twice its usual).
      Primary metric: views on YouTube; impressions on X; likes + comments on Instagram (its API exposes no views).
      **Compare slices - including across platforms - on performance_index, never on raw counts.**
    - `views_index` is the same value for YouTube only (None on Instagram).
    - Post age: posts younger than `min_age_days` are excluded - they haven't accumulated engagement yet.
    `engagement_rate` = (likes + comments) / views - YouTube, and X with impressions as views (None without views or both counts).
    Time fields are Riyadh local time.
    """
    now = db.utcnow()
    v, c = db.videos.c, db.channels.c
    stmt = (
        select(*_video_columns(), c.subscriber_count)
        .join(db.channels, v.channel_id == c.channel_id)
        .where(v.published_at >= now - timedelta(days=days))
        .where(v.published_at <= now - timedelta(days=min_age_days))
    )
    if platform:
        stmt = stmt.where(v.platform == platform)
    with db.get_engine().connect() as conn:
        rows = [_video_dict(r) | {"subscriber_count": r.subscriber_count} for r in conn.execute(stmt)]

    def primary(r: dict[str, Any]) -> int | None:
        if r["platform"] in ("youtube", "x"):
            return r["view_count"]
        interactions = [x for x in (r["like_count"], r["comment_count"]) if x is not None]
        return sum(interactions) if interactions else None

    records = []
    groups: dict[tuple[str, str, str], list[int]] = {}
    for r in rows:
        r["primary_metric"] = {"youtube": "views", "x": "impressions"}.get(r["platform"], "interactions")
        r["primary_value"] = primary(r)
        if r["primary_value"] is None:
            continue  # nothing comparable was exposed for this post
        records.append(r)
        groups.setdefault((r["platform"], r["entity_key"], r["content_type"]), []).append(r["primary_value"])
    medians = {key: (statistics.median(vals) or 1) for key, vals in groups.items()}

    for r in records:
        local = r["published_at"].astimezone(RIYADH_TZ)
        r["publish_hour"] = local.hour
        r["day_of_week"] = local.strftime("%a").lower()  # mon..sun
        r["age_days"] = round((now - r["published_at"]).total_seconds() / 86400, 2)
        r["performance_index"] = round(r["primary_value"] / medians[(r["platform"], r["entity_key"], r["content_type"])], 4)
        r["views_index"] = r["performance_index"] if r["platform"] == "youtube" else None
        interactions = [x for x in (r["like_count"], r["comment_count"]) if x is not None]
        r["engagement_rate"] = sum(interactions) / r["view_count"] if interactions and r["view_count"] else None
    return records
