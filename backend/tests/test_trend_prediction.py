from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert

from backend import config, db
from backend.agents import trend_prediction_agent as trend

NOW = db.utcnow().replace(microsecond=0)
# Every fixture video follows views(age) = final * (age / 168h) ** 0.5 -> 37.8% of day 7 at 24 h.
GROWTH_EXPONENT = 0.5
SNAPSHOT_AGES_H = (1, 3, 6, 9, 12, 18, 24, 30, 36, 48, 60, 72, 96, 120, 144, 168, 192)


def curve(final: float, age_h: float) -> int:
    return int(final * min(age_h / 168, 1.0) ** GROWTH_EXPONENT) if age_h < 168 else int(final)


@pytest.fixture(autouse=True)
def _fresh_cache():
    trend.clear_cache()
    yield
    trend.clear_cache()


@pytest.fixture()
def engine(_isolated_database):
    with _isolated_database.begin() as conn:
        for i, key in enumerate(("riyadiya", "ekhbariya")):
            conn.execute(insert(db.channels), {
                "channel_id": f"UC{i}", "platform": "youtube", "entity_key": key, "handle": f"@{key}",
                "name_ar": f"قناة {key}", "subscriber_count": 1000,
            })
        conn.execute(insert(db.channels), {
            "channel_id": "IG0", "platform": "instagram", "entity_key": "saudiya", "handle": "saudiyatv", "name_ar": "السعودية",
        })
    return _isolated_database


def add_video(engine, video_id, *, age, channel="UC0", content_type="video", platform="youtube", snapshots=(), views=None):
    """`snapshots`: [(age_hours, views)]."""
    published = NOW - age
    with engine.begin() as conn:
        conn.execute(insert(db.videos), {
            "video_id": video_id, "platform": platform, "channel_id": channel, "title": f"عنوان {video_id}",
            "url": None, "published_at": published, "content_type": content_type, "topic": "sports",
            "topic_source": "rule", "view_count": views if views is not None else (snapshots[-1][1] if snapshots else None),
            "first_seen_at": published, "stats_updated_at": NOW,
        })
        if snapshots:
            conn.execute(insert(db.video_snapshots), [
                {"video_id": video_id, "captured_at": published + timedelta(hours=a), "view_count": v} for a, v in snapshots
            ])


def add_finished_videos(engine, n=30, channel="UC0", noise=0.05):
    """`n` finished videos with known growth, final sizes spread 1k-7k so a 'channel median' guess is poor."""
    for i in range(n):
        final = 1000 * (1 + i % 7)
        wobble = 1 + noise * ((i % 3) - 1)  # day-7 views off the pure curve by -5% / 0 / +5%
        snaps = [(a, curve(final, a) if a < 168 else int(final * wobble)) for a in SNAPSHOT_AGES_H]
        add_video(engine, f"{channel}_done{i}", age=timedelta(days=10 + i), channel=channel, snapshots=snaps)


def test_views_at_age_interpolates_and_refuses_to_guess():
    series = [(21.0, 210), (27.0, 270)]
    assert trend.views_at_age(series, 24) == pytest.approx(240)
    assert trend.views_at_age([(2.0, 10), (60.0, 600)], 24) is None  # snapshots too far apart
    assert trend.views_at_age([(166.0, 990)], 168) == 990  # one snapshot close enough
    assert trend.views_at_age([], 24) is None


def test_prediction_within_tolerance_of_known_growth_curve(engine):
    add_finished_videos(engine)
    model, _ = trend.build(NOW)

    for age_h in (24, 30, 100):  # on an anchor, and in between anchors
        predicted = model.predict({"entity_key": "riyadiya", "content_type": "video"}, curve(5000, age_h), age_h)
        assert predicted == pytest.approx(5000, rel=0.08)


def test_prediction_is_null_without_history(engine):
    add_finished_videos(engine, n=3)  # below MIN_CURVE_SAMPLES
    model, accuracy = trend.build(NOW)

    assert model.predict({"entity_key": "riyadiya", "content_type": "video"}, 400, 24) is None
    assert model.predict({"entity_key": "riyadiya", "content_type": "video"}, 400, 2) is None  # too young to tell
    assert accuracy["status"] == "insufficient_history"
    assert accuracy["mape"] is None and accuracy["n_test"] == 0


def test_backtest_beats_naive_baseline(engine):
    add_finished_videos(engine, n=40)
    _, accuracy = trend.build(NOW)

    assert accuracy["status"] == "ok"
    assert accuracy["n_test"] == 8  # newest 20% of 40
    assert accuracy["mape"] < 10
    assert accuracy["mape"] < accuracy["baseline_mape"]
    assert accuracy["beats_baseline"] is True
    assert 0 <= accuracy["top10_hit_rate"] <= 1
    # Hold-out is temporal: the test window starts after the training window.
    assert accuracy["train_window"].split(" → ")[1] <= accuracy["test_window"].split(" → ")[0]


def test_trending_ranks_the_fast_mover_first_and_skips_instagram(engine):
    add_finished_videos(engine)
    young = timedelta(hours=30)
    # Peers: steady ~100 views/hour over the last half hour.
    for i in range(5):
        add_video(engine, f"peer{i}", age=young, snapshots=[(29.5, 3000), (30.0, 3050)])
    add_video(engine, "rocket", age=young, snapshots=[(29.5, 3000), (30.0, 4000)])
    add_video(engine, "stale", age=timedelta(days=5), snapshots=[(1.0, 50)])  # one old snapshot: no velocity now
    add_video(engine, "ig_post", age=young, channel="IG0", content_type="image", platform="instagram",
              snapshots=[(29.5, None), (30.0, None)])

    items = trend.compute_trending(hours=24, limit=10, now=NOW, model=trend.build(NOW)[0])
    ids = [i["video"]["video_id"] for i in items]

    assert ids[0] == "rocket"
    assert {"stale", "ig_post"}.isdisjoint(ids)
    top = items[0]
    assert top["views_per_hour"] == pytest.approx(2000)
    assert top["velocity_index"] == pytest.approx(20)
    assert 0 < top["viral_score"] <= 1
    assert top["predicted_views_7d"] is not None and top["predicted_views_7d"] >= 4000
    assert "مشاهدة/ساعة" in top["reason"]


def test_endpoints_return_contract_shapes(engine, monkeypatch):
    monkeypatch.setattr(config, "AUTH_ENABLED", False)
    add_video(engine, "solo", age=timedelta(hours=10), snapshots=[(9.5, 900), (10.0, 1000)])
    from backend.api import app

    with TestClient(app) as client:
        assert client.get("/api/trending?hours=24&limit=5").status_code == 200
        res = client.get("/api/model/accuracy")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "insufficient_history" and body["mape"] is None
        assert client.get("/api/trending?hours=0").status_code == 422
