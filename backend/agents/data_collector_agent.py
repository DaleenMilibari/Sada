"""Task 5 - Data Collector Agent (official SBA YouTube channels + Instagram accounts).

- Goal: Keep a fresh, real per-video dataset for every official SBA YouTube
  channel (backend/sba_channels.py), including a time series of stats so the
  other agents can measure velocity (views/hour), spikes and drops.
- Input: The channel registry + what is already stored in the database.
- Trigger: In-process scheduler every COLLECTOR_INTERVAL_MINUTES, the
  POST /api/collector/run endpoint, or the CLI (python -m backend.agents.data_collector_agent).
- Tools: YouTube Data API v3 (youtube_client.py); X API v2 (x_client.py / x_collector.py); Instagram Graph API Business
  Discovery (instagram_client.py / instagram_collector.py); Gemini for topic refinement.
- Data/context: The database (backend/db.py) - channels, videos, video_snapshots, collector_runs.
- Reasoning task: Decide what is worth spending quota on. New uploads first,
  then stats refreshes prioritised by video age (young videos change fast,
  old ones barely move), all inside a fixed per-run quota budget.
- Decision: Which channels to page, when discovery has caught up, which
  videos are due a refresh, which topics to send to the LLM.
- Action/output: Upserted channel + video rows, one snapshot per refreshed
  video, and a collector_runs row summarising the run.
- Memory/state: The database itself - runs are incremental, and whether a
  channel's window is already backfilled is derived from what is stored.
- Evidence: Every number stored is exactly what the YouTube API returned at
  `captured_at`; missing metrics (hidden likes, disabled comments) stay NULL.
- Failure/fallback: Transient API errors are retried; on quota exhaustion the
  run stops cleanly with status "partial" and the next run resumes where it
  left off. Without a Gemini key, topics stay rule-based.
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Engine

from backend import config, db
from backend.agents import audience_agent, audience_collector, instagram_collector, llm_client, x_collector
from backend.agents.instagram_client import InstagramClient, InstagramRateLimited
from backend.agents.x_client import XClient, XRateLimited
from backend.agents.youtube_client import QuotaExceeded, YouTubeClient, parse_duration
from backend.sba_channels import SBA_CHANNELS
from backend.topics import TOPIC_HINTS, TOPICS, classify_by_rules

logger = logging.getLogger("sada.collector")

CHANNEL_REFRESH_EVERY = timedelta(hours=6)
STALE_RUN_AFTER = timedelta(hours=2)
CAUGHT_UP_AFTER_KNOWN = 50  # consecutive already-stored uploads => discovery has caught up
DISCOVERY_BUDGET_SHARE = 0.5  # discovery may spend at most this share of the run's budget
LLM_BATCH_SIZE = 40

# How stale a video's stats may get, by video age. Young videos move fast and
# drive trending/velocity; old ones barely change and aren't worth the quota.
REFRESH_POLICY: list[tuple[timedelta, timedelta]] = [
    (timedelta(days=2), timedelta(minutes=25)),
    (timedelta(days=7), timedelta(hours=2)),
    (timedelta(days=30), timedelta(hours=24)),
]
REFRESH_OLD = timedelta(days=7)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _int_or_none(value: Any) -> int | None:
    return int(value) if value is not None else None


def classify_content_type(item: dict[str, Any], duration: int | None) -> str:
    snippet = item.get("snippet", {})
    if snippet.get("liveBroadcastContent") in ("live", "upcoming") or "liveStreamingDetails" in item:
        return "live"
    if duration is not None:
        # The API doesn't flag Shorts. <=60s is almost always a Short; 61-180s
        # only counts when the uploader tagged it, since news clips run that long too.
        if duration <= 60:
            return "short"
        text = " ".join([snippet.get("title", ""), snippet.get("description", ""), *snippet.get("tags", [])]).lower()
        if duration <= 180 and "#short" in text:
            return "short"
    return "video"


def parse_video(item: dict[str, Any], channel_id: str, default_topic: str, now: datetime) -> dict[str, Any]:
    snippet = item["snippet"]
    stats = item.get("statistics", {})
    duration = parse_duration(item.get("contentDetails", {}).get("duration"))
    title = snippet.get("title", "")
    return {
        "video_id": item["id"],
        "platform": "youtube",
        "channel_id": channel_id,
        "title": title,
        "url": f"https://www.youtube.com/watch?v={item['id']}",
        "published_at": _parse_ts(snippet.get("publishedAt")) or now,
        "duration_seconds": duration,
        "content_type": classify_content_type(item, duration),
        "topic": classify_by_rules(title, default_topic),
        "topic_source": "rule",
        "view_count": _int_or_none(stats.get("viewCount")),
        "like_count": _int_or_none(stats.get("likeCount")),
        "comment_count": _int_or_none(stats.get("commentCount")),
        "first_seen_at": now,
        "stats_updated_at": now,
    }


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _sync_channels(conn, client: YouTubeClient, now: datetime) -> list[dict[str, Any]]:
    stored = {
        r.entity_key: r._asdict()
        for r in conn.execute(select(db.channels).where(db.channels.c.platform == "youtube"))
    }
    result = []
    for spec in SBA_CHANNELS:
        row = stored.get(spec["entity_key"])
        fresh = row and row["uploads_playlist_id"] and db.as_utc(row["updated_at"]) > now - CHANNEL_REFRESH_EVERY
        if not fresh:
            item = client.channel_by_handle(spec["handle"])
            if item is None:
                logger.warning("Channel %s not found on YouTube - skipping", spec["handle"])
                continue
            stats = item.get("statistics", {})
            row = {
                "channel_id": item["id"],
                "platform": "youtube",
                "entity_key": spec["entity_key"],
                "handle": spec["handle"],
                "name_ar": spec["name_ar"],
                "title": item["snippet"]["title"],
                "uploads_playlist_id": item["contentDetails"]["relatedPlaylists"]["uploads"],
                "subscriber_count": _int_or_none(stats.get("subscriberCount")),
                "video_count": _int_or_none(stats.get("videoCount")),
                "view_count": _int_or_none(stats.get("viewCount")),
                "updated_at": now,
            }
            db.upsert(conn, db.channels, [row], "channel_id", [c for c in row if c != "channel_id"])
            db.record_followers(conn, [row], now)
        result.append({**row, "default_topic": spec["default_topic"]})
    return result


def _discover_new(conn, client: YouTubeClient, channel: dict[str, Any], cutoff: datetime, unit_limit: int) -> list[str]:
    """Walk the uploads playlist newest-first and return unseen video ids inside the window.

    While a channel's window isn't backfilled yet (nothing stored near the cutoff
    and below the per-channel cap), keep paging past already-known videos; once
    caught up, stop after CAUGHT_UP_AFTER_KNOWN consecutive known uploads.
    """
    known = set(
        conn.execute(
            select(db.videos.c.video_id).where(
                and_(db.videos.c.channel_id == channel["channel_id"], db.videos.c.published_at >= cutoff)
            )
        ).scalars()
    )
    oldest_known = conn.execute(
        select(func.min(db.videos.c.published_at)).where(db.videos.c.channel_id == channel["channel_id"])
    ).scalar()
    backfilled = len(known) >= config.COLLECTOR_MAX_VIDEOS_PER_CHANNEL or (
        oldest_known is not None and db.as_utc(oldest_known) <= cutoff + timedelta(days=1)
    )

    new_ids: list[str] = []
    consecutive_known = 0
    for item in client.iter_uploads(channel["uploads_playlist_id"]):
        published = _parse_ts(item.get("videoPublishedAt"))
        if published is None:
            continue  # private/deleted upload
        if published < cutoff:
            break
        if item["videoId"] in known:
            consecutive_known += 1
            if backfilled and consecutive_known >= CAUGHT_UP_AFTER_KNOWN:
                break
        else:
            consecutive_known = 0
            new_ids.append(item["videoId"])
        if len(new_ids) >= config.COLLECTOR_MAX_VIDEOS_PER_CHANNEL:
            break
        if client.units_used >= unit_limit:
            break
    return new_ids


def _due_for_refresh(conn, cutoff: datetime, now: datetime, exclude: set[str]) -> list[str]:
    rows = conn.execute(
        select(db.videos.c.video_id, db.videos.c.published_at, db.videos.c.stats_updated_at)
        .where(db.videos.c.published_at >= cutoff)
        .where(db.videos.c.platform == "youtube")
        .order_by(db.videos.c.published_at.desc())
    )
    due = []
    for video_id, published_at, stats_updated_at in rows:
        if video_id in exclude:
            continue
        age = now - db.as_utc(published_at)
        max_staleness = next((stale for max_age, stale in REFRESH_POLICY if age <= max_age), REFRESH_OLD)
        last = db.as_utc(stats_updated_at)
        if last is None or now - last >= max_staleness:
            due.append(video_id)
    return due  # newest first, so the budget goes to the fastest-moving videos


def _fetch_and_store(conn, client: YouTubeClient, ids: list[str], channels_by_id: dict[str, dict], now: datetime) -> tuple[int, int]:
    if not ids:
        return 0, 0
    existing = set(conn.execute(select(db.videos.c.video_id).where(db.videos.c.video_id.in_(ids))).scalars())
    rows = []
    for item in client.videos(ids):
        channel = channels_by_id.get(item["snippet"]["channelId"])
        if channel is None:
            continue
        rows.append(parse_video(item, channel["channel_id"], channel["default_topic"], now))
    stats_cols = [
        "title", "url", "duration_seconds", "content_type", "view_count", "like_count", "comment_count", "stats_updated_at",
    ]
    db.upsert(conn, db.videos, rows, "video_id", stats_cols)
    snapshots = [
        {
            "video_id": r["video_id"],
            "captured_at": now,
            "view_count": r["view_count"],
            "like_count": r["like_count"],
            "comment_count": r["comment_count"],
        }
        for r in rows
    ]
    if snapshots:
        conn.execute(insert(db.video_snapshots), snapshots)
    new = sum(1 for r in rows if r["video_id"] not in existing)
    return new, len(rows) - new


def _refine_topics_with_llm(engine: Engine, limit: int) -> int:
    if limit <= 0:
        return 0
    with engine.connect() as conn:
        pending = conn.execute(
            select(db.videos.c.video_id, db.videos.c.title, db.channels.c.name_ar)
            .join(db.channels, db.videos.c.channel_id == db.channels.c.channel_id)
            .where(db.videos.c.topic_source == "rule")
            .order_by(db.videos.c.published_at.desc())
            .limit(limit)
        ).all()
    classified = 0
    topic_list = "\n".join(f'- "{k}" ({v}): {TOPIC_HINTS.get(k, "")}' for k, v in TOPICS.items())
    for i in range(0, len(pending), LLM_BATCH_SIZE):
        batch = pending[i : i + LLM_BATCH_SIZE]
        lines = "\n".join(f"{vid} | {channel} | {title}" for vid, title, channel in batch)
        prompt = (
            "صنّف كل منشور من حسابات هيئة الإذاعة والتلفزيون السعودية إلى موضوع واحد فقط من القائمة التالية، "
            'واختر الأدق، ولا تستخدم "other" إلا إذا لم يناسبه أي موضوع آخر:\n'
            f"{topic_list}\n"
            "كل سطر بالشكل: معرف الفيديو | القناة | العنوان.\n"
            f"{lines}\n"
            'أعد كائن JSON فقط يربط كل معرف فيديو بمفتاح الموضوع بالإنجليزية، مثال: {"abc123": "news"}'
        )
        try:
            mapping = json.loads(llm_client.generate_json(prompt))
        except llm_client.MissingApiKeyError:
            return classified
        except Exception:
            logger.exception("LLM topic classification failed - keeping rule-based topics")
            return classified
        if not isinstance(mapping, dict):
            continue
        updates = [
            {"vid": vid, "topic": mapping[vid]}
            for vid, _, _ in batch
            if isinstance(mapping.get(vid), str) and mapping[vid] in TOPICS
        ]
        if updates:
            from sqlalchemy import bindparam

            with engine.begin() as conn:
                conn.execute(
                    update(db.videos)
                    .where(db.videos.c.video_id == bindparam("vid"))
                    .values(topic=bindparam("topic"), topic_source="llm"),
                    updates,
                )
            classified += len(updates)
    return classified


def _collect_youtube(engine: Engine, client: YouTubeClient, now: datetime, cutoff: datetime, budget: int, summary: dict) -> bool:
    """Discover + refresh YouTube videos inside `budget` units. Returns True if the budget cut the run short."""
    with engine.begin() as conn:
        channel_rows = _sync_channels(conn, client, now)
    channels_by_id = {c["channel_id"]: c for c in channel_rows}

    discovery_limit = int(budget * DISCOVERY_BUDGET_SHARE)
    new_ids: list[str] = []
    with engine.connect() as conn:
        for channel in channel_rows:
            if client.units_used >= discovery_limit:
                break
            new_ids.extend(_discover_new(conn, client, channel, cutoff, discovery_limit))
    discovery_cut_short = client.units_used >= discovery_limit

    with engine.connect() as conn:
        due = _due_for_refresh(conn, cutoff, now, exclude=set(new_ids))
    remaining_calls = max(budget - client.units_used, 0)
    to_fetch = (new_ids + due)[: remaining_calls * 50]

    # Commit per 500 videos so a quota/network failure mid-run keeps what was already collected.
    for i in range(0, len(to_fetch), 500):
        with engine.begin() as conn:
            new, updated = _fetch_and_store(conn, client, to_fetch[i : i + 500], channels_by_id, now)
        summary["new_videos"] += new
        summary["updated_videos"] += updated
        summary["snapshots"] += new + updated

    return discovery_cut_short or len(new_ids) + len(due) > len(to_fetch)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    trigger: str = "manual",
    *,
    client: YouTubeClient | None = None,
    instagram_client: InstagramClient | None = None,
    x_client: XClient | None = None,
    engine: Engine | None = None,
    now: datetime | None = None,
    quota_budget: int | None = None,
    lookback_days: int | None = None,
    llm_classify_limit: int | None = None,
    platforms: tuple[str, ...] = ("youtube", "instagram", "x"),
) -> dict[str, Any]:
    engine = engine or db.get_engine()
    now = now or db.utcnow()
    budget = quota_budget if quota_budget is not None else config.COLLECTOR_QUOTA_PER_RUN
    cutoff = now - timedelta(days=lookback_days if lookback_days is not None else config.COLLECTOR_LOOKBACK_DAYS)
    llm_limit = llm_classify_limit if llm_classify_limit is not None else config.COLLECTOR_LLM_CLASSIFY_PER_RUN

    db.init_db(engine)
    with engine.begin() as conn:
        running = conn.execute(
            select(func.count())
            .select_from(db.collector_runs)
            .where(and_(db.collector_runs.c.status == "running", db.collector_runs.c.started_at > now - STALE_RUN_AFTER))
        ).scalar()
        if running:
            return {"status": "skipped", "reason": "another collector run is in progress"}
        run_id = conn.execute(
            insert(db.collector_runs).values(trigger=trigger, status="running", started_at=now)
        ).inserted_primary_key[0]

    summary = {
        "run_id": run_id, "status": "success", "new_videos": 0, "updated_videos": 0, "snapshots": 0,
        "llm_classified": 0, "quota_units": 0, "instagram_calls": 0, "x_posts_read": 0,
        "audience_comments": 0, "audience_classified": 0, "error": None,
    }
    errors: list[str] = []
    partial = False
    sources_tried = sources_failed = 0

    # --- YouTube --------------------------------------------------------------
    if "youtube" in platforms and (client is not None or config.YOUTUBE_API_KEY):
        sources_tried += 1
        client = client or YouTubeClient(config.YOUTUBE_API_KEY)
        try:
            partial |= _collect_youtube(engine, client, now, cutoff, budget, summary)
            summary["audience_comments"] += audience_collector.collect_youtube(engine, client, now)
        except QuotaExceeded as e:
            partial = True
            errors.append(f"youtube: {e}")
        except Exception as e:
            logger.exception("YouTube collection failed in run %s", run_id)
            sources_failed += 1
            errors.append(f"youtube: {type(e).__name__}: {e}")
        finally:
            summary["quota_units"] = client.units_used

    # --- Instagram ------------------------------------------------------------
    if "instagram" not in platforms:
        instagram_client = None
    elif instagram_client is None and config.INSTAGRAM_ENABLED:
        instagram_client = InstagramClient(
            config.META_ACCESS_TOKEN, config.INSTAGRAM_BUSINESS_ACCOUNT_ID, config.META_GRAPH_API_VERSION
        )
    if instagram_client is not None:
        sources_tried += 1
        try:
            ig = instagram_collector.collect(engine, instagram_client, now, cutoff)
            summary["new_videos"] += ig["new"]
            summary["updated_videos"] += ig["updated"]
            summary["snapshots"] += ig["new"] + ig["updated"]
            if ig["errors"]:
                partial = True
                errors.extend(ig["errors"])
        except InstagramRateLimited as e:
            partial = True
            errors.append(f"instagram: {e}")
        except Exception as e:
            logger.exception("Instagram collection failed in run %s", run_id)
            sources_failed += 1
            errors.append(f"instagram: {type(e).__name__}: {e}")
        finally:
            summary["instagram_calls"] = instagram_client.calls

    # --- X --------------------------------------------------------------------
    if "x" not in platforms:
        x_client = None
    elif x_client is None and config.X_ENABLED:
        x_client = XClient(config.X_BEARER_TOKEN)
    if x_client is not None:
        sources_tried += 1
        xr: dict[str, Any] = {"new": 0, "updated": 0, "errors": []}
        try:
            x_collector.collect(engine, x_client, now, cutoff, xr)
            ar = audience_collector.collect_x(engine, x_client, now)
            summary["audience_comments"] += ar["stored"]
            xr["errors"] += ar["errors"]
            if xr["errors"]:
                partial = True
                errors.extend(xr["errors"])
        except XRateLimited as e:
            partial = True
            errors.append(f"x: {e}")
        except Exception as e:
            logger.exception("X collection failed in run %s", run_id)
            sources_failed += 1
            errors.append(f"x: {type(e).__name__}: {e}")
        finally:
            summary["x_posts_read"] = x_client.posts_read
            summary["new_videos"] += xr["new"]  # pages stored before an error still count
            summary["updated_videos"] += xr["updated"]
            summary["snapshots"] += xr["new"] + xr["updated"]

    if sources_tried == 0:
        errors.append(
            "No data source configured: set YOUTUBE_API_KEY, META_ACCESS_TOKEN + INSTAGRAM_BUSINESS_ACCOUNT_ID, and/or X_BEARER_TOKEN."
        )
    else:
        summary["llm_classified"] = _refine_topics_with_llm(engine, llm_limit)
        summary["audience_classified"] = audience_agent.classify_pending(config.AUDIENCE_LLM_CLASSIFY_PER_RUN)

    if sources_tried == 0 or sources_failed == sources_tried:
        summary["status"] = "failed"
    elif sources_failed or partial:
        summary["status"] = "partial"  # the next run picks up whatever was missed
    summary["error"] = "; ".join(errors) or None

    with engine.begin() as conn:
        conn.execute(
            update(db.collector_runs)
            .where(db.collector_runs.c.id == run_id)
            .values(
                status=summary["status"],
                finished_at=db.utcnow(),
                new_videos=summary["new_videos"],
                updated_videos=summary["updated_videos"],
                snapshots=summary["snapshots"],
                llm_classified=summary["llm_classified"],
                quota_units=summary["quota_units"],
                instagram_calls=summary["instagram_calls"],
                error=summary["error"],
            )
        )
    logger.info("Collector run %s finished: %s", run_id, summary)
    return summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Collect SBA YouTube + Instagram data into the database.")
    parser.add_argument("--budget", type=int, help="YouTube quota units this run may spend")
    parser.add_argument("--lookback", type=int, help="days of uploads to track")
    parser.add_argument("--llm-limit", type=int, help="videos to topic-classify with Gemini")
    parser.add_argument("--platform", choices=["all", "youtube", "instagram", "x"], default="all", help="which source(s) to collect")
    args = parser.parse_args()
    result = run(
        "cli",
        quota_budget=args.budget,
        lookback_days=args.lookback,
        llm_classify_limit=args.llm_limit,
        platforms=("youtube", "instagram", "x") if args.platform == "all" else (args.platform,),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
