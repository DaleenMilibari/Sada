import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from backend import db, repository
from backend.agents import data_collector_agent as collector
from backend.agents import instagram_collector
from backend.agents.instagram_client import InstagramApiError, InstagramClient

from backend.tests.test_data_collector import FakeYouTube, _client as yt_client

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


class FakeGraph:
    """In-memory Business Discovery endpoint."""

    def __init__(self):
        self.accounts: dict[str, dict] = {}
        self.calls = 0
        self.error: dict | None = None  # {"status": int, "code": int, "error_subcode": int}

    def add_account(self, username, account_id, followers=1000):
        self.accounts[username] = {"id": account_id, "username": username, "name": username, "followers_count": followers, "media": []}

    def add_post(self, username, post_id, age, likes=100, comments=10, media_type="IMAGE", product="FEED", caption="منشور"):
        post = {
            "id": post_id, "caption": caption, "media_type": media_type, "media_product_type": product,
            "timestamp": (NOW - age).strftime("%Y-%m-%dT%H:%M:%S+0000"),
            "comments_count": comments, "permalink": f"https://www.instagram.com/p/{post_id}/",
        }
        if likes is not None:
            post["like_count"] = likes
        media = self.accounts[username]["media"]
        media.append(post)
        media.sort(key=lambda p: p["timestamp"], reverse=True)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        if self.error:
            e = self.error
            return httpx.Response(e["status"], json={"error": {"message": "err", "code": e["code"], "error_subcode": e.get("error_subcode")}})
        fields = request.url.params["fields"]
        username = re.search(r"business_discovery\.username\(([^)]+)\)", fields).group(1)
        if username not in self.accounts:
            return httpx.Response(400, json={"error": {"message": "Invalid user id", "code": 110, "error_subcode": 2207013}})
        after = re.search(r"media\.after\(([^)]+)\)", fields)
        start = int(after.group(1)) if after else 0
        acc = self.accounts[username]
        page = acc["media"][start : start + 50]
        media = {"data": page}
        if start + 50 < len(acc["media"]):
            media["paging"] = {"cursors": {"after": str(start + 50)}, "next": "https://graph.facebook.com/next"}
        body = {k: v for k, v in acc.items() if k != "media"}
        body["media_count"] = len(acc["media"])
        body["media"] = media
        return httpx.Response(200, json={"business_discovery": body, "id": "OUR_ACCOUNT"})


@pytest.fixture()
def graph(monkeypatch):
    g = FakeGraph()
    monkeypatch.setattr(instagram_collector, "SBA_INSTAGRAM_ACCOUNTS", [
        {"entity_key": "saudiya", "username": "saudiyatv"},
        {"entity_key": "ekhbariya", "username": "alekhbariya"},
    ])
    return g


def _ig_client(graph):
    return InstagramClient("token", "OUR_ACCOUNT", "v23.0", http=httpx.Client(transport=httpx.MockTransport(graph.handler)), backoff_seconds=0)


def _run(graph, now=NOW, youtube=None):
    return collector.run(
        "cli", client=youtube, instagram_client=_ig_client(graph), engine=db.get_engine(),
        now=now, quota_budget=100, lookback_days=60, llm_classify_limit=0,
    )


def test_collects_instagram_posts_into_shared_tables(graph):
    graph.add_account("saudiyatv", "IG1", followers=2_000_000)
    graph.add_account("alekhbariya", "IG2")
    graph.add_post("saudiyatv", "p1", timedelta(hours=5), likes=500, comments=20, media_type="VIDEO", product="REELS")
    graph.add_post("saudiyatv", "p2", timedelta(days=10), likes=None, comments=3, media_type="CAROUSEL_ALBUM")
    graph.add_post("saudiyatv", "old", timedelta(days=90))

    result = _run(graph)

    assert result["status"] == "success"
    assert result["new_videos"] == 2 and result["instagram_calls"] == 2
    with db.get_engine().connect() as conn:
        posts = {r.video_id: r for r in conn.execute(select(db.videos))}
        channel = conn.execute(select(db.channels).where(db.channels.c.channel_id == "IG1")).one()
    assert set(posts) == {"p1", "p2"}
    assert posts["p1"].platform == "instagram" and posts["p1"].content_type == "short"
    assert posts["p1"].url == "https://www.instagram.com/p/p1/"
    assert posts["p1"].view_count is None  # never fabricated
    assert posts["p2"].content_type == "carousel" and posts["p2"].like_count is None  # hidden likes stay NULL
    assert channel.platform == "instagram" and channel.subscriber_count == 2_000_000 and channel.entity_key == "saudiya"


