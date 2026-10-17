import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend import analytics, config, db
from backend.api import app

NOW = db.utcnow().replace(microsecond=0, minute=0, second=0)


@pytest.fixture(autouse=True)
def _fresh_cache():
    analytics.clear_cache()
    yield
    analytics.clear_cache()


@pytest.fixture()
def engine(_isolated_database):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), [
            {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@r", "name_ar": "الرياضية", "subscriber_count": 1000},
            {"channel_id": "IG1", "platform": "instagram", "entity_key": "saudiya", "handle": "s", "name_ar": "السعودية", "subscriber_count": 500},
        ])
    return _isolated_database


def add(engine, vid, *, platform="youtube", channel="UC1", age_days=10, views=1000, likes=10, comments=1, topic="sports", content_type="video", hour_utc=10):
    published = (NOW - timedelta(days=age_days)).replace(hour=hour_utc)
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": vid, "platform": platform, "channel_id": channel, "title": vid, "url": f"https://x/{vid}",
            "published_at": published, "content_type": content_type, "topic": topic, "topic_source": "rule",
            "view_count": views, "like_count": likes, "comment_count": comments, "first_seen_at": published, "stats_updated_at": NOW,
        })


def test_summary_totals_and_null_handling(engine):
    for i in range(4):
        add(engine, f"y{i}", views=1000 * (i + 1), likes=10, comments=None)  # hidden comments: never counted as 0, never breaks sums
    add(engine, "i1", platform="instagram", channel="IG1", views=None, likes=40, comments=2, content_type="image")
    add(engine, "young", age_days=1)  # too young: excluded

    s = analytics.build_summary(30)
    assert s["totals"]["posts"] == 5
    assert s["totals"]["views"] == 10000  # YouTube only
    assert s["totals"]["likes"] == 80
    assert s["totals"]["comments"] == 2
    assert s["totals"]["engagement_rate"] == pytest.approx(40 / 10000, rel=1e-3)
    plat = {p["platform"]: p for p in s["by_platform"]}
    assert plat["instagram"]["followers"] == 500 and plat["instagram"]["posts"] == 1
    ig = next(c for c in s["by_channel"] if c["platform"] == "instagram")
    assert ig["views"] is None and ig["engagement_rate"] is None
    assert {t["label_ar"] for t in s["by_topic"]} == {"رياضة"}


def test_platform_filter_and_best_times_min_sample(engine):
    for i in range(analytics.MIN_TIMES_N):
        add(engine, f"a{i}", age_days=10 + i * 7, hour_utc=10, views=1000 + i)  # same weekday + hour: one cell at the minimum size
    add(engine, "lonely", age_days=12, hour_utc=3)  # a cell of 1 post must not be surfaced
    s = analytics.build_summary(60, "youtube")
    assert all(t["platform"] == "youtube" for t in s["best_times"])
    assert all(t["n"] >= analytics.MIN_TIMES_N for t in s["best_times"])
    assert s["best_times"] and s["best_times"][0]["hour"] == 13  # Riyadh = UTC+3
    assert analytics.build_summary(60, "instagram")["totals"]["posts"] == 0


def test_data_as_of_uses_last_successful_run(engine):
    with engine.begin() as conn:
        conn.execute(insert(db.collector_runs), [
            {"trigger": "scheduled", "status": "success", "started_at": NOW - timedelta(hours=3), "finished_at": NOW - timedelta(hours=2)},
            {"trigger": "scheduled", "status": "failed", "started_at": NOW - timedelta(hours=1), "finished_at": NOW - timedelta(minutes=50)},
        ])
    assert analytics.data_as_of() == NOW - timedelta(hours=2)


def test_data_as_of_none_without_runs(engine):
    assert analytics.build_summary(30)["data_as_of"] is None


def test_summary_is_cached(engine, monkeypatch):
    calls = []
    real = analytics.build_summary
    monkeypatch.setattr(analytics, "build_summary", lambda *a: calls.append(a) or real(*a))
    analytics.summary(30)
    analytics.summary(30)
    analytics.summary(7)
    assert len(calls) == 2
    analytics.clear_cache()
    analytics.summary(30)
    assert len(calls) == 3


def test_endpoint_contract_and_latency(engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    for i in range(5):
        add(engine, f"e{i}", views=500 * (i + 1))
    with TestClient(app) as client:
        res = client.get("/api/analytics/summary?days=30")
        assert res.status_code == 200
        body = res.json()
        for key in ("generated_at", "data_as_of", "totals", "by_platform", "by_channel", "by_content_type", "by_topic", "best_times"):
            assert key in body
        start = time.perf_counter()
        client.get("/api/analytics/summary?days=30")
        assert (time.perf_counter() - start) < 0.1  # cached path
        assert client.get("/api/analytics/summary?days=0").status_code == 422


def test_best_times_use_all_collected_history_not_the_kpi_window(engine, monkeypatch):
    monkeypatch.setattr(config, "COLLECTOR_LOOKBACK_DAYS", 180)
    # One post per week at the same weekday/hour for 20 weeks: only ~4 fall inside a 30-day window.
    for week in range(20):
        add(engine, f"w{week}", age_days=7 * week + 7, hour_utc=17)

    s = analytics.build_summary(30, "youtube")
    assert s["totals"]["posts"] < 5  # the KPIs follow the selected window ...
    cell = [c for c in s["best_times"] if c["platform"] == "youtube"]
    assert len(cell) == 1 and cell[0]["n"] == 20  # ... the best times use everything collected
    assert s["best_times_coverage"] == [{"platform": "youtube", "days": 133, "posts": 20}]
