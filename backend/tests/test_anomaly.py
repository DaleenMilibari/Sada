from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend import config, db
from backend.agents import anomaly_agent as anomaly
from backend.api import app

NOW = db.utcnow().replace(microsecond=0)


@pytest.fixture(autouse=True)
def _fresh_cache():
    anomaly.clear_cache()
    yield
    anomaly.clear_cache()


@pytest.fixture()
def engine(_isolated_database):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), [
            {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@r", "name_ar": "الرياضية"},
            {"channel_id": "IG1", "platform": "instagram", "entity_key": "saudiya", "handle": "s", "name_ar": "السعودية"},
        ])
    return _isolated_database


def add(engine, vid, *, age_h, snaps, platform="youtube", channel="UC1", content_type="video"):
    """`snaps`: [(age_hours, value)] - the last one is also the stored current count."""
    published = NOW - timedelta(hours=age_h)
    last = snaps[-1][1]
    ig = platform == "instagram"
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": vid, "platform": platform, "channel_id": channel, "title": f"عنوان {vid}", "url": f"https://x/{vid}",
            "published_at": published, "content_type": content_type, "topic": "sports", "topic_source": "rule",
            "view_count": None if ig else last, "like_count": last if ig else None, "comment_count": 0 if ig else None,
            "first_seen_at": published, "stats_updated_at": published + timedelta(hours=snaps[-1][0]),
        })
        conn.execute(insert(db.video_snapshots), [
            {"video_id": vid, "captured_at": published + timedelta(hours=a),
             "view_count": None if ig else v, "like_count": v if ig else None, "comment_count": 0 if ig else None}
            for a, v in snaps
        ])


def linear(rate, upto_h=48, step=6):
    return [(h, int(rate * h)) for h in range(step, upto_h + 1, step)]


def seed_normal(engine, n=12):
    """Peers a few days old, ~100 views/hour with small noise."""
    for i in range(n):
        add(engine, f"peer{i}", age_h=24 * 5 + i, snaps=linear(100 + i * 2, upto_h=96))


def test_only_the_spike_and_the_drop_are_flagged(engine):
    seed_normal(engine)
    add(engine, "spike", age_h=30, snaps=linear(500, upto_h=30))  # 5x the typical pace
    add(engine, "drop", age_h=30, snaps=linear(10, upto_h=30))  # 0.1x
    add(engine, "normal", age_h=30, snaps=linear(105, upto_h=30))

    found = {a["video"]["video_id"]: a for a in anomaly.detect(days=2)}
    assert set(found) == {"spike", "drop"}
    assert found["spike"]["kind"] == "spike" and found["spike"]["ratio"] >= 3
    assert found["spike"]["basis"] == "same_age" and found["spike"]["peers"] >= anomaly.MIN_PEERS
    assert found["spike"]["severity"] == "medium"  # ~5x < 6x
    assert found["drop"]["kind"] == "drop" and found["drop"]["ratio"] <= 0.33
    assert found["drop"]["severity"] == "high"


def test_too_few_peers_means_no_alert(engine):
    for i in range(anomaly.MIN_PEERS - 2):
        add(engine, f"peer{i}", age_h=120, snaps=linear(100, upto_h=96))
    add(engine, "spike", age_h=30, snaps=linear(900, upto_h=30))
    assert anomaly.detect(days=2) == []


def test_tiny_baseline_is_ignored(engine):
    for i in range(8):
        add(engine, f"peer{i}", age_h=120, snaps=[(6, 1), (24, 2), (48, 3), (96, 4)])
    add(engine, "tiny", age_h=30, snaps=[(6, 10), (24, 20), (30, 30)])
    assert anomaly.detect(days=2) == []


def test_young_posts_are_not_judged(engine):
    seed_normal(engine)
    add(engine, "newborn", age_h=3, snaps=[(1, 5000), (3, 9000)])
    assert anomaly.detect(days=2) == []


def test_velocity_takeoff_detected(engine):
    # No peers -> no level alert; the video itself jumps from 10/h to 200/h between snapshots.
    add(engine, "takeoff", age_h=30, snaps=[(6, 60), (12, 120), (18, 180), (24, 240), (30, 1440)])
    alerts = anomaly.detect(days=2)
    assert len(alerts) == 1
    a = alerts[0]
    assert a["detection"] == "velocity" and a["kind"] == "spike" and a["ratio"] == 20.0


def test_velocity_stall_detected(engine):
    add(engine, "stall", age_h=30, snaps=[(6, 600), (12, 1200), (18, 1800), (24, 2400), (30, 2410)])
    a = anomaly.detect(days=2)[0]
    assert a["detection"] == "velocity" and a["kind"] == "drop"


def test_instagram_uses_interactions(engine):
    for i in range(8):
        add(engine, f"ig{i}", age_h=24 * 5, snaps=linear(10 + i, upto_h=96), platform="instagram", channel="IG1")
    add(engine, "igspike", age_h=30, snaps=linear(100, upto_h=30), platform="instagram", channel="IG1")
    a = [x for x in anomaly.detect(days=2) if x["video"]["video_id"] == "igspike"][0]
    assert a["metric"] == "interactions" and a["kind"] == "spike"


def test_plateau_fallback_for_week_old_posts_without_history(engine):
    # One snapshot each (a one-shot import): only posts >= 7 days old can be judged, against peers' current values.
    for i in range(8):
        add(engine, f"old{i}", age_h=24 * 20, snaps=[(24 * 20, 1000 + i * 10)])
    add(engine, "hit", age_h=24 * 10, snaps=[(24 * 10, 20000)])
    add(engine, "fresh_hit", age_h=24 * 2, snaps=[(24 * 2, 20000)])  # too young for the plateau comparison
    found = {a["video"]["video_id"]: a for a in anomaly.detect(days=30)}
    assert found["hit"]["basis"] == "plateau" and found["hit"]["kind"] == "spike"
    assert "fresh_hit" not in found


def test_endpoint_contract(engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    seed_normal(engine)
    add(engine, "spike", age_h=30, snaps=linear(500, upto_h=30))
    with TestClient(app) as client:
        res = client.get("/api/alerts?days=7")
        assert res.status_code == 200
        alert = res.json()[0]
        for key in ("alert_id", "kind", "video", "metric", "observed", "expected", "ratio", "severity", "detected_at"):
            assert key in alert
        assert alert["video"]["url"] == "https://x/spike"
        assert client.get("/api/alerts?days=0").status_code == 422


def test_full_stall_ranks_as_the_most_severe_deviation():
    assert anomaly._deviation(0.0) > anomaly._deviation(0.1) > anomaly._deviation(0.2)
    assert anomaly._deviation(3.0) == pytest.approx(anomaly._deviation(1 / 3))


def test_downward_count_correction_is_a_stall_not_a_negative_ratio(engine):
    seed_normal(engine)
    # Growing ~100/h, then the platform removes views: the latest interval goes negative.
    add(engine, "corrected", age_h=30, snaps=[(12, 1200), (18, 1800), (24, 1500)])
    alerts = [a for a in anomaly.detect(days=7, now=NOW) if a["video"]["video_id"] == "corrected"]
    for a in alerts:
        assert a["ratio"] >= 0 and a["observed"] >= 0
