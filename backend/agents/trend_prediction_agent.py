"""Task 2 - Trend & Viral Prediction Agent (official SBA YouTube channels).

- Goal: Say what is trending across SBA right now, how likely each video is to
  go viral, how many views it will have at day 7 - and measure how accurate
  that prediction really is.
- Input: YouTube videos + their `video_snapshots` time series (backend/db.py).
  YouTube only: trending and prediction need view counts, which Instagram's
  API does not expose for accounts we don't own.
- Trigger: GET /api/trending and GET /api/model/accuracy (cached), or the CLI
  (python -m backend.agents.trend_prediction_agent).
- Tools: Plain statistics (medians, linear interpolation) - no LLM, so every
  number is reproducible.
- Data/context: `views_at_age()` reads a video's views at an exact age off its
  snapshots; `analysis_records()` gives each content type's track record.
- Reasoning task:
  * Velocity = views/hour between the last two snapshots (or since publish for
    a video under 48 h that has a single snapshot). `velocity_index` divides it
    by the channel's median velocity for videos in the same age bucket.
  * Viral score (0-1) = 0.60 momentum (velocity_index) + 0.25 reach so far
    (views vs. the channel's usual at that age) + 0.15 content-type track
    record (share of the channel's posts of that type that reached 2x its usual).
  * Day-7 prediction = current views / the typical share of day-7 views a video
    has at its age, from the growth curves of finished videos (channel +
    content type, then channel, then content type across SBA).
- Decision: Which videos rank as trending, their score, and whether there is
  enough history to predict at all.
- Action/output: TrendingItem[] and ModelAccuracy (backend/schemas.py).
- Memory/state: In-process caches - trending for 60 s, the growth model and the
  backtest for an hour.
- Evidence: Every reason quotes the measured velocity, the channel baseline it
  is compared with, and the sample behind the track record. The accuracy number
  is a temporal backtest against a naive "channel median" baseline.
- Failure/fallback: Too little snapshot history -> `predicted_views_7d` is null
  and the accuracy reports status "insufficient_history". Never guessed.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from backend import db, repository

PLATFORM = "youtube"

# --- Prediction -------------------------------------------------------------
HORIZON_HOURS = 168.0  # day 7
ANCHOR_HOURS = (6.0, 12.0, 24.0, 48.0, 72.0, 120.0)  # ages the growth curve is measured at
BACKTEST_ANCHOR_HOURS = 24.0  # "predict 7-day views from first-day data"
MIN_CURVE_SAMPLES = 5  # finished videos a growth curve needs at one anchor
# Reading views at an exact age: interpolate between two snapshots at most this
# share of the age apart, else take one snapshot within half of it.
BRACKET_GAP_SHARE = 0.25
BACKTEST_TEST_SHARE = 0.2
MIN_BACKTEST_VIDEOS = 20

# --- Trending ---------------------------------------------------------------
# Upper edges (hours) of the age buckets velocities are compared within.
AGE_BUCKETS: tuple[tuple[float, str], ...] = (
    (6, "أقل من 6 ساعات"),
    (24, "6–24 ساعة"),
    (72, "1–3 أيام"),
    (168, "3–7 أيام"),
    (720, "1–4 أسابيع"),
    (math.inf, "أكثر من شهر"),
)
MIN_VELOCITY_GAP_HOURS = 10 / 60
MAX_VELOCITY_GAP_HOURS = 26.0  # a velocity measured over days isn't "now"
LIFETIME_VELOCITY_MAX_AGE_HOURS = 48.0
MIN_BASELINE_SAMPLES = 3
MIN_VELOCITY_FLOOR = 1.0  # views/hour - keeps a stalled bucket's median from dividing by ~0
MIN_TRACK_RECORD_SAMPLES = 10
VIRAL_PERFORMANCE_INDEX = 2.0
# Viral-score weights and the ratio at which a component saturates.
W_MOMENTUM, W_REACH, W_TRACK_RECORD = 0.60, 0.25, 0.15
SATURATION_RATIO = 8.0
TRACK_RECORD_SATURATION = 0.25

TRENDING_TTL_SECONDS = 60
MODEL_TTL_SECONDS = 3600

CONTENT_TYPE_AR = {"short": "المقاطع القصيرة", "video": "الفيديوهات", "live": "البث المباشر"}

Series = list[tuple[float, int]]  # [(age_hours, views)] sorted by age


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_videos(conn, published_before: datetime | None = None) -> dict[str, dict[str, Any]]:
    stmt = (
        select(*repository._video_columns())
        .join(db.channels, db.videos.c.channel_id == db.channels.c.channel_id)
        .where(db.videos.c.platform == PLATFORM)
    )
    if published_before is not None:
        stmt = stmt.where(db.videos.c.published_at <= published_before)
    return {r.video_id: repository._video_dict(r) for r in conn.execute(stmt)}


def _load_series(conn, videos: dict[str, dict[str, Any]], max_age_hours: float) -> dict[str, Series]:
    """Every video's view-count series as (age in hours, views), up to `max_age_hours`."""
    s = db.video_snapshots.c
    stmt = (
        select(s.video_id, s.captured_at, s.view_count)
        .join(db.videos, db.videos.c.video_id == s.video_id)
        .where(db.videos.c.platform == PLATFORM)
        .where(s.view_count.isnot(None))
        .order_by(s.video_id, s.captured_at)
    )
    series: dict[str, Series] = {}
    for video_id, captured_at, views in conn.execute(stmt):
        video = videos.get(video_id)
        if video is None:
            continue
        age = (db.as_utc(captured_at) - video["published_at"]).total_seconds() / 3600
        if 0 <= age <= max_age_hours:
            series.setdefault(video_id, []).append((age, int(views)))
    return series


