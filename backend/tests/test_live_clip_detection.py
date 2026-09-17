from backend.agents import live_clip_detection_agent as agent


def _flat_signal_with_noise(n=60, step=10):
    import random

    random.seed(1)
    return [
        {"timestamp_seconds": i * step, "engagement_level": round(20 + random.uniform(-4, 4), 1)}
        for i in range(n)
    ]


def _signal_with_two_spikes(n=80, step=10):
    signal = _flat_signal_with_noise(n, step)
    # Inject two clear, sustained spikes.
    for i in range(20, 23):
        signal[i]["engagement_level"] = 80.0
    for i in range(55, 58):
        signal[i]["engagement_level"] = 70.0
    return signal


def test_flags_the_real_spikes_and_ignores_noise():
    signal = _signal_with_two_spikes()
    segments = [
        {"start_seconds": 0, "end_seconds": 300, "label": "segment_a"},
        {"start_seconds": 300, "end_seconds": 600, "label": "segment_b"},
        {"start_seconds": 600, "end_seconds": 900, "label": "segment_c"},
    ]
    broadcast = {"segments": segments, "signal": signal}

    result = agent.detect_clip_opportunities(broadcast)

    # Acceptance criteria: flags the 2 real spikes, not the noise.
    assert len(result) == 2
    for opp in result:
        c = opp["clip_opportunity"]
        assert c["spike_magnitude"] > 50
        assert c["confidence"] > 0
        assert c["segment_label"] in {"segment_a", "segment_b", "segment_c"}


def test_flat_noisy_signal_yields_no_false_positives():
    signal = _flat_signal_with_noise()
    segments = [{"start_seconds": 0, "end_seconds": 600, "label": "segment_a"}]
    broadcast = {"segments": segments, "signal": signal}

    result = agent.detect_clip_opportunities(broadcast)
    assert result == []


def test_seeded_mock_broadcast_has_expected_spikes():
    broadcast = agent.load_broadcast()
    result = agent.detect_clip_opportunities(broadcast)
    assert 1 <= len(result) <= 3
    labels = {o["clip_opportunity"]["segment_label"] for o in result}
    assert "حديث الدعم السكني" in labels or "ختام ولقاء الجمهور" in labels
