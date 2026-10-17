from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend import config, db, playbook
from backend.api import app

NOW = db.utcnow().replace(microsecond=0, minute=0, second=0)


@pytest.fixture(autouse=True)
def _fresh_cache():
    playbook.clear_cache()
    yield
    playbook.clear_cache()


@pytest.fixture()
def engine(_isolated_database):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), [
            {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@r", "name_ar": "الرياضية", "subscriber_count": 1000},
            {"channel_id": "UC2", "platform": "youtube", "entity_key": "ekhbariya", "handle": "@e", "name_ar": "الإخبارية", "subscriber_count": 1000},
        ])
    return _isolated_database


def add(engine, vid, channel, topic, views, *, content_type="video", age_days=10, hour_utc=17):
    published = (NOW - timedelta(days=age_days)).replace(hour=hour_utc)
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": vid, "platform": "youtube", "channel_id": channel, "title": vid, "url": f"https://x/{vid}",
            "published_at": published, "content_type": content_type, "topic": topic, "topic_source": "rule",
            "view_count": views, "like_count": 1, "comment_count": 1, "first_seen_at": published, "stats_updated_at": NOW,
        })


def test_recommends_the_account_where_the_topic_reaches_most(engine):
    for i in range(20):  # riyadiya: sports posts ~3x its own news posts
        add(engine, f"rs{i}", "UC1", "sports", 3000 + i, age_days=5 + i % 20)
        add(engine, f"rn{i}", "UC1", "news", 1000 + i, age_days=5 + i % 20)
    for i in range(20):  # ekhbariya: sports posts weak
        add(engine, f"es{i}", "UC2", "sports", 500 + i, age_days=5 + i % 20)
        add(engine, f"en{i}", "UC2", "news", 2000 + i, age_days=5 + i % 20)

    sports = next(t for t in playbook.build(60)["topics"] if t["topic"] == "sports")

    best = sports["best"]
    assert best["entity_key"] == "riyadiya" and best["confidence"] == "high"
    assert best["content_type"]["content_type"] == "video" and best["best_time"] is not None
    assert best["reasons"] and "20 منشوراً" in best["reasons"][0]
    assert [o["entity_key"] for o in sports["options"]] == ["riyadiya", "ekhbariya"]


def test_small_samples_are_shrunk_toward_usual(engine):
    for i in range(40):
        add(engine, f"a{i}", "UC1", "news", 1000 + i, age_days=5 + i % 30)
    for i in range(5):  # 5 lucky posts at 3x: shrunk well below 3x
        add(engine, f"b{i}", "UC1", "economy", 3000, age_days=6 + i)

    economy = next(t for t in playbook.build(60)["topics"] if t["topic"] == "economy")["best"]

    assert economy["topic_multiplier"] > 2.5
    assert economy["expected_reach"] < 0.6 * 3000  # 3x ** (5/15) ~ 1.44x the typical ~1000
    assert economy["confidence"] == "low"


def test_topic_without_enough_posts_has_no_recommendation(engine):
    for i in range(4):
        add(engine, f"d{i}", "UC1", "documentary", 1000)
    doc = next(t for t in playbook.build(60)["topics"] if t["topic"] == "documentary")
    assert doc["best"] is None and doc["options"] == []


def test_endpoint(engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    for i in range(6):
        add(engine, f"s{i}", "UC1", "sports", 1000 + i)
    with TestClient(app) as client:
        body = client.get("/api/playbook?days=60").json()
        assert {t["topic"] for t in body["topics"]} >= {"sports", "news"}
        assert client.get("/api/playbook?days=3").status_code == 422
