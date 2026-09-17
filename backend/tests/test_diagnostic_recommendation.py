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
