import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend import config, db, draft_suggest
from backend.agents import llm_client
from backend.api import app

NOW = db.utcnow().replace(microsecond=0)


@pytest.fixture()
def engine(_isolated_database):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), [
            {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@r", "name_ar": "الرياضية", "subscriber_count": 10},
            {"channel_id": "UC2", "platform": "youtube", "entity_key": "ekhbariya", "handle": "@e", "name_ar": "الإخبارية", "subscriber_count": 10},
        ])
    return _isolated_database


def add(engine, vid, channel, topic, views, title, age_days=2):
    published = NOW - timedelta(days=age_days)
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": vid, "platform": "youtube", "channel_id": channel, "title": title, "url": f"https://x/{vid}",
            "published_at": published, "content_type": "video", "topic": topic, "topic_source": "rule",
            "view_count": views, "like_count": 1, "comment_count": 1, "first_seen_at": published, "stats_updated_at": NOW,
        })


def test_grounded_in_the_chosen_accounts_best_recent_posts(engine, monkeypatch):
    for i, v in enumerate([100, 100, 900]):
        add(engine, f"r{i}", "UC1", "sports", v, f"هدف المنتخب {i}")
    add(engine, "e0", "UC2", "sports", 5000, "خبر رياضي من الإخبارية")
    prompts = []
    monkeypatch.setattr(llm_client, "generate_json", lambda p: prompts.append(p) or json.dumps({"text": "فكرة جديدة"}))

    out = draft_suggest.suggest("sports", "short", ["riyadiya"])

    assert out["source"] == "ai" and out["text"] == "فكرة جديدة"
    assert out["based_on"][0]["title"] == "هدف المنتخب 2"  # best vs its account's usual
    assert all(b["channel_name_ar"] == "الرياضية" for b in out["based_on"])
    assert "خبر رياضي من الإخبارية" not in prompts[0] and "مقطع قصير" in prompts[0]


def test_falls_back_without_llm_and_without_posts(engine, monkeypatch):
    add(engine, "r0", "UC1", "news", 100, "عنوان حقيقي")

    def no_key(prompt):
        raise llm_client.MissingApiKeyError("no key")

    monkeypatch.setattr(llm_client, "generate_json", no_key)
    out = draft_suggest.suggest("news", "video", [])
    assert out["source"] == "recent_post" and "عنوان حقيقي" in out["text"]

    empty = draft_suggest.suggest("economy", "video", [])
    assert empty["source"] == "generic" and empty["based_on"] == []


def test_endpoint(engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(llm_client, "generate_json", lambda p: json.dumps({"text": "x"}))
    add(engine, "r0", "UC1", "sports", 100, "t")
    with TestClient(app) as client:
        body = client.post("/api/draft/suggest", json={"topic": "sports", "content_type": "video", "channel_options": ["riyadiya"]}).json()
        assert body["text"] == "x" and body["based_on"][0]["url"] == "https://x/r0"
