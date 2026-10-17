"""Task 3 - dashboard analytics over the collected SBA data.

Everything is derived from `repository.analysis_records()`, so slices are compared on
`performance_index` (the post's main metric / its own account's typical value) and never on raw
counts across platforms. The summary is cached in memory for CACHE_TTL_SECONDS: the dashboard
polls every minute and the response must stay well under 100 ms.
"""

from __future__ import annotations

import statistics
import threading
import time
from typing import Any

from sqlalchemy import select

from backend import config, db, repository
from backend.topics import TOPICS

CACHE_TTL_SECONDS = 60
MIN_POST_AGE_DAYS = 3.0  # analysis_records' default: younger posts haven't accumulated engagement
MIN_TIMES_N = 5  # a (day, hour) cell with fewer posts is noise - it is not surfaced

_cache: dict[tuple[int, str | None], tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def data_as_of() -> Any:
    """Finish time of the last successful collector run (None if the collector never succeeded)."""
    with db.get_engine().connect() as conn:
        value = conn.execute(
            select(db.collector_runs.c.finished_at)
            .where(db.collector_runs.c.status == "success")
            .where(db.collector_runs.c.finished_at.isnot(None))
            .order_by(db.collector_runs.c.finished_at.desc())
            .limit(1)
        ).scalar()
    return db.as_utc(value)


def _median(values: list[float]) -> float:
    return round(statistics.median(values), 3)


def _sum(values) -> int:
    return int(sum(v for v in values if v is not None))  # null (hidden) is never treated as 0


# Platforms whose view_count is a reach metric: YouTube views, X impressions (Instagram exposes none).
# They measure different things, so they are summed or rated together only within one platform.
VIEW_PLATFORMS = ("youtube", "x")


def _engagement_rate(records: list[dict[str, Any]], platform: str = "youtube") -> float | None:
    """(likes + comments) / views, over `platform` posts that expose views and at least one of the counts."""
    likes = comments = views = 0
    for r in records:
        if r["platform"] != platform or not r["view_count"]:
            continue
        if r["like_count"] is None and r["comment_count"] is None:
            continue
        likes += r["like_count"] or 0
        comments += r["comment_count"] or 0
        views += r["view_count"]
    return round((likes + comments) / views, 5) if views else None


def build_summary(days: int = 30, platform: str | None = None) -> dict[str, Any]:
    records = repository.analysis_records(days=days, min_age_days=MIN_POST_AGE_DAYS, platform=platform)
    views_platform = platform if platform in VIEW_PLATFORMS else "youtube"  # "all": YouTube views only
    channels = repository.list_channels(platform)

    by_platform = []
    for p in sorted({c["platform"] for c in channels}):
        accounts = [c for c in channels if c["platform"] == p]
        posts = [r for r in records if r["platform"] == p]
        by_platform.append({
            "platform": p,
            "accounts": len(accounts),
            "posts": len(posts),
            "followers": _sum(c["subscriber_count"] for c in accounts),
            "likes": _sum(r["like_count"] for r in posts),
            "comments": _sum(r["comment_count"] for r in posts),
        })

    channel_names = {(c["platform"], c["entity_key"]): c for c in channels}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records:
        grouped.setdefault((r["platform"], r["entity_key"]), []).append(r)
    by_channel = []
    for (p, key), rows in grouped.items():
        channel = channel_names.get((p, key), {})
        by_channel.append({
            "platform": p,
            "entity_key": key,
            "name_ar": rows[0]["channel_name_ar"],
            "subscriber_count": channel.get("subscriber_count"),
            "posts": len(rows),
            "views": _sum(r["view_count"] for r in rows) if p in VIEW_PLATFORMS else None,
            "median_performance_index": _median([r["performance_index"] for r in rows]),
            "engagement_rate": _engagement_rate(rows, p),
            # The typical post's views (YouTube) / impressions (X) / interactions (Instagram)
            # per 1,000 followers - comparable across accounts of one platform, unlike the index.
            "median_per_1k_followers": _median(per) if (per := [r["per_1k_followers"] for r in rows if r["per_1k_followers"] is not None]) else None,
        })
    by_channel.sort(key=lambda c: c["median_per_1k_followers"] or 0, reverse=True)

    types: dict[tuple[str, str], list[float]] = {}
    topics: dict[str, list[float]] = {}
    for r in records:
        types.setdefault((r["platform"], r["content_type"]), []).append(r["account_index"])  # vs the account's typical post
        topics.setdefault(r["topic"], []).append(r["performance_index"])

    # Best times use the whole collected history: one weekday/hour cell gets a single post a week at best,
    # so the KPI window (`days`) would leave most cells under MIN_TIMES_N.
    history = records if days >= config.COLLECTOR_LOOKBACK_DAYS else repository.analysis_records(
        min_age_days=MIN_POST_AGE_DAYS, platform=platform
    )
    cells: dict[tuple[str, str, int], list[float]] = {}
    spans: dict[str, list[Any]] = {}
    for r in history:
        cells.setdefault((r["platform"], r["day_of_week"], r["publish_hour"]), []).append(r["performance_index"])
        spans.setdefault(r["platform"], []).append(r["published_at"])

    return {
        "generated_at": db.utcnow(),
        "data_as_of": data_as_of(),
        "days": days,
        "platform": platform,
        "min_post_age_days": MIN_POST_AGE_DAYS,
        "totals": {
            "posts": len(records),
            "views": _sum(r["view_count"] for r in records if r["platform"] == views_platform),
            "likes": _sum(r["like_count"] for r in records),
            "comments": _sum(r["comment_count"] for r in records),
            "engagement_rate": _engagement_rate(records, views_platform),
        },
        "by_platform": by_platform,
        "by_channel": by_channel,
        "by_content_type": sorted(
            ({"platform": p, "content_type": t, "posts": len(v), "median_performance_index": _median(v)} for (p, t), v in types.items()),
            key=lambda x: (x["platform"], -x["median_performance_index"]),
        ),
        "by_topic": sorted(
            ({"topic": t, "label_ar": TOPICS.get(t, t), "posts": len(v), "median_performance_index": _median(v)} for t, v in topics.items()),
            key=lambda x: -x["median_performance_index"],
        ),
        "best_times": [
            {"platform": p, "day_of_week": d, "hour": h, "median_performance_index": _median(v), "n": len(v)}
            for (p, d, h), v in sorted(cells.items())
            if len(v) >= MIN_TIMES_N
        ],
        "best_times_coverage": [
            {"platform": p, "days": max(1, round((max(ts) - min(ts)).total_seconds() / 86400)), "posts": len(ts)}
            for p, ts in sorted(spans.items())
        ],
    }


def summary(days: int = 30, platform: str | None = None) -> dict[str, Any]:
    """Cached for CACHE_TTL_SECONDS per (days, platform)."""
    key = (days, platform)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    result = build_summary(days, platform)
    with _lock:
        _cache[key] = (now, result)
    return result
