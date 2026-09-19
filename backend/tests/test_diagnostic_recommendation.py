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
