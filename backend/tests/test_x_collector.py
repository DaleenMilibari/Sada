import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from backend import config, db, repository
from backend.agents import data_collector_agent as collector
from backend.agents import x_collector
from backend.agents.x_client import XApiError, XClient

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


class FakeX:
    """In-memory X API v2: user lookup + user timeline (newest first)."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.posts: dict[str, list[dict]] = {}
        self.requests: list[httpx.Request] = []
        self.error_status: int | None = None
        self.credit_pages: int | None = None  # timeline pages served before credits run out

    def add_user(self, username, user_id, followers=1000):
        self.users[username.lower()] = {
            "id": user_id, "username": username, "name": username,
            "public_metrics": {"followers_count": followers, "tweet_count": 0},
        }
        self.posts[user_id] = []

    def add_post(self, user_id, post_id, age, impressions=1000, likes=10, replies=2, media=()):
        username = next(u["username"] for u in self.users.values() if u["id"] == user_id)
        urls = [{"expanded_url": f"https://x.com/{username}/status/{post_id}/{kind}/{i + 1}"} for i, kind in enumerate(media)]
        post = {
            "id": post_id, "text": "منشور", "created_at": (NOW - age).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "public_metrics": {"impression_count": impressions, "like_count": likes, "reply_count": replies,
                               "retweet_count": 0, "quote_count": 0},
        }
        if urls:
            post["entities"] = {"urls": urls}
        self.posts[user_id].append(post)
        self.posts[user_id].sort(key=lambda p: int(p["id"]), reverse=True)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["Authorization"] == "Bearer token"
        if self.error_status:
            return httpx.Response(self.error_status, json={"title": "Payment Required", "detail": "no credits"})
        params = request.url.params
        if request.url.path == "/2/users/by":
            found = [self.users[u.lower()] for u in params["usernames"].split(",") if u.lower() in self.users]
            return httpx.Response(200, json={"data": found} if found else {})
        if request.url.path == "/2/tweets/search/recent":  # audience step: no replies in these fixtures
            return httpx.Response(200, json={"meta": {"result_count": 0}})
        user_id = re.fullmatch(r"/2/users/(\d+)/tweets", request.url.path).group(1)
        assert params["exclude"] == "retweets,replies"
        posts = self.posts[user_id]
        if self.credit_pages is not None:
            if self.credit_pages == 0:
                return httpx.Response(402, json={"title": "Payment Required", "detail": "credits depleted"})
            self.credit_pages -= 1
        if "since_id" in params:
            posts = [p for p in posts if int(p["id"]) > int(params["since_id"])]
        if "until_id" in params:
            posts = [p for p in posts if int(p["id"]) < int(params["until_id"])]
        if "start_time" in params:
            posts = [p for p in posts if p["created_at"] >= params["start_time"].replace("Z", ".000Z")]
        start = int(params.get("pagination_token", 0))
        size = int(params["max_results"])
        page = posts[start : start + size]
        body = {"meta": {"result_count": len(page)}}
        if page:
            body["data"] = page
        if start + size < len(posts):
            body["meta"]["next_token"] = str(start + size)
        return httpx.Response(200, json=body)

    def timeline_calls(self):
        return [r for r in self.requests if r.url.path.endswith("/tweets")]


@pytest.fixture()
def fake(monkeypatch):
    monkeypatch.setattr(x_collector, "SBA_X_ACCOUNTS", [
        {"entity_key": "sba", "username": "SBAgovSA"},
        {"entity_key": "ekhbariya", "username": "ekhbariya"},
    ])
    monkeypatch.setattr(config, "X_TOTAL_POST_BUDGET", 6000)
    monkeypatch.setattr(config, "X_MAX_POSTS_PER_RUN", 4000)
    monkeypatch.setattr(config, "X_MAX_POSTS_PER_ACCOUNT", 600)
    return FakeX()


def _client(fake):
    return XClient("token", http=httpx.Client(transport=httpx.MockTransport(fake.handler)), backoff_seconds=0)


def _run(fake, now=NOW):
    return collector.run(
        "cli", x_client=_client(fake), engine=db.get_engine(), now=now,
        lookback_days=60, llm_classify_limit=0, platforms=("x",),
    )


def _both_accounts(fake):
    fake.add_user("SBAgovSA", "100", followers=500_000)
    fake.add_user("ekhbariya", "200")


def test_backfill_stores_posts_in_shared_tables(fake):
    _both_accounts(fake)
    fake.add_post("100", "11", timedelta(hours=5), impressions=9000, media=("video",))
    fake.add_post("100", "12", timedelta(days=3), media=("photo", "photo"))
    fake.add_post("100", "13", timedelta(days=4), media=("photo",))
    fake.add_post("100", "14", timedelta(days=5))
    fake.add_post("100", "10", timedelta(days=90))  # older than the lookback

    result = _run(fake)

    assert result["status"] == "success"
    assert result["new_videos"] == 4 and result["x_posts_read"] == 4
    with db.get_engine().connect() as conn:
        posts = {r.video_id: r for r in conn.execute(select(db.videos))}
        channel = conn.execute(select(db.channels).where(db.channels.c.channel_id == "100")).one()
    assert set(posts) == {"11", "12", "13", "14"}
    assert posts["11"].platform == "x" and posts["11"].content_type == "video"
    assert posts["11"].view_count == 9000 and posts["11"].comment_count == 2  # impressions, replies
    assert posts["11"].url == "https://x.com/SBAgovSA/status/11"
    assert [posts[i].content_type for i in ("12", "13", "14")] == ["carousel", "image", "text"]
    assert channel.platform == "x" and channel.entity_key == "sba" and channel.subscriber_count == 500_000


def test_later_runs_read_only_new_posts_and_skip_user_lookup(fake):
    _both_accounts(fake)
    for n in range(30):
        fake.add_post("100", str(100 + n), timedelta(hours=30 - n))  # higher id = newer, as on X
    _run(fake)

    fake.requests.clear()
    fake.add_post("100", "500", timedelta(minutes=10))
    result = _run(fake, now=NOW + timedelta(hours=1))

    assert result["x_posts_read"] == 1 and result["new_videos"] == 1 and result["updated_videos"] == 0
    assert not any(r.url.path == "/2/users/by" for r in fake.requests)  # ids reused from the database
    assert fake.timeline_calls()[0].url.params["since_id"] == "129"


def test_per_account_cap_limits_backfill(fake, monkeypatch):
    monkeypatch.setattr(config, "X_MAX_POSTS_PER_ACCOUNT", 150)
    _both_accounts(fake)
    for n in range(400):
        fake.add_post("100", str(1000 + n), timedelta(minutes=10 * n + 1))

    result = _run(fake)

    assert result["x_posts_read"] == 150
    sizes = [int(r.url.params["max_results"]) for r in fake.timeline_calls() if "100" in r.url.path]
    assert sizes == [100, 50]  # never asks for more than the cap


def test_later_runs_keep_going_back_until_the_cutoff(fake, monkeypatch):
    monkeypatch.setattr(config, "X_MAX_POSTS_PER_ACCOUNT", 100)
    _both_accounts(fake)
    for n in range(250):  # one post every 2h, ~21 days, higher id = newer
        fake.add_post("100", str(1000 + n), timedelta(hours=2 * (250 - n)))
    _run(fake)  # newest 100

    fake.add_post("100", "5000", timedelta(minutes=5))
    second = _run(fake, now=NOW + timedelta(hours=1))
    third = _run(fake, now=NOW + timedelta(hours=2))

    assert second["x_posts_read"] == 100  # 1 new + 99 older
    assert third["x_posts_read"] == 51  # the rest; window now complete
    with db.get_engine().connect() as conn:
        assert len(conn.execute(select(db.videos.c.video_id)).scalars().all()) == 251
    fake.requests.clear()
    assert _run(fake, now=NOW + timedelta(hours=3))["x_posts_read"] == 0


def test_posts_already_billed_are_kept_when_credit_runs_out(fake, monkeypatch):
    _both_accounts(fake)
    for n in range(250):
        fake.add_post("100", str(1000 + n), timedelta(hours=2 * (250 - n)))
    fake.credit_pages = 2

    result = _run(fake)

    assert result["status"] == "failed" and "credit" in result["error"]
    assert result["new_videos"] == 200 and result["x_posts_read"] == 200
    with db.get_engine().connect() as conn:
        assert len(conn.execute(select(db.videos.c.video_id)).scalars().all()) == 200


def test_total_budget_is_a_hard_stop_across_runs(fake, monkeypatch):
    monkeypatch.setattr(config, "X_TOTAL_POST_BUDGET", 40)
    _both_accounts(fake)
    for n in range(100):
        fake.add_post("100", str(1000 + n), timedelta(minutes=10 * n + 1))

    first = _run(fake)
    assert first["x_posts_read"] == 40 and first["status"] == "partial"

    fake.requests.clear()
    fake.add_post("100", "9999", timedelta(minutes=1))
    second = _run(fake, now=NOW + timedelta(hours=1))
    assert second["x_posts_read"] == 0 and fake.timeline_calls() == []  # replies have their own budget
    assert "budget" in second["error"]


def test_unknown_account_is_reported_but_others_collected(fake):
    fake.add_user("SBAgovSA", "100")
    fake.add_post("100", "11", timedelta(hours=2))

    result = _run(fake)

    assert result["status"] == "partial"
    assert "ekhbariya" in result["error"] and result["new_videos"] == 1


def test_no_credits_fails_x_step_cleanly(fake):
    fake.error_status = 402

    result = _run(fake)

    assert result["status"] == "failed"
    assert "credit" in result["error"]


def test_performance_index_uses_impressions(fake):
    _both_accounts(fake)
    fake.add_post("100", "1", timedelta(days=5), impressions=1000)
    fake.add_post("100", "2", timedelta(days=6), impressions=2000)
    fake.add_post("100", "3", timedelta(days=7), impressions=3000)
    _run(fake, now=db.utcnow())

    records = {r["video_id"]: r for r in repository.analysis_records(platform="x")}
    assert records["2"]["performance_index"] == 1.0 and records["3"]["performance_index"] == 1.5
    assert records["1"]["primary_metric"] == "impressions"


def test_bad_ids_and_usernames_rejected_before_any_call(fake):
    client = _client(fake)
    with pytest.raises(XApiError):
        client.users_by_username(["bad name"])
    with pytest.raises(XApiError):
        client.user_posts("100/../x", 10)
    assert fake.requests == []


# --- X through the analysis layer (dashboard summary, diagnosis) ---


def _collect_at(fake, collected_at, posts):
    """Collect `posts` [(id, age at collection, impressions)] for @SBAgovSA at `collected_at`."""
    _both_accounts(fake)
    for post_id, age, impressions in posts:
        fake.add_post("100", post_id, age + (NOW - collected_at), impressions=impressions)
    collector.run("cli", x_client=_client(fake), engine=db.get_engine(), now=collected_at,
                  lookback_days=60, llm_classify_limit=0, platforms=("x",))


def test_x_in_dashboard_summary_uses_impressions_but_never_mixes_them_with_youtube_views(fake):
    from backend import analytics, schemas

    _collect_at(fake, db.utcnow(), [("1", timedelta(days=5), 1000), ("2", timedelta(days=6), 3000)])

    x_only = analytics.build_summary(days=30, platform="x")
    everything = analytics.build_summary(days=30)

    schemas.AnalyticsSummary.model_validate(x_only)  # platform "x" passes the response model
    schemas.AnalyticsSummary.model_validate(everything)
    assert x_only["totals"]["views"] == 4000 and x_only["by_channel"][0]["views"] == 4000
    assert x_only["totals"]["engagement_rate"] is not None
    assert everything["totals"]["views"] == 0  # "all" totals stay YouTube views only


def test_x_posts_measured_too_young_stay_out_of_analysis(fake):
    collected = db.utcnow() - timedelta(days=5)
    # Both published >3 days ago today, but 901 was only 1h old when its counts were frozen.
    _collect_at(fake, collected, [("901", timedelta(hours=1), 50), ("902", timedelta(days=4), 5000)])

    ids = {r["video_id"] for r in repository.analysis_records(platform="x")}
    assert ids == {"902"}  # 901 was 1h old when measured


def test_x_diagnosis_refuses_counts_frozen_too_young(fake):
    from backend.agents import diagnostic_recommendation_agent as diag

    _collect_at(fake, db.utcnow(), [("903", timedelta(hours=2), 50)])
    post = repository.get_video("903")

    assert diag.build_video_diagnosis_context(post)["low_confidence"] is True
