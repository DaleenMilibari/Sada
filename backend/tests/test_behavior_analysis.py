from backend.agents import behavior_analysis_agent as agent


def test_analyze_finds_the_designed_patterns(tmp_path):
    records = agent._load_records(agent.DATA_PATH)
    patterns = agent.analyze(records)

    # Acceptance criteria: 3-5+ distinct, evidence-backed patterns.
    assert 3 <= len(patterns) <= 10

    for p in patterns:
        assert p["confidence"] > 0
        assert "n=" in p["supporting_metric"] and "lift=" in p["supporting_metric"]
        assert p["affected_content_types"]

    dimensions = {p["dimension"] for p in patterns}
    assert "content_type" in dimensions

    # The seed data has an intentional dip in this bucket and spike in this
    # topic/platform combo - both should be recovered.
    slice_keys = {p["slice_key"] for p in patterns}
    assert "weekday_afternoon_14_17" in slice_keys
    assert "national_event|x" in slice_keys

    # "science" is deliberately sparse in the seed data - must never appear.
    for p in patterns:
        assert "science" not in p["slice_key"]


def test_rerun_upserts_instead_of_duplicating(tmp_path):
    store_path = tmp_path / "pattern_store.json"
    records = agent._load_records(agent.DATA_PATH)
    patterns = agent.analyze(records)

    first = agent.upsert_store(patterns, store_path)
    second = agent.upsert_store(patterns, store_path)

    assert len(first) == len(second)
    ids_first = {p["pattern_id"] for p in first}
    ids_second = {p["pattern_id"] for p in second}
    assert ids_first == ids_second


def test_insufficient_data_slice_is_skipped_not_guessed():
    # A tiny synthetic dataset with one "rare" bucket should never produce
    # a pattern for that bucket - the agent must skip it, not fabricate one.
    records = []
    for i in range(30):
        records.append(
            {
                "platform": "x",
                "content_type": "video",
                "topic": "general",
                "format": "short_clip",
                "publish_hour": 10,
                "day_of_week": "mon",
                "views": 5000,
                "likes": 100,
                "shares": 20,
                "watch_time_seconds": 30.0,
                "drop_off_point_seconds": None,
            }
        )
    # Only 2 records for this rare topic - must not produce a topic_platform pattern.
    for i in range(2):
        records.append(
            {
                "platform": "youtube",
                "content_type": "video",
                "topic": "rare_topic",
                "format": "short_clip",
                "publish_hour": 10,
                "day_of_week": "mon",
                "views": 50000,
                "likes": 5000,
                "shares": 2000,
                "watch_time_seconds": 60.0,
                "drop_off_point_seconds": None,
            }
        )

    patterns = agent.analyze(records)
    assert not any("rare_topic" in p["slice_key"] for p in patterns)


def test_real_hajj_data_produces_platform_patterns():
    # Real SBA Hajj 1445H season totals (backend/data/hajj_1445_platform_totals.json).
    totals = agent._load_real_hajj_totals(agent.REAL_DATA_PATH)
    assert totals is not None

    patterns = agent.analyze_real_hajj_platforms(totals)
    assert len(patterns) >= 3
    for p in patterns:
        assert p["dimension"] == "platform_reach_real"
        assert p["source"] == "real_hajj_1445_sba"
        assert 0 < p["confidence"] <= 0.85

    # YouTube dominates both impressions and views in the real data - both should surface.
    slice_keys = {p["slice_key"] for p in patterns}
    assert "impressions:youtube" in slice_keys
    assert "views:youtube" in slice_keys


def test_real_hajj_data_never_treats_a_missing_metric_as_zero():
    # TikTok reports no impressions figure in the source sheet - it must
    # never appear in an impressions-share comparison.
    totals = agent._load_real_hajj_totals(agent.REAL_DATA_PATH)
    patterns = agent.analyze_real_hajj_platforms(totals)
    assert not any(p["slice_key"] == "impressions:tiktok" for p in patterns)

    # Meta reports no views figure - it must never appear in a views-share
    # comparison or in the engagement/views rate comparison.
    assert not any(p["slice_key"] == "views:meta" for p in patterns)
    assert not any(p["slice_key"] == "engagement_per_views:meta" for p in patterns)


def test_real_hajj_patterns_merge_into_store_alongside_synthetic_ones():
    store_path = agent.STORE_PATH.parent / "_test_merged_store.json"
    try:
        records = agent._load_records(agent.DATA_PATH)
        synthetic = agent.analyze(records)
        totals = agent._load_real_hajj_totals(agent.REAL_DATA_PATH)
        real = agent.analyze_real_hajj_platforms(totals)

        merged = agent.upsert_store(synthetic + real, store_path)
        dimensions = {p["dimension"] for p in merged}
        assert "platform_reach_real" in dimensions
        assert "content_type" in dimensions
        assert len(merged) == len(synthetic) + len(real)
    finally:
        store_path.unlink(missing_ok=True)


def test_real_awj_sada_data_produces_descriptive_patterns():
    # Real AWJ | Sada podcast/X dataset (backend/data/awj_sada_real.json) -
    # 6 episodes (رهان + SO) and 5 X posts, too few to t-test.
    data = agent._load_real_awj_sada(agent.AWJ_REAL_DATA_PATH)
    assert data is not None

    patterns = agent.analyze_real_awj_sada(data)
    assert len(patterns) >= 1
    for p in patterns:
        assert p["dimension"] == "awj_sada_real"
        assert p["source"] == "real_awj_sada"
        assert 0 < p["confidence"] <= 0.75

    # رهان reports YouTube views on all 3 episodes vs. SO's 1 - رهان's much
    # higher average should surface as a pattern.
    slice_keys = {p["slice_key"] for p in patterns}
    assert "podcast_youtube_views:رهان" in slice_keys


def test_real_awj_sada_patterns_merge_into_store_alongside_others():
    store_path = agent.STORE_PATH.parent / "_test_merged_awj_store.json"
    try:
        records = agent._load_records(agent.DATA_PATH)
        synthetic = agent.analyze(records)
        data = agent._load_real_awj_sada(agent.AWJ_REAL_DATA_PATH)
        real_awj = agent.analyze_real_awj_sada(data)

        merged = agent.upsert_store(synthetic + real_awj, store_path)
        dimensions = {p["dimension"] for p in merged}
        assert "awj_sada_real" in dimensions
        assert "content_type" in dimensions
        assert len(merged) == len(synthetic) + len(real_awj)
    finally:
        store_path.unlink(missing_ok=True)
