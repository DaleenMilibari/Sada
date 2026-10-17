from backend.agents import behavior_analysis_agent, diagnostic_recommendation_agent as diag


def _patterns():
    records = behavior_analysis_agent._load_records(behavior_analysis_agent.DATA_PATH)
    return behavior_analysis_agent.analyze(records)


def test_over_and_under_performers_get_different_specific_explanations():
    patterns = _patterns()

    underperformer = {
        "content_id": "diag-under",
        "title": "حديث ضعيف عن الدعم السكني",
        "platform": "x",
        "content_type": "video",
        "topic": "housing_support",
        "format": "short_clip",
        "publish_hour": 15,
        "day_of_week": "tue",
        "views": 3000,
        "likes": 15,
        "shares": 2,
        "watch_time_seconds": 8.0,
    }
    overperformer = {
        "content_id": "diag-over",
        "title": "حديث قوي عن الحدث الوطني",
        "platform": "x",
        "content_type": "video",
        "topic": "national_event",
        "format": "short_clip",
        "publish_hour": 20,
        "day_of_week": "tue",
        "views": 9000,
        "likes": 900,
        "shares": 400,
        "watch_time_seconds": 60.0,
    }

    under_ctx = diag.build_diagnosis_context(underperformer, patterns=patterns)
    over_ctx = diag.build_diagnosis_context(overperformer, patterns=patterns)

    assert under_ctx["low_confidence"] is False
    assert over_ctx["low_confidence"] is False

    # Acceptance criteria: different, specific, evidence-cited explanations.
    assert under_ctx["delta_pct"] < 0
    assert over_ctx["delta_pct"] > 0
    assert under_ctx["factors"] != over_ctx["factors"]

    for ctx in (under_ctx, over_ctx):
        for factor in ctx["factors"]:
            assert factor["evidence_source_title"]
            assert factor["evidence_url_or_ref"]
            assert factor["confidence"] > 0


def test_no_comparable_history_triggers_low_confidence_not_fabrication():
    item = {
        "content_id": "diag-nohist",
        "title": "موضوع بلا سابقة",
        "platform": "x",
        "content_type": "video",
        "topic": "brand_new_topic",
        "format": "short_clip",
        "publish_hour": 12,
        "day_of_week": "wed",
        "views": 1000,
        "likes": 10,
        "shares": 1,
        "watch_time_seconds": 3.0,
    }

    result = diag.diagnose(item, history=[], patterns=[])
    assert result["low_confidence"] is True
    assert result["contributing_factors"] == []


def test_awj_podcast_reach_context_grounds_in_real_episodes_not_synthetic():
    context = diag.build_awj_diagnosis_context("podcast_reach")
    assert context["low_confidence"] is False

    # Every factor must trace to a real awj_sada_real pattern, a real episode
    # title, or the one clearly-labeled synthetic context factor - nothing else.
    pattern_factors = [f for f in context["factors"] if f["evidence_source_title"] == "بيانات أوج | صدى الحقيقية (حلقات يوتيوب)"]
    episode_titles = {ep["episode_title"] for ep in diag._load_awj_raw()["episodes"]}
    for f in context["factors"]:
        is_pattern = f in pattern_factors
        is_episode = f["evidence_source_title"] in episode_titles
        is_demo = "تجريبية" in f["evidence_source_title"]
        assert is_pattern or is_episode or is_demo

    demo_factors = [f for f in context["factors"] if "تجريبية" in f["evidence_source_title"]]
    assert len(demo_factors) <= 1
    if demo_factors:
        assert "ليست جزءاً من بيانات أوج" in demo_factors[0]["reason"]
        assert demo_factors[0]["confidence"] <= 0.5

    # All 6 real episodes must be represented, including the ones with no
    # public YouTube figure (never silently dropped or treated as zero).
    episode_factors = [f for f in context["factors"] if f["reason"].startswith("حلقة")]
    assert len(episode_factors) == 6
    assert any("لا تتوفر بيانات" in f["reason"] for f in episode_factors)


def test_awj_x_relationship_context_covers_all_real_posts():
    context = diag.build_awj_diagnosis_context("x_relationship")
    assert context["low_confidence"] is False

    post_factors = [f for f in context["factors"] if f["reason"].startswith("منشور من")]
    assert len(post_factors) == 5  # all 5 real X posts, official + amplification


def test_awj_unknown_topic_raises():
    import pytest

    with pytest.raises(ValueError):
        diag.build_awj_diagnosis_context("not_a_real_topic")


# --- Task 4: diagnosis of real collected posts ---

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend import config, db
from backend.api import app

_NOW = db.utcnow().replace(microsecond=0, minute=0, second=0)


@pytest.fixture()
def real_engine(_isolated_database):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@r", "name_ar": "الرياضية"})
    return _isolated_database


def _add(engine, vid, *, views, hour_utc=17, days_ago=5, duration=60, title="عنوان", topic="sports", likes=10):
    published = (_NOW - timedelta(days=days_ago)).replace(hour=hour_utc)
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": vid, "platform": "youtube", "channel_id": "UC1", "title": title, "url": f"https://www.youtube.com/watch?v={vid}",
            "published_at": published, "duration_seconds": duration, "content_type": "short", "topic": topic, "topic_source": "rule",
            "view_count": views, "like_count": likes, "comment_count": 1, "first_seen_at": published, "stats_updated_at": _NOW,
        })


