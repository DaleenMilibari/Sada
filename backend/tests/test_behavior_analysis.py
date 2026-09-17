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
