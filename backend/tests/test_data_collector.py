from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from backend import db
from backend.agents import data_collector_agent as collector
from backend.agents import youtube_client
from backend.agents.youtube_client import YouTubeClient, parse_duration
from backend.sba_channels import SBA_CHANNELS
from backend.topics import classify_by_rules

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


class FakeYouTube:
    """In-memory YouTube API: one uploads playlist per SBA channel."""

    def __init__(self):
        self.uploads: dict[str, list[dict]] = {}  # playlist_id -> newest-first [{id, published, views, duration}]
        self.calls: list[str] = []
        self.quota_exhausted = False
        for i, spec in enumerate(SBA_CHANNELS):
            self.uploads[f"UU{i}"] = []

    def channel_id(self, handle: str) -> int:
        return next(i for i, c in enumerate(SBA_CHANNELS) if c["handle"].lstrip("@") == handle)

    def add_video(self, channel_index: int, video_id: str, age: timedelta, views: int = 100, duration: str = "PT5M", title: str = "عنوان"):
        self.uploads[f"UU{channel_index}"].insert(
            0, {"id": video_id, "published": NOW - age, "views": views, "duration": duration, "title": title, "ch": channel_index}
        )
        self.uploads[f"UU{channel_index}"].sort(key=lambda v: v["published"], reverse=True)

    def handler(self, request: httpx.Request) -> httpx.Response:
        resource = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(resource)
        if self.quota_exhausted:
            return httpx.Response(403, json={"error": {"errors": [{"reason": "quotaExceeded"}]}})
        p = request.url.params
        if resource == "channels":
            i = self.channel_id(p["forHandle"])
            return httpx.Response(200, json={"items": [{
                "id": f"UC{i}",
                "snippet": {"title": SBA_CHANNELS[i]["name_ar"]},
                "statistics": {"subscriberCount": "1000", "videoCount": "10", "viewCount": "5000"},
                "contentDetails": {"relatedPlaylists": {"uploads": f"UU{i}"}},
            }]})
        if resource == "playlistItems":
            items = self.uploads[p["playlistId"]]
            start = int(p.get("pageToken", 0))
            page = items[start : start + 50]
            body = {"items": [{"contentDetails": {"videoId": v["id"], "videoPublishedAt": v["published"].isoformat().replace("+00:00", "Z")}} for v in page]}
            if start + 50 < len(items):
                body["nextPageToken"] = str(start + 50)
            return httpx.Response(200, json=body)
        if resource == "videos":
            ids = p["id"].split(",")
            all_videos = {v["id"]: v for vs in self.uploads.values() for v in vs}
            return httpx.Response(200, json={"items": [{
                "id": vid,
                "snippet": {"channelId": f"UC{all_videos[vid]['ch']}", "title": all_videos[vid]["title"],
                            "publishedAt": all_videos[vid]["published"].isoformat().replace("+00:00", "Z")},
                "statistics": {"viewCount": str(all_videos[vid]["views"]), "likeCount": "5"},
                "contentDetails": {"duration": all_videos[vid]["duration"]},
            } for vid in ids if vid in all_videos]})
        return httpx.Response(404)


@pytest.fixture()
def engine(_isolated_database):
    return _isolated_database


@pytest.fixture()
def fake():
    return FakeYouTube()


def _client(fake):
    return YouTubeClient("test-key", http=httpx.Client(transport=httpx.MockTransport(fake.handler)), backoff_seconds=0)


def _run(engine, fake, now=NOW, **kw):
    kw.setdefault("llm_classify_limit", 0)
    kw.setdefault("quota_budget", 1000)
    kw.setdefault("lookback_days", 60)
    return collector.run("cli", client=_client(fake), engine=engine, now=now, **kw)


def test_first_run_collects_window_and_snapshots(engine, fake):
    fake.add_video(1, "new1", timedelta(hours=3), views=500)
    fake.add_video(1, "old1", timedelta(days=20))
    fake.add_video(1, "too_old", timedelta(days=90))

    result = _run(engine, fake)

    assert result["status"] == "success"
    assert result["new_videos"] == 2
    with engine.connect() as conn:
        ids = set(conn.execute(select(db.videos.c.video_id)).scalars())
        snaps = conn.execute(select(db.video_snapshots)).all()
        channels = conn.execute(select(db.channels)).all()
    assert ids == {"new1", "old1"}  # outside the lookback window is never stored
    assert len(snaps) == 2
    assert len(channels) == len(SBA_CHANNELS)


