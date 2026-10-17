"""Import an Instagram scraper export (Apify instagram-scraper JSON) into the SQL tables.

Posts land in `channels` / `videos` / `video_snapshots` and comments in `audience_comments`,
in the same shape the live collector (agents/instagram_collector.py) writes, so every
agent and dashboard view reads them like any other Instagram post:

    python -m backend.instagram_import backend/data/dataset_instagram-scraper_2026-10-16_15-39-19-781.json

Safe to re-run: the scrape time (taken from the file name) is the snapshot time, so a second
run adds nothing, and it never overwrites stats a later collector run has refreshed.
Accounts not in SBA_INSTAGRAM_ACCOUNTS and items the scraper reports as errors are skipped.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import insert, select

from backend import db
from backend.sba_channels import BY_ENTITY, SBA_INSTAGRAM_ACCOUNTS
from backend.topics import classify_by_rules

_ENTITY_BY_USERNAME = {a["username"].lower(): a["entity_key"] for a in SBA_INSTAGRAM_ACCOUNTS}
# Scraper type/productType -> our content_type (reels are "clips", like YouTube shorts).
_CONTENT_TYPES = {"Image": "image", "Sidecar": "carousel", "Video": "video"}


def scraped_at(path: Path) -> datetime:
    """The scrape time encoded in the export's name (..._2026-10-16_15-39-19-781.json), else now."""
    m = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{2})-(\d{2})-(\d{2})", path.name)
    if not m:
        return db.utcnow()
    return datetime.fromisoformat(f"{m[1]}T{m[2]}:{m[3]}:{m[4]}").replace(tzinfo=timezone.utc)


def parse_timestamp(value: str | None) -> datetime | None:
    """Scraper timestamps look like 2026-10-05T13:28:15.000Z."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _count(value: Any) -> int | None:
    # The scraper reports hidden likes as -1 or null - never treat those as 0.
    return int(value) if value is not None and int(value) >= 0 else None


def content_type(item: dict[str, Any]) -> str:
    if item.get("productType") == "clips":
        return "short"
    return _CONTENT_TYPES.get(item.get("type", ""), "image")


def parse_post(item: dict[str, Any], default_topic: str, now: datetime) -> dict[str, Any] | None:
    published = parse_timestamp(item.get("timestamp"))
    if published is None or not item.get("id"):
        return None
    caption = item.get("caption") or ""
    duration = item.get("videoDuration")
    return {
        "video_id": str(item["id"]),
        "platform": "instagram",
        "channel_id": str(item["ownerId"]),
        "title": caption,
        "url": item.get("url"),
        "published_at": published,
        "duration_seconds": round(duration) if duration else None,
        "content_type": content_type(item),
        "topic": classify_by_rules(caption, default_topic),
        "topic_source": "rule",
        # Kept NULL like the live collector: Instagram's main metric is likes + comments
        # everywhere (repository.py), and image/carousel posts have no view count at all.
        "view_count": None,
        "like_count": _count(item.get("likesCount")),
        "comment_count": _count(item.get("commentsCount")),
        "first_seen_at": now,
        "stats_updated_at": now,
    }


def parse_comments(item: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Top-level comments and their replies. Only what was said is kept - no author (PDPL)."""
    out = []
    pending = list(item.get("latestComments") or [])
    while pending:
        c = pending.pop()
        pending.extend(c.get("replies") or [])
        published = parse_timestamp(c.get("timestamp"))
        text = (c.get("text") or "").strip()
        if not c.get("id") or published is None or not text:
            continue
        out.append({
            "comment_id": f"ig_{c['id']}",
            "platform": "instagram",
            "video_id": str(item["id"]),
            "text": text,
            "published_at": published,
            "like_count": _count(c.get("likesCount")),
            "collected_at": now,
        })
    return out


def import_file(path: Path) -> dict[str, Any]:
    db.init_db()
    now = scraped_at(path)
    items = json.loads(path.read_text(encoding="utf-8"))

    channel_rows: dict[str, dict[str, Any]] = {}
    posts: list[dict[str, Any]] = []
    comments: list[dict[str, Any]] = []
    skipped: set[str] = set()
    for item in items:
        username = (item.get("ownerUsername") or item.get("username") or "").lower()
        entity_key = _ENTITY_BY_USERNAME.get(username)
        if item.get("error") or entity_key is None:
            skipped.add(username or "?")
            continue
        post = parse_post(item, BY_ENTITY[entity_key]["default_topic"], now)
        if post is None:
            continue
        posts.append(post)
        comments += parse_comments(item, now)
        channel_rows.setdefault(post["channel_id"], {
            "channel_id": post["channel_id"],
            "platform": "instagram",
            "entity_key": entity_key,
            "handle": f"@{item['ownerUsername']}",
            "name_ar": BY_ENTITY[entity_key]["name_ar"],
            "title": item.get("ownerFullName") or BY_ENTITY[entity_key]["name_ar"],
            "uploads_playlist_id": None,
            "subscriber_count": None,  # the post scrape carries no follower count
            "video_count": None,
            "view_count": None,
            "updated_at": now,
        })

    with db.get_engine().begin() as conn:
        # Accounts the collector already stored keep their (fresher) follower counts.
        known = set(conn.execute(select(db.channels.c.channel_id).where(db.channels.c.channel_id.in_(list(channel_rows)))).scalars())
        new_channels = [r for cid, r in channel_rows.items() if cid not in known]
        if new_channels:
            conn.execute(insert(db.channels), new_channels)

        # Upsert a post only when this scrape is newer than what is stored.
        ids = [p["video_id"] for p in posts]
        stored = dict(conn.execute(
            select(db.videos.c.video_id, db.videos.c.stats_updated_at).where(db.videos.c.video_id.in_(ids))
        ).all())
        fresh = [p for p in posts if p["video_id"] not in stored or (db.as_utc(stored[p["video_id"]]) or now) < now]
        db.upsert(
            conn, db.videos, fresh, "video_id",
            ["title", "url", "content_type", "like_count", "comment_count", "stats_updated_at"],
        )
        snapped = set(conn.execute(
            select(db.video_snapshots.c.video_id).where(
                db.video_snapshots.c.video_id.in_(ids), db.video_snapshots.c.captured_at == now
            )
        ).scalars())
        snapshots = [
            {"video_id": p["video_id"], "captured_at": now, "view_count": None,
             "like_count": p["like_count"], "comment_count": p["comment_count"]}
            for p in posts if p["video_id"] not in snapped
        ]
        if snapshots:
            conn.execute(insert(db.video_snapshots), snapshots)

        # Insert-only, so classifications the audience agent already made are kept.
        have = set(conn.execute(
            select(db.audience_comments.c.comment_id).where(
                db.audience_comments.c.comment_id.in_([c["comment_id"] for c in comments])
            )
        ).scalars())
        new_comments = [c for c in comments if c["comment_id"] not in have]
        if new_comments:
            conn.execute(insert(db.audience_comments), new_comments)

    return {
        "scraped_at": now.isoformat(),
        "channels_new": len(new_channels),
        "posts_new": sum(1 for p in posts if p["video_id"] not in stored),
        "posts_updated": sum(1 for p in fresh if p["video_id"] in stored),
        "snapshots": len(snapshots),
        "comments_new": len(new_comments),
        "skipped_accounts": sorted(skipped),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", type=Path)
    print(json.dumps(import_file(parser.parse_args().path), ensure_ascii=False))
