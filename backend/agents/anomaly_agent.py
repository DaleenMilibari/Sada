"""Task 4 - Spike / drop detection on real posts.

Two detectors, both computed only from stored snapshots and counts:

1. Level (cumulative): a post's main metric (views on YouTube, likes + comments on Instagram)
   vs the typical value of its peers (same platform + account + content type) AT THE SAME AGE.
   - "same_age": peers' snapshots bracket the post's age, so their value at that age is interpolated.
   - "plateau": when snapshots can't pin the age down (e.g. a one-shot import), posts at least
     PLATEAU_AGE_DAYS old are compared with peers of that age on their current value, since by then
     most of the lifetime engagement has accumulated. Younger posts are NOT guessed at.
2. Velocity: metric per hour between the latest two snapshots vs the interval before them - a post
   that suddenly takes off, or stalls.

ratio >= SPIKE_RATIO is a spike, ratio <= DROP_RATIO a drop. Too few peers or a tiny expected value
means no alert (insufficient evidence), never a guess.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from datetime import datetime
from typing import Any

from sqlalchemy import select

from backend import db, repository

SPIKE_RATIO = 3.0
DROP_RATIO = 0.33
HIGH_SPIKE_RATIO = 6.0
HIGH_DROP_RATIO = 0.15

MIN_PEERS = 5
MIN_AGE_HOURS = 6.0  # younger posts are too noisy to judge
PLATEAU_AGE_DAYS = 7.0
MIN_EXPECTED = {"views": 100, "interactions": 10}  # tiny baselines make any ratio meaningless
MIN_VELOCITY_EXPECTED = {"views": 5.0, "interactions": 0.5}  # per hour
MIN_VELOCITY_INTERVAL_H = 1.0
MAX_ALERTS = 60
CACHE_TTL_SECONDS = 60

_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()

Series = list[tuple[float, int]]  # (age in hours, metric value), ascending


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _metric(platform: str) -> str:
    return "views" if platform in ("youtube", "x") else "interactions"  # X: impressions


def _primary(platform: str, views, likes, comments) -> int | None:
    if platform in ("youtube", "x"):
        return views
    parts = [x for x in (likes, comments) if x is not None]
    return sum(parts) if parts else None


def value_at_age(series: Series, age_h: float) -> float | None:
    """Linear interpolation between the snapshots bracketing `age_h`; None if they don't (no extrapolation)."""
    before = after = None
    for point in series:
        if point[0] <= age_h:
            before = point
        else:
            after = point
            break
    if before is None or after is None:
        return None
    if after[0] - before[0] > max(2.0, 0.5 * age_h):  # too coarse a gap to trust
        return None
    (a0, v0), (a1, v1) = before, after
    return v0 + (v1 - v0) * (age_h - a0) / (a1 - a0)


def _severity(kind: str, ratio: float) -> str:
    if kind == "spike":
        return "high" if ratio >= HIGH_SPIKE_RATIO else "medium"
    return "high" if ratio <= HIGH_DROP_RATIO else "medium"


def _deviation(ratio: float) -> float:
    """How far from normal, in either direction: 3x and 1/3x rank the same; a full stall ranks highest."""
    return max(ratio, 1 / ratio) if ratio > 0 else math.inf


def _classify(ratio: float) -> str | None:
    if ratio >= SPIKE_RATIO:
        return "spike"
    if ratio <= DROP_RATIO:
        return "drop"
    return None


def _load(conn, days: int, now: datetime) -> tuple[dict[str, dict[str, Any]], dict[str, list[tuple[datetime, Any, Any, Any]]]]:
    """Posts published within the peer window (analysis window + the plateau lookback) and their snapshots."""
    v, c, s = db.videos.c, db.channels.c, db.video_snapshots.c
    from datetime import timedelta

    since = now - timedelta(days=max(days, 60))
    posts = {
        r.video_id: repository._video_dict(r)
        for r in conn.execute(
            select(*repository._video_columns()).join(db.channels, v.channel_id == c.channel_id).where(v.published_at >= since)
        )
    }
    snaps: dict[str, list[tuple[datetime, Any, Any, Any]]] = {}
    for vid, at, views, likes, comments in conn.execute(
        select(s.video_id, s.captured_at, s.view_count, s.like_count, s.comment_count)
        .join(db.videos, v.video_id == s.video_id)
        .where(v.published_at >= since)
        .order_by(s.video_id, s.captured_at)
    ):
        snaps.setdefault(vid, []).append((db.as_utc(at), views, likes, comments))
    return posts, snaps


def _series(post: dict[str, Any], snaps: list[tuple[datetime, Any, Any, Any]]) -> Series:
    out: Series = []
    for at, views, likes, comments in snaps:
        value = _primary(post["platform"], views, likes, comments)
        age = (at - post["published_at"]).total_seconds() / 3600
        if value is not None and age >= 0:
            out.append((age, int(value)))
    return out


