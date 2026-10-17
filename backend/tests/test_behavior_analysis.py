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


def _real_record(
    platform: str,
    entity_key: str,
    channel_name_ar: str,
    content_type: str,
    topic: str,
    performance_index: float,
    day_of_week: str = "mon",
    publish_hour: int = 10,
) -> dict:
    """A minimal backend.repository.analysis_records()-shaped record.

    Only the fields analyze_real_data() actually reads - it's a pure function
    over this shape, so tests build it directly instead of needing a seeded
    database (that's exercised separately in test_data_collector.py).
    """
    return {
        "platform": platform,
        "entity_key": entity_key,
        "channel_name_ar": channel_name_ar,
        "content_type": content_type,
        "topic": topic,
        "performance_index": performance_index,
        "day_of_week": day_of_week,
        "publish_hour": publish_hour,
    }


def _real_records_for_slice(n: int, **overrides) -> list[dict]:
    base = dict(
        platform="youtube",
        entity_key="riyadiya_tv",
        channel_name_ar="قناة الرياضية",
        content_type="video",
        topic="sports",
        performance_index=1.0,
        day_of_week="mon",
        publish_hour=10,
    )
    base.update(overrides)
    pi = base.pop("performance_index")
    records = []
    for i in range(n):
        # Small deterministic jitter so each bucket has real variance (needed
        # for the Welch t-test) without materially changing the lift between
        # buckets - a perfectly constant value makes variance 0 and the
        # t-stat undefined, which _slice_pattern correctly treats as noise.
        jittered = pi * (1 + ((i % 5) - 2) * 0.03)
        records.append(_real_record(performance_index=jittered, **base))
    return records


def test_analyze_real_data_finds_real_content_type_and_topic_patterns():
    # "short" content clearly outperforms its own channel/type baseline (perf_index ~2.5),
    # "video" content on the same channel is roughly typical (perf_index ~1.0).
    records = (
        _real_records_for_slice(30, content_type="short", topic="sports", performance_index=2.5)
        + _real_records_for_slice(30, content_type="video", topic="news", performance_index=1.0)
    )

    patterns = agent.analyze_real_data(records)
    assert len(patterns) >= 1
    for p in patterns:
        assert p["source"] == "real_youtube_sba"
        assert p["dimension"] in {"content_type_real", "timing_real", "topic_real", "channel_topic_real"}

    dimensions = {p["dimension"] for p in patterns}
    assert "content_type_real" in dimensions
    assert "topic_real" in dimensions
    assert "channel_topic_real" in dimensions

    slice_keys = {p["slice_key"] for p in patterns}
    assert "short" in slice_keys
    assert "sports" in slice_keys
    assert "riyadiya_tv|sports" in slice_keys


def test_analyze_real_data_respects_min_samples():
    # Only 3 records for this channel/topic combo - must never surface a pattern for it,
    # same MIN_SAMPLES gate _slice_pattern already enforces for the synthetic path.
    records = _real_records_for_slice(30, content_type="video", performance_index=1.0) + _real_records_for_slice(
        3, entity_key="rare_channel", channel_name_ar="قناة نادرة", topic="economy", performance_index=5.0
    )

    patterns = agent.analyze_real_data(records)
    assert not any("rare_channel" in p["slice_key"] for p in patterns)
    assert not any(p["slice_key"] == "economy" for p in patterns)


def test_analyze_real_data_empty_records_returns_no_patterns():
    assert agent.analyze_real_data([]) == []


def test_analyze_real_data_cross_platform_dimension_needs_both_platforms():
    youtube_only = _real_records_for_slice(30, content_type="short", performance_index=2.0)
    patterns = agent.analyze_real_data(youtube_only)
    assert not any(p["dimension"] == "platform_content_real" for p in patterns)

    both_platforms = youtube_only + _real_records_for_slice(
        30, platform="instagram", entity_key="sba_ig", channel_name_ar="سبا", content_type="short", performance_index=0.3
    )
    patterns = agent.analyze_real_data(both_platforms)
    cross = [p for p in patterns if p["dimension"] == "platform_content_real"]
    assert cross, "expected a platform_content_real pattern when both platforms have enough samples"
    for p in cross:
        assert p["source"] == "real_sba"


def test_real_data_patterns_merge_into_store_with_real_patterns_first():
    store_path = agent.STORE_PATH.parent / "_test_merged_real_store.json"
    try:
        real_records = _real_records_for_slice(30, content_type="short", performance_index=2.5) + _real_records_for_slice(
            30, content_type="video", performance_index=1.0
        )
        real = agent.analyze_real_data(real_records)
        records = agent._load_records(agent.DATA_PATH)
        synthetic = agent.analyze(records)

        merged = agent.upsert_store(real + synthetic, store_path)
        assert len(merged) == len(real) + len(synthetic)
        # Real patterns were inserted first, and dict insertion order is preserved by upsert_store.
        first_ids = [p["pattern_id"] for p in merged[: len(real)]]
        assert first_ids == [p["pattern_id"] for p in real]
    finally:
        store_path.unlink(missing_ok=True)


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


def test_same_slice_on_two_platforms_keeps_both_patterns(tmp_path):
    # "short" over-performs on YouTube and on X alike: two patterns, two ids - neither overwrites the other.
    records = []
    for platform in ("youtube", "x"):
        records += _real_records_for_slice(30, platform=platform, content_type="short", performance_index=2.5)
        records += _real_records_for_slice(30, platform=platform, content_type="video", performance_index=1.0)
    found = [p for p in agent.analyze_real_data(records) if p["dimension"] == "content_type_real" and p["slice_key"] == "short"]
    assert {p["source"] for p in found} == {"real_youtube_sba", "real_x_sba"}
    assert len({p["pattern_id"] for p in found}) == 2

    stored = agent.run(store_path=tmp_path / "store.json", real_sba_records=records)
    assert {p["source"] for p in stored if p["dimension"] == "content_type_real" and p["slice_key"] == "short"} == {
        "real_youtube_sba", "real_x_sba"
    }


def test_corrupt_store_reads_as_empty_and_writes_leave_no_temp_files(tmp_path):
    store = tmp_path / "patterns" / "store.json"
    store.parent.mkdir()
    store.write_text('[{"pattern_id": "half-writ', encoding="utf-8")
    assert agent.load_store(store) == []

    agent._write_store(store, [{"pattern_id": "p1"}])
    assert agent.load_store(store) == [{"pattern_id": "p1"}]
    assert [f.name for f in store.parent.iterdir()] == ["store.json"]