def _load_latest_two(conn) -> dict[str, list[tuple[datetime, int]]]:
    """The two most recent snapshots of every YouTube video, newest first."""
    s = db.video_snapshots.c
    rn = func.row_number().over(partition_by=s.video_id, order_by=s.captured_at.desc()).label("rn")
    inner = (
        select(s.video_id, s.captured_at, s.view_count, rn)
        .join(db.videos, db.videos.c.video_id == s.video_id)
        .where(db.videos.c.platform == PLATFORM)
        .where(s.view_count.isnot(None))
        .subquery()
    )
    latest: dict[str, list[tuple[datetime, int]]] = {}
    for video_id, captured_at, views, _ in conn.execute(select(inner).where(inner.c.rn <= 2).order_by(inner.c.video_id, inner.c.rn)):
        latest.setdefault(video_id, []).append((db.as_utc(captured_at), int(views)))
    return latest


# ---------------------------------------------------------------------------
# Growth curves and day-7 prediction
# ---------------------------------------------------------------------------


def views_at_age(series: Series, age_hours: float) -> float | None:
    """Views at exactly `age_hours`, read off the snapshots - None if they don't pin it down."""
    before = after = None
    for point in series:
        if point[0] <= age_hours:
            before = point
        else:
            after = point
            break
    max_gap = age_hours * BRACKET_GAP_SHARE
    if before and after and after[0] - before[0] <= max_gap:
        (a0, v0), (a1, v1) = before, after
        return v0 + (v1 - v0) * (age_hours - a0) / (a1 - a0)
    nearest = min((p for p in (before, after) if p), key=lambda p: abs(p[0] - age_hours), default=None)
    if nearest and abs(nearest[0] - age_hours) <= max_gap / 2:
        return float(nearest[1])
    return None


def _curve_keys(video: dict[str, Any]) -> list[tuple[str, ...]]:
    """Most specific first: this channel's content type, this channel, this content type across SBA."""
    return [
        ("channel_type", video["entity_key"], video["content_type"]),
        ("channel", video["entity_key"]),
        ("type", video["content_type"]),
    ]


@dataclass
class GrowthModel:
    # curve key -> anchor hour -> median share of day-7 views reached at that age
    curves: dict[tuple[str, ...], dict[float, float]] = field(default_factory=dict)
    samples: dict[tuple[str, ...], int] = field(default_factory=dict)  # finished videos behind each curve

    def share_at(self, video: dict[str, Any], age_hours: float) -> tuple[float, tuple[str, ...]] | None:
        """Typical share of day-7 views a video like this has at `age_hours`, interpolated in log-age."""
        if age_hours < ANCHOR_HOURS[0] or age_hours >= HORIZON_HOURS:
            return None
        anchors = [*ANCHOR_HOURS, HORIZON_HOURS]
        i = max(j for j, a in enumerate(anchors) if a <= age_hours)
        lo, hi = anchors[i], anchors[i + 1]
        for key in _curve_keys(video):
            curve = self.curves.get(key, {})
            f_lo = curve.get(lo)
            f_hi = 1.0 if hi == HORIZON_HOURS else curve.get(hi)
            if f_lo is None or f_hi is None:
                continue
            if age_hours == lo:
                return f_lo, key
            t = math.log(age_hours / lo) / math.log(hi / lo)
            return f_lo + (f_hi - f_lo) * t, key
        return None

    def predict(self, video: dict[str, Any], views_now: float, age_hours: float) -> int | None:
        share = self.share_at(video, age_hours)
        if share is None or share[0] <= 0:
            return None
        return int(round(max(views_now, views_now / min(share[0], 1.0))))