def _alert(post, kind, metric, observed, expected, ratio, detection, basis, peers, detected_at, explanation) -> dict[str, Any]:
    return {
        "alert_id": f"{detection}:{kind}:{post['video_id']}",
        "kind": kind,
        "video": post,
        "metric": metric,
        "observed": int(round(observed)),
        "expected": int(round(expected)),
        "ratio": round(ratio, 2),
        "severity": _severity(kind, ratio),
        "detected_at": detected_at,
        "detection": detection,
        "basis": basis,
        "peers": peers,
        "explanation": explanation,
    }


def detect(days: int = 7, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or db.utcnow()
    with db.get_engine().connect() as conn:
        posts, snaps = _load(conn, days, now)

    series = {vid: _series(posts[vid], rows) for vid, rows in snaps.items() if vid in posts}
    peer_groups: dict[tuple[str, str, str], list[str]] = {}
    for vid, p in posts.items():
        peer_groups.setdefault((p["platform"], p["entity_key"], p["content_type"]), []).append(vid)

    def current(vid: str) -> tuple[float, int] | None:
        """Latest (age_h, value): newest snapshot, else the stored counts."""
        if series.get(vid):
            return series[vid][-1]
        p = posts[vid]
        value = _primary(p["platform"], p["view_count"], p["like_count"], p["comment_count"])
        stamp = p["stats_updated_at"]
        if value is None or stamp is None:
            return None
        return (stamp - p["published_at"]).total_seconds() / 3600, int(value)

    alerts: list[dict[str, Any]] = []
    for vid, post in posts.items():
        age_days = (now - post["published_at"]).total_seconds() / 86400
        if age_days > days:
            continue
        metric = _metric(post["platform"])
        peers = [x for x in peer_groups[(post["platform"], post["entity_key"], post["content_type"])] if x != vid]
        cur = current(vid)
        if cur is None or cur[0] < MIN_AGE_HOURS:
            continue
        age_h, observed = cur
        detected_at = post["stats_updated_at"] or now

        # --- level detection ---
        level = None
        expected_vals = [x for x in (value_at_age(series.get(p, []), age_h) for p in peers) if x is not None]
        if len(expected_vals) >= MIN_PEERS:
            level = ("same_age", statistics.median(expected_vals), len(expected_vals))
        elif age_h / 24 >= PLATEAU_AGE_DAYS:
            plateau = [
                cur_p[1]
                for p in peers
                if (cur_p := current(p)) is not None and cur_p[0] / 24 >= PLATEAU_AGE_DAYS
            ]
            if len(plateau) >= MIN_PEERS:
                level = ("plateau", statistics.median(plateau), len(plateau))
        if level and level[1] >= MIN_EXPECTED[metric]:
            basis, expected, n = level
            ratio = observed / expected
            kind = _classify(ratio)
            if kind:
                what = {"youtube": "المشاهدات", "x": "مرات الظهور"}.get(post["platform"], "التفاعل (إعجابات + تعليقات)")
                where = "عند نفس العمر" if basis == "same_age" else "لمنشورات بعمر ٧ أيام فأكثر"
                alerts.append(_alert(
                    post, kind, metric, observed, expected, ratio, "level", basis, n, detected_at,
                    f"{what} {observed:,} مقابل المعتاد {round(expected):,} {where} "
                    f"لنفس الحساب ونوع المحتوى (n={n}) — {ratio:.1f}×.",
                ))
                continue  # one alert per post; the level alert already says it

        # --- velocity detection (needs three snapshots) ---
        pts = series.get(vid, [])
        if len(pts) >= 3 and age_days <= PLATEAU_AGE_DAYS:
            (a0, v0), (a1, v1), (a2, v2) = pts[-3:]
            if a2 - a1 >= MIN_VELOCITY_INTERVAL_H and a1 - a0 >= MIN_VELOCITY_INTERVAL_H:
                # Platforms sometimes correct counts downward (removed spam views): a negative rate is a stall.
                prev, recent = (v1 - v0) / (a1 - a0), max(0.0, (v2 - v1) / (a2 - a1))
                if prev >= MIN_VELOCITY_EXPECTED[metric]:
                    ratio = recent / prev
                    kind = _classify(ratio)
                    if kind:
                        verb = "تسارع" if kind == "spike" else "تباطأ"
                        alerts.append(_alert(
                            post, kind, metric, recent, prev, ratio, "velocity", "snapshots", len(pts), detected_at,
                            f"{verb} نمو {'مرات الظهور' if post['platform'] == 'x' else 'المشاهدات' if metric == 'views' else 'التفاعل'} فجأة: "
                            f"{recent:,.1f}/ساعة بعد {prev:,.1f}/ساعة في القياس السابق ({ratio:.1f}×).",
                        ))

    alerts.sort(key=lambda a: (a["severity"] != "high", -_deviation(a["ratio"])))
    return alerts[:MAX_ALERTS]


def alerts(days: int = 7) -> list[dict[str, Any]]:
    """Cached for CACHE_TTL_SECONDS per window."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(days)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    result = detect(days)
    with _lock:
        _cache[days] = (now, result)
    return result