def _seed_peers(engine):
    # Strong peers publish around 20:00 Riyadh (17 UTC), ~60 s, with a question mark; weak ones at 03:00 Riyadh.
    for i in range(6):
        _add(engine, f"top{i}", views=50000 + i * 1000, hour_utc=17, duration=60, title=f"هل تعرف؟ {i}", days_ago=4 + i % 3)
    for i in range(3):
        _add(engine, f"weak{i}", views=3000 + i * 100, hour_utc=0, duration=200, title=f"خبر {i}", days_ago=4 + i)


def test_underperformer_gets_evidence_cited_specific_factors(real_engine):
    _seed_peers(real_engine)
    _add(real_engine, "under", views=2000, hour_utc=0, duration=200, title="خبر عادي", days_ago=5)
    _add(real_engine, "over", views=90000, hour_utc=17, duration=60, title="هل تعرف؟ سؤال", days_ago=5)

    under = diag.diagnose_video("under")
    over = diag.diagnose_video("over")
    assert not under["low_confidence"] and not over["low_confidence"]
    assert len(under["contributing_factors"]) >= 3  # level + hour + duration (+ title)
    peer_urls = {f"https://www.youtube.com/watch?v={p}" for p in [f"top{i}" for i in range(6)] + [f"weak{i}" for i in range(3)] + ["under", "over"]}
    for f in under["contributing_factors"] + over["contributing_factors"]:
        assert f["evidence_url_or_ref"] in peer_urls  # every factor cites a real comparable post
        assert f["supporting_metric"]
    assert under["diagnosis"] != over["diagnosis"]
    reasons_under = " ".join(f["reason"] for f in under["contributing_factors"])
    assert "أقل" in reasons_under and "ساعة النشر" in reasons_under and "مدة المقطع" in reasons_under


def test_no_comparables_is_low_confidence(real_engine):
    _add(real_engine, "alone", views=1000)
    result = diag.diagnose_video("alone")
    assert result["low_confidence"] is True
    assert result["contributing_factors"] == []


def test_comparables_outside_14_days_are_ignored(real_engine):
    for i in range(6):
        _add(real_engine, f"far{i}", views=10000, days_ago=40)
    _add(real_engine, "target", views=100, days_ago=5)
    assert diag.diagnose_video("target")["low_confidence"] is True


def test_unknown_video_returns_none(real_engine):
    assert diag.diagnose_video("nope") is None


def test_uses_llm_wording_when_available_and_falls_back_when_not(real_engine, monkeypatch):
    _seed_peers(real_engine)
    _add(real_engine, "under", views=2000, hour_utc=0, duration=200, title="خبر عادي")
    monkeypatch.setattr(diag.llm_client, "generate_json", lambda p: '{"diagnosis": "تشخيص من النموذج", "recommendations": ["توصية"]}')
    assert diag.diagnose_video("under")["diagnosis"].startswith("تشخيص من النموذج")

    def boom(_prompt):
        raise RuntimeError("no key")

    monkeypatch.setattr(diag.llm_client, "generate_json", boom)
    fallback = diag.diagnose_video("under")
    assert "أقل من المعتاد" in fallback["diagnosis"] and fallback["recommendations"]


def test_diagnose_video_endpoint(real_engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    monkeypatch.setattr(diag.llm_client, "generate_json", lambda p: (_ for _ in ()).throw(RuntimeError("no key")))
    _seed_peers(real_engine)
    _add(real_engine, "under", views=2000, hour_utc=0, duration=200)
    with TestClient(app) as client:
        res = client.post("/api/diagnose/video", json={"video_id": "under"})
        assert res.status_code == 200 and res.json()["contributing_factors"]
        assert client.post("/api/diagnose/video", json={"video_id": "missing"}).status_code == 404


@pytest.mark.parametrize(
    "reply",
    [
        '{"diagnosis": "تشخيص", "recommendations": "توصية واحدة"}',  # a string, not a list
        '{"diagnosis": "", "recommendations": ["توصية"]}',
        '["not", "an", "object"]',
        "not json",
    ],
)
def test_malformed_llm_reply_never_reaches_the_user(real_engine, monkeypatch, reply):
    _seed_peers(real_engine)
    _add(real_engine, "under", views=2000, hour_utc=0, duration=200, title="خبر عادي")
    monkeypatch.setattr(diag.llm_client, "generate_json", lambda p: reply)
    result = diag.diagnose_video("under")
    assert result["diagnosis"].strip()
    assert result["recommendations"] and all(len(r) > 1 for r in result["recommendations"])


def test_awj_diagnosis_falls_back_to_evidence_without_llm(monkeypatch):
    monkeypatch.setattr(diag.llm_client, "generate_json", lambda p: (_ for _ in ()).throw(RuntimeError("no key")))
    result = diag.diagnose_awj_topic("podcast_reach")
    assert result["low_confidence"] is False
    assert result["diagnosis"] and result["recommendations"] and result["contributing_factors"]