def build_growth_model(videos: dict[str, dict[str, Any]], series: dict[str, Series]) -> GrowthModel:
    """Median share-of-day-7 curves from every video whose day-7 views are known."""
    shares: dict[tuple[str, ...], dict[float, list[float]]] = {}
    finished: dict[tuple[str, ...], int] = {}
    for video_id, points in series.items():
        v7 = views_at_age(points, HORIZON_HOURS)
        if not v7:
            continue
        keys = _curve_keys(videos[video_id])
        for key in keys:
            finished[key] = finished.get(key, 0) + 1
        for anchor in ANCHOR_HOURS:
            v = views_at_age(points, anchor)
            if v is None:
                continue
            for key in keys:
                shares.setdefault(key, {}).setdefault(anchor, []).append(min(v / v7, 1.0))
    model = GrowthModel()
    for key, by_anchor in shares.items():
        curve = {a: statistics.median(vals) for a, vals in by_anchor.items() if len(vals) >= MIN_CURVE_SAMPLES}
        if curve:
            model.curves[key] = curve
            model.samples[key] = finished[key]
    return model


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------


def _window(videos: list[dict[str, Any]]) -> str:
    dates = [v["published_at"] for v in videos]
    return f"{min(dates):%Y-%m-%d} → {max(dates):%Y-%m-%d}"


def run_backtest(videos: dict[str, dict[str, Any]], series: dict[str, Series], now: datetime) -> dict[str, Any]:
    """Hold out the newest ~20% of finished videos; predict their day-7 views from their day-1 views.

    Scored against a naive baseline that predicts the channel's median day-7 views
    (same content type when there's enough of it), on exactly the same test videos.
    """
    observed = []
    for video_id, points in series.items():
        v1, v7 = views_at_age(points, BACKTEST_ANCHOR_HOURS), views_at_age(points, HORIZON_HOURS)
        if v1 is not None and v7:
            observed.append((videos[video_id], v1, v7))
    observed.sort(key=lambda o: o[0]["published_at"])
    result: dict[str, Any] = {
        "method": "growth_curve_day1_to_day7",
        "status": "insufficient_history",
        "train_window": None,
        "test_window": None,
        "n_test": 0,
        "n_eligible": len(observed),
        "mape": None,
        "baseline_mape": None,
        "top10_hit_rate": None,
        "beats_baseline": None,
        "computed_at": now,
    }
    if len(observed) < MIN_BACKTEST_VIDEOS:
        return result

    test = observed[int(len(observed) * (1 - BACKTEST_TEST_SHARE)):]
    test_start = test[0][0]["published_at"]
    train_ids = {vid for vid, v in videos.items() if v["published_at"] < test_start and vid in series}
    train_videos = [videos[vid] for vid in train_ids]
    if not train_videos:
        return result
    model = build_growth_model(videos, {vid: series[vid] for vid in train_ids})

    day7_by_key: dict[tuple[str, ...], list[float]] = {}
    for vid in train_ids:
        v7 = views_at_age(series[vid], HORIZON_HOURS)
        if v7:
            for key in _curve_keys(videos[vid])[:2]:
                day7_by_key.setdefault(key, []).append(v7)
    baseline = {k: statistics.median(vals) for k, vals in day7_by_key.items() if len(vals) >= MIN_CURVE_SAMPLES}

    scored = []  # (video_id, predicted, baseline, actual)
    for video, v1, v7 in test:
        predicted = model.predict(video, v1, BACKTEST_ANCHOR_HOURS)
        base = next((baseline[k] for k in _curve_keys(video)[:2] if k in baseline), None)
        if predicted is not None and base is not None:
            scored.append((video["video_id"], predicted, base, v7))
    if len(scored) < MIN_CURVE_SAMPLES:
        return result

    def mape(index: int) -> float:
        return round(100 * statistics.fmean(abs(s[index] - s[3]) / s[3] for s in scored), 1)

    k = min(10, len(scored))
    predicted_top = {s[0] for s in sorted(scored, key=lambda s: s[1], reverse=True)[:k]}
    actual_top = {s[0] for s in sorted(scored, key=lambda s: s[3], reverse=True)[:k]}
    result.update(
        status="ok",
        train_window=_window(train_videos),
        test_window=_window([o[0] for o in test]),
        n_test=len(scored),
        mape=mape(1),
        baseline_mape=mape(2),
        top10_hit_rate=round(len(predicted_top & actual_top) / k, 2),
    )
    result["beats_baseline"] = result["mape"] < result["baseline_mape"]
    return result