def test_second_run_is_incremental_and_respects_refresh_policy(engine, fake):
    fake.add_video(2, "young", timedelta(hours=5))
    fake.add_video(2, "mature", timedelta(days=20))
    _run(engine, fake)

    fake.add_video(2, "brand_new", timedelta(minutes=30))
    result = _run(engine, fake, now=NOW + timedelta(minutes=30))

    # brand_new is discovered; young (<2d, 25 min staleness) is refreshed; mature (24h staleness) is not.
    assert result["new_videos"] == 1
    assert result["updated_videos"] == 1
    with engine.connect() as conn:
        snaps = dict(
            conn.execute(
                select(db.video_snapshots.c.video_id, db.video_snapshots.c.id).where(db.video_snapshots.c.video_id == "mature")
            ).all()
        )
    assert len(snaps) == 1


def test_quota_exhaustion_ends_partial_and_keeps_data(engine, fake):
    fake.add_video(0, "v1", timedelta(days=1))
    _run(engine, fake)
    fake.quota_exhausted = True

    result = _run(engine, fake, now=NOW + timedelta(days=2))

    assert result["status"] == "partial"
    assert "quota" in result["error"].lower()
    with engine.connect() as conn:
        assert conn.execute(select(db.videos.c.video_id)).scalars().all() == ["v1"]
        last = conn.execute(select(db.collector_runs).order_by(db.collector_runs.c.id.desc())).first()
    assert last.status == "partial"


def test_budget_limits_api_calls(engine, fake):
    for n in range(300):
        fake.add_video(3, f"v{n}", timedelta(hours=n + 1))
    result = _run(engine, fake, quota_budget=30)

    assert result["quota_units"] <= 30
    assert result["status"] == "partial"  # discovery stopped at its budget share; next run resumes
    assert 0 < result["new_videos"] < 300


def test_concurrent_run_is_skipped(engine, fake):
    with engine.begin() as conn:
        conn.execute(db.collector_runs.insert().values(trigger="scheduled", status="running", started_at=NOW - timedelta(minutes=5)))
    assert _run(engine, fake)["status"] == "skipped"


def test_content_type_and_topic_classification():
    item = lambda title, dur, **extra: {"snippet": {"title": title, **extra}, "contentDetails": {"duration": dur}}
    assert collector.classify_content_type(item("x", "PT45S"), 45) == "short"
    assert collector.classify_content_type(item("clip", "PT2M"), 120) == "video"
    assert collector.classify_content_type(item("clip #Shorts", "PT2M"), 120) == "short"
    assert collector.classify_content_type({**item("x", "P0D"), "liveStreamingDetails": {}}, 0) == "live"
    assert parse_duration("PT1H2M3S") == 3723 and parse_duration("P1DT1S") == 86401

    assert classify_by_rules("ملخص مباراة الهلال والنصر", "news") == "sports"
    assert classify_by_rules("احتفالات اليوم الوطني 96", "other") == "national_event"
    assert classify_by_rules("عنوان عام", "religious") == "religious"


def test_transient_errors_are_retried(monkeypatch):
    attempts = {"n": 0}

    def flaky(request):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"items": []})

    client = YouTubeClient("k", http=httpx.Client(transport=httpx.MockTransport(flaky)), backoff_seconds=0)
    assert client.channel_by_handle("@x") is None
    assert attempts["n"] == 3

    with pytest.raises(youtube_client.YouTubeApiError):
        YouTubeClient("k", http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(400))), backoff_seconds=0).videos(["a"])


