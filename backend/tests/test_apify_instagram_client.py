import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from backend import db
from backend.agents import data_collector_agent as collector
from backend.agents import instagram_collector
from backend.agents.apify_instagram_client import ApifyInstagramClient
from backend.agents.instagram_client import (
    InstagramAccountNotFound,
    InstagramApiError,
    InstagramAuthError,
    InstagramRateLimited,
)

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


class FakeApify:
    """In-memory stand-in for Apify's run-sync-get-dataset-items endpoint."""

    def __init__(self):
        self.profiles: dict[str, dict] = {}
        self.posts: dict[str, list[dict]] = {}
        self.requests: list[dict] = []
        self.status: int | None = None  # force an error status

    def add_account(self, username, account_id="111", followers=2_000_000, posts_count=500):
        self.profiles[username] = {
            "id": account_id, "username": username, "fullName": f"{username} channel",
            "followersCount": followers, "postsCount": posts_count,
        }
        self.posts[username] = []

    def add_post(self, username, post_id, age, *, likes=100, comments=10, kind="Image", product="feed", views=None):
        self.posts[username].append(
            {
                "id": post_id, "shortCode": f"sc{post_id}", "type": kind, "productType": product,
                "caption": "منشور", "url": f"https://www.instagram.com/p/sc{post_id}/",
                "likesCount": likes, "commentsCount": comments, "videoViewCount": views,
                "timestamp": (NOW - age).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            }
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append({"body": body, "auth": request.headers.get("authorization"), "url": str(request.url)})
        if self.status:
            return httpx.Response(self.status, json={"error": {"message": "nope"}})
        username = body["directUrls"][0].rstrip("/").rsplit("/", 1)[-1]
        if username not in self.profiles:
            return httpx.Response(201, json=[{"error": "no_items", "errorDescription": "not found"}])
        if body["resultsType"] == "details":
            return httpx.Response(201, json=[self.profiles[username]])
        return httpx.Response(201, json=self.posts[username][: body["resultsLimit"]])


@pytest.fixture()
def apify():
    return FakeApify()


def _client(apify, now=lambda: NOW, **kwargs):
    return ApifyInstagramClient(
        "tok", http=httpx.Client(transport=httpx.MockTransport(apify.handler)), backoff_seconds=0, now=now, **kwargs
    )


def test_posts_are_returned_in_graph_api_shape(apify):
    apify.add_account("saudiyatv")
    apify.add_post("saudiyatv", "1", timedelta(days=3), likes=-1, comments=4)  # hidden likes
    apify.add_post("saudiyatv", "2", timedelta(hours=2), likes=900, comments=30, kind="Video", product="clips", views=50_000)
    apify.add_post("saudiyatv", "3", timedelta(days=1), kind="Sidecar", product="carousel_container")

    account, items, after = _client(apify).media_page("saudiyatv")

    assert after is None
    assert account == {"id": "111", "username": "saudiyatv", "name": "saudiyatv channel", "followers_count": 2_000_000, "media_count": 500}
    assert [i["id"] for i in items] == ["2", "3", "1"]  # newest first
    reel, carousel, hidden = items
    assert (reel["media_type"], reel["media_product_type"], reel["video_view_count"]) == ("VIDEO", "REELS", 50_000)
    assert carousel["media_type"] == "CAROUSEL_ALBUM" and carousel["media_product_type"] == "FEED"
    assert hidden["like_count"] is None and hidden["comments_count"] == 4  # -1 is never stored as a number
    assert reel["timestamp"] == (NOW - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    assert reel["permalink"] == "https://www.instagram.com/p/sc2/"


def test_token_goes_in_a_header_not_the_url(apify):
    apify.add_account("saudiyatv")
    _client(apify).media_page("saudiyatv")
    assert all(r["auth"] == "Bearer tok" and "tok" not in r["url"] for r in apify.requests)


def test_unknown_account_raises_not_found(apify):
    with pytest.raises(InstagramAccountNotFound):
        _client(apify).media_page("nobody_here")


def test_bad_username_never_reaches_apify(apify):
    with pytest.raises(InstagramApiError):
        _client(apify).media_page("../evil?x=1")
    assert apify.requests == []


@pytest.mark.parametrize(
    ("status", "error"), [(401, InstagramAuthError), (403, InstagramAuthError), (402, InstagramRateLimited), (429, InstagramRateLimited)]
)
def test_error_statuses_map_to_the_collectors_exceptions(apify, status, error):
    apify.status = status
    with pytest.raises(error):
        _client(apify).media_page("saudiyatv")


def test_recent_fetch_is_skipped_to_save_apify_spend(apify):
    apify.add_account("saudiyatv")
    apify.add_post("saudiyatv", "1", timedelta(hours=1))
    clock = {"now": NOW}
    client = _client(apify, now=lambda: clock["now"], min_interval_minutes=360, lookback_days=60, refresh_days=7)

    _, first, _ = client.media_page("saudiyatv")
    runs_after_first = len(apify.requests)
    clock["now"] = NOW + timedelta(minutes=30)
    account, second, _ = client.media_page("saudiyatv")

    assert len(first) == 1 and second == []  # no duplicate snapshots
    assert len(apify.requests) == runs_after_first  # and no new Apify runs
    assert account["username"] == "saudiyatv"

    clock["now"] = NOW + timedelta(hours=7)
    _, third, _ = client.media_page("saudiyatv")
    assert len(third) == 1 and len(apify.requests) > runs_after_first


def test_first_fetch_backfills_then_only_recent_days(apify):
    apify.add_account("saudiyatv")
    clock = {"now": NOW}
    client = _client(apify, now=lambda: clock["now"], min_interval_minutes=60, lookback_days=60, refresh_days=7)

    client.media_page("saudiyatv")
    clock["now"] = NOW + timedelta(hours=2)
    client.media_page("saudiyatv")

    newer_than = [r["body"]["onlyPostsNewerThan"] for r in apify.requests if r["body"]["resultsType"] == "posts"]
    assert newer_than == [(NOW - timedelta(days=60)).date().isoformat(), (NOW + timedelta(hours=2) - timedelta(days=7)).date().isoformat()]


def test_apify_posts_flow_through_the_real_collector_into_the_database(apify, monkeypatch):
    monkeypatch.setattr(instagram_collector, "SBA_INSTAGRAM_ACCOUNTS", [{"entity_key": "saudiya", "username": "saudiyatv"}])
    apify.add_account("saudiyatv", account_id="IG1")
    apify.add_post("saudiyatv", "p1", timedelta(hours=5), likes=500, comments=20, kind="Video", product="clips", views=9000)
    apify.add_post("saudiyatv", "p2", timedelta(days=10), likes=-1, comments=3, kind="Sidecar", product="carousel_container")
    apify.add_post("saudiyatv", "old", timedelta(days=90))

    result = collector.run(
        "cli", instagram_client=_client(apify), engine=db.get_engine(),
        now=NOW, quota_budget=100, lookback_days=60, llm_classify_limit=0,
        platforms=("instagram",),
    )

    assert result["status"] == "success" and result["new_videos"] == 2
    with db.get_engine().connect() as conn:
        posts = {r.video_id: r for r in conn.execute(select(db.videos))}
    assert set(posts) == {"p1", "p2"}
    assert posts["p1"].content_type == "short" and posts["p1"].view_count is None
    assert posts["p2"].content_type == "carousel" and posts["p2"].like_count is None


def test_provider_switch_defaults_to_meta_and_selects_apify(monkeypatch):
    from backend import config
    from backend.agents import instagram_provider
    from backend.agents.instagram_client import InstagramClient

    monkeypatch.setattr(config, "META_ACCESS_TOKEN", "meta-token")
    monkeypatch.setattr(config, "INSTAGRAM_BUSINESS_ACCOUNT_ID", "123")
    monkeypatch.setattr(config, "INSTAGRAM_PROVIDER", "meta")
    assert isinstance(instagram_provider.make_client(), InstagramClient)

    monkeypatch.setattr(config, "INSTAGRAM_PROVIDER", "apify")
    monkeypatch.setattr(config, "APIFY_API_TOKEN", "apify-token")
    assert isinstance(instagram_provider.make_client(), ApifyInstagramClient)