# ---------------------------------------------------------------------------
# Trending
# ---------------------------------------------------------------------------


def _age_bucket(age_hours: float) -> int:
    return next(i for i, (edge, _) in enumerate(AGE_BUCKETS) if age_hours < edge)


def _saturating(ratio: float, cap: float = SATURATION_RATIO) -> float:
    """0 at ratio 0, ~0.32 at 1x (typical), 1.0 at `cap`x and beyond."""
    return min(1.0, math.log2(1 + max(ratio, 0.0)) / math.log2(1 + cap))


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


def _track_records() -> tuple[dict[tuple[str, str], tuple[float, int]], dict[str, tuple[float, int]]]:
    """Share of posts that reached VIRAL_PERFORMANCE_INDEX x their channel's usual - per channel+type and per type."""
    by_channel: dict[tuple[str, str], list[bool]] = {}
    by_type: dict[str, list[bool]] = {}
    for r in repository.analysis_records(platform=PLATFORM):
        hit = r["performance_index"] >= VIRAL_PERFORMANCE_INDEX
        by_channel.setdefault((r["entity_key"], r["content_type"]), []).append(hit)
        by_type.setdefault(r["content_type"], []).append(hit)
    summarize = lambda hits: (sum(hits) / len(hits), len(hits))  # noqa: E731
    return (
        {k: summarize(v) for k, v in by_channel.items() if len(v) >= MIN_TRACK_RECORD_SAMPLES},
        {k: summarize(v) for k, v in by_type.items() if len(v) >= MIN_TRACK_RECORD_SAMPLES},
    )


def compute_trending(hours: int = 24, limit: int = 10, now: datetime | None = None, model: GrowthModel | None = None) -> list[dict[str, Any]]:
    """Videos whose views moved in the last `hours`, ranked by viral score."""
    now = now or db.utcnow()
    with db.get_engine().connect() as conn:
        videos = _load_videos(conn)
        latest = _load_latest_two(conn)

    measured = []  # per video: velocity and where it sits among its peers
    for video_id, snaps in latest.items():
        video = videos.get(video_id)
        if video is None:
            continue
        (last_at, last_views), prev = snaps[0], (snaps[1] if len(snaps) > 1 else None)
        age = (last_at - video["published_at"]).total_seconds() / 3600
        if age <= 0:
            continue
        since_publish = False
        if prev is not None:
            gap = (last_at - prev[0]).total_seconds() / 3600
            if not MIN_VELOCITY_GAP_HOURS <= gap <= MAX_VELOCITY_GAP_HOURS:
                continue
            velocity = max(0.0, (last_views - prev[1]) / gap)
        elif age <= LIFETIME_VELOCITY_MAX_AGE_HOURS and age >= MIN_VELOCITY_GAP_HOURS:
            velocity, since_publish = last_views / age, True
        else:
            continue
        measured.append({
            "video": video, "views": last_views, "last_at": last_at, "age": age,
            "bucket": _age_bucket(age), "velocity": velocity, "since_publish": since_publish,
        })

    def medians(metric: str) -> tuple[dict, dict]:
        # Peers share the age bucket *and* how velocity was measured (a since-publish
        # average runs far higher than a later between-snapshots rate).
        per_channel: dict[tuple[str, int, bool], list[float]] = {}
        per_bucket: dict[tuple[int, bool], list[float]] = {}
        for m in measured:
            per_channel.setdefault((m["video"]["entity_key"], m["bucket"], m["since_publish"]), []).append(m[metric])
            per_bucket.setdefault((m["bucket"], m["since_publish"]), []).append(m[metric])
        pick = lambda groups: {k: statistics.median(v) for k, v in groups.items() if len(v) >= MIN_BASELINE_SAMPLES}  # noqa: E731
        return pick(per_channel), pick(per_bucket)

    velocity_channel, velocity_all = medians("velocity")
    views_channel, views_all = medians("views")
    track_channel, track_type = _track_records()

    cutoff = now - timedelta(hours=hours)
    items = []
    for m in measured:
        if m["last_at"] < cutoff:
            continue
        video = m["video"]
        key, peers_key = (video["entity_key"], m["bucket"], m["since_publish"]), (m["bucket"], m["since_publish"])
        own_baseline = key in velocity_channel
        base_velocity = velocity_channel.get(key, velocity_all.get(peers_key))
        base_views = views_channel.get(key, views_all.get(peers_key))
        if base_velocity is None or base_views is None:
            continue  # no peers to compare with - can't call it trending honestly
        velocity_index = m["velocity"] / max(base_velocity, MIN_VELOCITY_FLOOR)
        reach_ratio = m["views"] / max(base_views, 1)
        track = track_channel.get((video["entity_key"], video["content_type"]))
        track_scope = "channel" if track else "sba"
        track = track or track_type.get(video["content_type"])

        score = (
            W_MOMENTUM * _saturating(velocity_index)
            + W_REACH * _saturating(reach_ratio)
            + (W_TRACK_RECORD * min(1.0, track[0] / TRACK_RECORD_SATURATION) if track else 0.0)
        )

        peers = video["channel_name_ar"] if own_baseline else "قنوات الهيئة"
        reason = [
            f"{_fmt(m['velocity'])} مشاهدة/ساعة{' منذ النشر' if m['since_publish'] else ''}"
            f"، أي {velocity_index:.1f}× المعتاد في {peers} للمقاطع بعمر {AGE_BUCKETS[m['bucket']][1]}",
            f"مشاهداته حتى الآن ({_fmt(m['views'])}) {reach_ratio:.1f}× المعتاد لعمره",
        ]
        if track:
            label = CONTENT_TYPE_AR.get(video["content_type"], video["content_type"])
            where = "في القناة" if track_scope == "channel" else "في قنوات الهيئة"
            reason.append(f"{round(track[0] * 100)}٪ من {label} {where} تجاوزت ضعف معدلها (n={track[1]})")

        items.append({
            "video": video,
            "views_per_hour": round(m["velocity"], 1),
            "velocity_index": round(velocity_index, 2),
            "viral_score": round(score, 3),
            "predicted_views_7d": model.predict(video, m["views"], m["age"]) if model else None,
            "reason": "؛ ".join(reason),
        })
    items.sort(key=lambda i: (i["viral_score"], i["views_per_hour"]), reverse=True)
    return items[:limit]