def test_collected_data_served_by_api(fake, monkeypatch):
    from fastapi.testclient import TestClient

    from backend import config
    from backend.api import app

    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(db, "utcnow", lambda: NOW)  # the fake's publish times are relative to NOW, not the real clock
    fake.add_video(4, "match1", timedelta(hours=2), views=9000, title="ملخص مباراة الهلال")
    fake.add_video(4, "clip1", timedelta(hours=1), views=10, duration="PT40S")
    collector.run("cli", client=_client(fake), engine=db.get_engine(), now=db.utcnow(), quota_budget=100, llm_classify_limit=0)

    with TestClient(app) as client:
        channels = client.get("/api/channels").json()
        assert len(channels) == len(SBA_CHANNELS)
        assert next(c for c in channels if c["entity_key"] == "riyadiya")["tracked_videos"] == 2

        page = client.get("/api/videos", params={"channel": "riyadiya", "sort": "views"}).json()
        assert page["total"] == 2
        top = page["items"][0]
        assert top["video_id"] == "match1" and top["topic"] == "sports" and top["content_type"] == "video"
        assert top["url"].endswith("match1")

        assert client.get("/api/videos", params={"content_type": "short"}).json()["total"] == 1
        detail = client.get("/api/videos/match1").json()
        assert len(detail["snapshots"]) == 1
        assert client.get("/api/videos/nope").status_code == 404

        status = client.get("/api/collector/status").json()
        assert status["total_videos"] == 2 and status["runs"][0]["status"] == "success"


def test_export_import_roundtrip(engine, fake, tmp_path):
    from backend import db_tools

    fake.add_video(5, "q1", timedelta(hours=4))
    _run(engine, fake)
    path = tmp_path / "seed.json.gz"
    exported = db_tools.export(path)
    assert exported["videos"] == 1 and exported["video_snapshots"] == 1

    db.metadata.drop_all(engine)
    db.init_db(engine)
    imported = db_tools.import_(path)
    assert imported["videos"] == 1
    assert db_tools.import_(path)["video_snapshots"] == 0  # idempotent
    with engine.connect() as conn:
        assert conn.execute(select(db.videos.c.video_id)).scalars().all() == ["q1"]


def test_seed_carries_audience_labels_and_follower_history(engine, fake, tmp_path):
    from sqlalchemy import func, insert

    from backend import db_tools

    fake.add_video(5, "q1", timedelta(hours=4))
    _run(engine, fake)
    now = db.utcnow()
    with engine.begin() as conn:
        conn.execute(insert(db.audience_comments), {"comment_id": "c1", "platform": "youtube", "video_id": "q1", "text": "رائع",
                                                    "published_at": now, "collected_at": now, "sentiment": "positive", "intent": "praise"})
        conn.execute(insert(db.audience_labels), {"comment_id": "c1", "sentiment": "positive", "intent": "praise", "labeled_at": now})
    path = tmp_path / "seed.json.gz"
    exported = db_tools.export(path)
    assert exported["audience_comments"] == 1 and exported["audience_labels"] == 1 and exported["follower_snapshots"] >= 1

    db.metadata.drop_all(engine)
    db.init_db(engine)
    db_tools.import_(path)
    again = db_tools.import_(path)
    assert again["follower_snapshots"] == 0 and again["video_snapshots"] == 0  # idempotent
    with engine.connect() as conn:
        assert conn.execute(select(db.audience_comments.c.sentiment)).scalar() == "positive"
        assert conn.execute(select(func.count()).select_from(db.audience_labels)).scalar() == 1


def test_analysis_records_normalize_by_channel_and_age(fake, monkeypatch):
    from backend import repository

    monkeypatch.setattr(db, "utcnow", lambda: NOW)  # the fake's publish times are relative to NOW, not the real clock
    now = db.utcnow()
    fake.add_video(6, "a", timedelta(days=5), views=100)
    fake.add_video(6, "b", timedelta(days=6), views=300)
    fake.add_video(6, "c", timedelta(days=7), views=200)
    fake.add_video(6, "too_young", timedelta(hours=10), views=5)
    collector.run("cli", client=_client(fake), engine=db.get_engine(), now=now, quota_budget=100, llm_classify_limit=0)

    records = {r["video_id"]: r for r in repository.analysis_records(days=60, min_age_days=3)}
    assert set(records) == {"a", "b", "c"}
    assert records["c"]["views_index"] == 1.0  # median of the channel
    assert records["b"]["views_index"] == 1.5
    assert records["a"]["engagement_rate"] == 5 / 100
    assert 0 <= records["a"]["publish_hour"] <= 23 and records["a"]["day_of_week"] in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
