"""Import Instagram posts exported from Apify's website into the Sada database.

For when you run Apify's Instagram Scraper yourself in the browser (no token in this project),
download the result as JSON, and load it here:

    python -m backend.apify_import posts.json
    python -m backend.apify_import posts.json --profiles profiles.json   # adds follower counts

Only accounts listed in SBA_INSTAGRAM_ACCOUNTS (backend/sba_channels.py) are imported. Posts from
any other account in the file are skipped and reported. Re-importing is safe: posts are upserted
and each import adds one snapshot per post.

Hidden like counts (-1) are stored as missing, never as 0. Views are not stored (see
apify_instagram_client.py).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from backend import db
from backend.agents import instagram_collector
from backend.agents.apify_instagram_client import _to_graph_item
from backend.sba_channels import BY_ENTITY, SBA_INSTAGRAM_ACCOUNTS


def load_items(path: Path) -> list[dict[str, Any]]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path}: expected a JSON list (Apify's 'Download as JSON' export).")
    return [item for item in data if isinstance(item, dict)]


def import_posts(
    engine: Engine,
    posts: list[dict[str, Any]],
    profiles: list[dict[str, Any]] | None = None,
    *,
    accounts: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Store Apify post items. Returns {"accounts": {username: {...}}, "skipped": {owner: n}, "problems": [...]}."""
    db.init_db(engine)
    accounts = SBA_INSTAGRAM_ACCOUNTS if accounts is None else accounts
    now = now or db.utcnow()
    entity_by_user = {a["username"].lower(): a["entity_key"] for a in accounts}
    profile_by_user = {str(p["username"]).lower(): p for p in profiles or [] if p.get("username")}

    by_owner: dict[str, list[dict[str, Any]]] = defaultdict(list)
    skipped: dict[str, int] = defaultdict(int)
    problems: list[str] = []
    for post in posts:
        if post.get("error"):
            problems.append(f"Apify reported an error item: {post.get('errorDescription') or post['error']}")
            continue
        owner = str(post.get("ownerUsername") or "").lower()
        if owner in entity_by_user:
            by_owner[owner].append(post)
        else:
            skipped[owner or "(no owner field)"] += 1

    report: dict[str, Any] = {"accounts": {}, "skipped": dict(skipped), "problems": problems}
    for owner, items in by_owner.items():
        profile = profile_by_user.get(owner, {})
        account_id = profile.get("id") or next((p.get("ownerId") for p in items if p.get("ownerId")), None)
        if not account_id:
            problems.append(f"@{owner}: the file has no account id. Also load that account's profile export with --profiles.")
            continue
        entity_key = entity_by_user[owner]
        account = {
            "id": str(account_id),
            "username": items[0].get("ownerUsername") or owner,
            "name": profile.get("fullName") or items[0].get("ownerFullName"),
            "followers_count": profile.get("followersCount"),
            "media_count": profile.get("postsCount"),
        }
        default_topic = BY_ENTITY[entity_key]["default_topic"]
        rows: dict[str, dict[str, Any]] = {}
        for post in items:
            graph_item = _to_graph_item(post)
            row = instagram_collector.parse_media(graph_item, account["id"], default_topic, now) if graph_item else None
            if row:
                rows[row["video_id"]] = row  # a post listed twice is stored once
        new, updated = instagram_collector._store(engine, account, entity_key, list(rows.values()), now)
        report["accounts"][owner] = {"entity_key": entity_key, "posts": len(rows), "new": new, "updated": updated}
        if len(rows) < len(items):
            problems.append(f"@{owner}: {len(items) - len(rows)} item(s) skipped (no id or timestamp, or listed twice).")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import an Apify Instagram export into the Sada database.")
    parser.add_argument("posts", type=Path, help="JSON export of the 'Posts' run")
    parser.add_argument("--profiles", type=Path, help="JSON export of a 'Details' run (adds follower counts)")
    args = parser.parse_args(argv)

    try:
        posts = load_items(args.posts)
        profiles = load_items(args.profiles) if args.profiles else None
    except (OSError, ValueError) as e:
        print(f"Could not read the file: {e}")
        return 2

    report = import_posts(db.get_engine(), posts, profiles)
    if not report["accounts"]:
        print("Nothing imported.")
    for owner, r in report["accounts"].items():
        print(f"  @{owner} ({r['entity_key']}): {r['posts']} posts, {r['new']} new, {r['updated']} updated")
    for owner, count in report["skipped"].items():
        print(f"  skipped {count} post(s) from @{owner}: not in SBA_INSTAGRAM_ACCOUNTS (backend/sba_channels.py)")
    for problem in report["problems"]:
        print(f"  note: {problem}")
    return 0 if report["accounts"] else 1


if __name__ == "__main__":
    sys.exit(main())