def test_after_backfill_only_recent_posts_are_reread(graph):
    graph.add_account("saudiyatv", "IG1")
    graph.add_account("alekhbariya", "IG2")
    for n in range(120):  # 3 pages spanning ~60 days
        graph.add_post("saudiyatv", f"p{n}", timedelta(hours=12 * n + 1))
    _run(graph)
    first_calls = graph.calls

    graph.calls = 0
    result = _run(graph, now=NOW + timedelta(hours=1))

    assert first_calls == 4  # 3 pages + 1 for the second account
    assert graph.calls == 2  # backfilled: the newest page covers the 7-day refresh window
    assert result["updated_videos"] == 14  # posts from the last 7 days got a fresh snapshot


def test_unknown_account_is_reported_but_others_collected(graph):
    graph.add_account("saudiyatv", "IG1")
    graph.add_post("saudiyatv", "p1", timedelta(hours=2))

    result = _run(graph)

    assert result["status"] == "partial"
    assert "alekhbariya" in result["error"]
    assert result["new_videos"] == 1


def test_expired_token_fails_instagram_without_breaking_youtube(graph):
    graph.error = {"status": 400, "code": 190}
    youtube = FakeYouTube()
    youtube.add_video(1, "yt1", timedelta(hours=3))

    result = _run(graph, youtube=yt_client(youtube))

    assert result["status"] == "partial"  # YouTube succeeded, Instagram failed
    assert "expired" in result["error"]
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.videos.c.video_id)).scalars().all() == ["yt1"]


def test_rate_limit_ends_partial(graph):
    graph.error = {"status": 400, "code": 4}
    limited = _run(graph)
    assert limited["status"] == "partial"  # temporary - the next run resumes
    assert "rate limit" in limited["error"]

    graph.error = None
    graph.add_account("saudiyatv", "IG1")
    graph.add_account("alekhbariya", "IG2")
    assert _run(graph, now=NOW + timedelta(hours=1))["status"] == "success"


def test_cross_platform_performance_index(graph):
    graph.add_account("saudiyatv", "IG1")
    graph.add_account("alekhbariya", "IG2")
    graph.add_post("saudiyatv", "a", timedelta(days=5), likes=90, comments=10)   # 100 interactions
    graph.add_post("saudiyatv", "b", timedelta(days=6), likes=190, comments=10)  # 200 (median)
    graph.add_post("saudiyatv", "c", timedelta(days=7), likes=290, comments=10)  # 300
    _run(graph, now=db.utcnow())

    records = {r["video_id"]: r for r in repository.analysis_records(platform="instagram")}
    assert records["b"]["performance_index"] == 1.0 and records["c"]["performance_index"] == 1.5
    assert records["a"]["views_index"] is None and records["a"]["primary_metric"] == "interactions"
    assert records["a"]["engagement_rate"] is None  # no views on Instagram


def test_username_and_cursor_injection_rejected(graph):
    client = _ig_client(graph)
    with pytest.raises(InstagramApiError):
        client.media_page("saudiyatv){id}")
    with pytest.raises(InstagramApiError):
        client.media_page("saudiyatv", after="x){id}")
    assert graph.calls == 0


def test_platform_filter_skips_youtube(graph):
    youtube = FakeYouTube()
    youtube.add_video(1, "yt1", timedelta(hours=3))
    graph.add_account("saudiyatv", "IG1")
    graph.add_account("alekhbariya", "IG2")
    graph.add_post("saudiyatv", "p1", timedelta(hours=2))

    result = collector.run(
        "cli", client=yt_client(youtube), instagram_client=_ig_client(graph), engine=db.get_engine(),
        now=NOW, quota_budget=100, lookback_days=60, llm_classify_limit=0, platforms=("instagram",),
    )

    assert result["status"] == "success" and result["quota_units"] == 0 and youtube.calls == []
    assert result["new_videos"] == 1