# ---------------------------------------------------------------------------
# Cached entry points (used by the API)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_model_cache: tuple[float, GrowthModel, dict[str, Any]] | None = None
_trending_cache: dict[tuple[int, int], tuple[float, list[dict[str, Any]]]] = {}


def build(now: datetime | None = None) -> tuple[GrowthModel, dict[str, Any]]:
    """Growth model from every finished video, plus the backtest accuracy report."""
    now = now or db.utcnow()
    with db.get_engine().connect() as conn:
        videos = _load_videos(conn, published_before=now - timedelta(hours=ANCHOR_HOURS[0]))
        series = _load_series(conn, videos, max_age_hours=HORIZON_HOURS * (1 + BRACKET_GAP_SHARE))
    return build_growth_model(videos, series), run_backtest(videos, series, now)


def _model() -> tuple[GrowthModel, dict[str, Any]]:
    global _model_cache
    with _lock:
        if _model_cache is None or time.monotonic() - _model_cache[0] > MODEL_TTL_SECONDS:
            _model_cache = (time.monotonic(), *build())
        return _model_cache[1], _model_cache[2]


def model_accuracy() -> dict[str, Any]:
    return _model()[1]


def trending(hours: int = 24, limit: int = 10) -> list[dict[str, Any]]:
    cached = _trending_cache.get((hours, limit))
    if cached and time.monotonic() - cached[0] <= TRENDING_TTL_SECONDS:
        return cached[1]
    items = compute_trending(hours, limit, model=_model()[0])
    _trending_cache[(hours, limit)] = (time.monotonic(), items)
    return items


def clear_cache() -> None:
    global _model_cache
    with _lock:
        _model_cache = None
        _trending_cache.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description="Print SBA trending videos and the prediction backtest.")
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    model, accuracy = build()
    print(json.dumps(accuracy, ensure_ascii=False, indent=2, default=str))
    for item in compute_trending(args.hours, args.limit, model=model):
        print(f"{item['viral_score']:.2f}  {item['video']['channel_name_ar']}  {item['video']['title'][:60]}")
        print(f"      {item['reason']}  -> day 7: {item['predicted_views_7d']}")


if __name__ == "__main__":
    main()
