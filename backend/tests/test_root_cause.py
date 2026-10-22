from datetime import timedelta

import pytest
from sqlalchemy import insert

from backend import db
from backend.agents import alerts_diagnosis_agent as diag
from backend.agents import root_cause

BASE = db.utcnow().replace(microsecond=0) - timedelta(days=30)


@pytest.fixture()
def engine(_isolated_database):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), {"channel_id": "UC1", "platform": "youtube", "entity_key": "sba", "handle": "@s", "name_ar": "الهيئة", "subscriber_count": 10})
    return _isolated_database


def add(engine, vid, at, views, content_type="video", topic="news"):
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": vid, "platform": "youtube", "channel_id": "UC1", "title": vid, "url": f"https://x/{vid}",
            "published_at": at, "content_type": content_type, "topic": topic, "topic_source": "rule",
            "view_count": views, "like_count": 10, "comment_count": 1, "first_seen_at": at, "stats_updated_at": at + timedelta(days=10),
        })


def isolated_history(engine, n=40, views=1000):
    for i in range(n):  # one post every ~13h, never within 10 minutes of another
        add(engine, f"h{i}", BASE + timedelta(hours=13 * i), views + (i % 7) * 30)


def test_burst_is_the_root_cause_with_a_decision_and_the_leader_as_evidence(engine):
    isolated_history(engine)
    t = BASE + timedelta(days=12, hours=5, minutes=17)
    for i, v in enumerate([1100, 300, 90, 60]):  # a series posted one minute apart
        add(engine, f"b{i}", t + timedelta(minutes=i), v)
    post = {"video_id": "b2", "channel_id": "UC1", "published_at": t + timedelta(minutes=2)}

    rc = root_cause.analyze(post)

    assert rc["direction"] == "under" and rc["drivers"][0]["kind"] == "burst"
    burst = rc["drivers"][0]
    assert "4 منشورات" in burst["reason"] and "ترتيبه 3" in burst["reason"]
    assert burst["evidence"]["video_id"] == "b0" and "ثريد" in burst["decision"]
    assert all(d["kind"] != "timing" for d in rc["drivers"])  # the burst isn't counted again as a "bad slot"


def test_no_driver_without_enough_history(engine):
    for i in range(5):
        add(engine, f"h{i}", BASE + timedelta(hours=13 * i), 1000)
    assert root_cause.analyze({"video_id": "h0", "channel_id": "UC1", "published_at": BASE}) is None


def test_format_driver_measured_on_the_accounts_own_posts(engine):
    for i in range(20):
        add(engine, f"v{i}", BASE + timedelta(hours=13 * i), 2000 + i, content_type="video")
        add(engine, f"i{i}", BASE + timedelta(hours=13 * i + 6), 500 + i, content_type="image")
    post = {"video_id": "i3", "channel_id": "UC1", "published_at": BASE + timedelta(hours=13 * 3 + 6)}

    fmt = next(d for d in root_cause.analyze(post)["drivers"] if d["kind"] == "format")

    assert fmt["effect"] < 0.3 and "فيديو" in fmt["decision"]


def test_diagnosis_leads_with_root_cause_and_decisions(engine, monkeypatch):
    isolated_history(engine)
    t = BASE + timedelta(days=12, hours=5, minutes=17)
    for i, v in enumerate([1100, 300, 90, 60]):
        add(engine, f"b{i}", t + timedelta(minutes=i), v)

    def no_llm(prompt):
        raise AssertionError("root-cause wording needs no LLM")

    monkeypatch.setattr(diag.llm_client, "generate_json", no_llm)
    result = diag.diagnose_video("b2")

    assert result["diagnosis"].startswith("تراجع المنشور") and "السبب الأرجح" in result["diagnosis"]
    assert "ثريد" in result["recommendations"][0]
    assert result["contributing_factors"][0]["evidence_url_or_ref"] == "https://x/b0"
