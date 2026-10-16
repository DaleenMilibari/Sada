import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend import apify_import, db

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
ACCOUNTS = [{"entity_key": "saudiya", "username": "saudiyatv"}]


def _post(post_id, owner="saudiyatv", age=timedelta(hours=3), **overrides):
    post = {
        "id": post_id, "shortCode": f"sc{post_id}", "type": "Image", "productType": "feed",
        "caption": "منشور", "url": f"https://www.instagram.com/p/sc{post_id}/",
        "likesCount": 100, "commentsCount": 5, "ownerUsername": owner, "ownerId": "IG1",
        "ownerFullName": "قناة السعودية", "timestamp": (NOW - age).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }
    post.update(overrides)
    return post


def _import(posts, profiles=None):
    return apify_import.import_posts(db.get_engine(), posts, profiles, accounts=ACCOUNTS, now=NOW)


def test_imports_known_account_and_skips_others():
    report = _import([_post("1"), _post("2", likesCount=-1), _post("x", owner="stranger", ownerId="IG9")])

    assert report["accounts"]["saudiyatv"] == {"entity_key": "saudiya", "posts": 2, "new": 2, "updated": 0}
    assert report["skipped"] == {"stranger": 1}
    with db.get_engine().connect() as conn:
        posts = {r.video_id: r for r in conn.execute(select(db.videos))}
        channel = conn.execute(select(db.channels)).one()
    assert set(posts) == {"1", "2"}
    assert posts["1"].platform == "instagram" and posts["1"].like_count == 100 and posts["1"].view_count is None
    assert posts["2"].like_count is None  # hidden likes (-1) are missing, never a number
    assert channel.entity_key == "saudiya" and channel.channel_id == "IG1" and channel.handle == "@saudiyatv"


def test_owner_match_ignores_case_and_reels_become_shorts():
    report = _import([_post("1", owner="SaudiyaTV", type="Video", productType="clips")])
    assert report["accounts"]["saudiyatv"]["posts"] == 1
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.videos.c.content_type)).scalar() == "short"


def test_profiles_file_adds_follower_counts():
    profiles = [{"id": "IG1", "username": "saudiyatv", "fullName": "Saudi Channel", "followersCount": 2_400_000, "postsCount": 8000}]
    _import([_post("1")], profiles)
    with db.get_engine().connect() as conn:
        channel = conn.execute(select(db.channels)).one()
    assert channel.subscriber_count == 2_400_000 and channel.video_count == 8000 and channel.title == "Saudi Channel"


def test_reimport_updates_instead_of_duplicating():
    _import([_post("1")])
    report = _import([_post("1", likesCount=250)])
    assert report["accounts"]["saudiyatv"]["new"] == 0 and report["accounts"]["saudiyatv"]["updated"] == 1
    with db.get_engine().connect() as conn:
        rows = conn.execute(select(db.videos)).all()
    assert len(rows) == 1 and rows[0].like_count == 250


def test_account_without_an_id_is_reported_not_guessed():
    post = _post("1")
    del post["ownerId"]
    report = _import([post])
    assert report["accounts"] == {}
    assert any("no account id" in p for p in report["problems"])


def test_duplicate_and_unusable_items_are_reported():
    report = _import([_post("1"), _post("1"), _post("2", timestamp=None), {"error": "no_items", "errorDescription": "x"}])
    assert report["accounts"]["saudiyatv"]["posts"] == 1
    assert len(report["problems"]) == 2


def test_cli_reads_a_downloaded_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(apify_import, "SBA_INSTAGRAM_ACCOUNTS", ACCOUNTS)
    path = tmp_path / "posts.json"
    path.write_text(json.dumps([_post("1")], ensure_ascii=False), encoding="utf-8")

    assert apify_import.main([str(path)]) == 0
    assert "@saudiyatv (saudiya): 1 posts, 1 new" in capsys.readouterr().out

    (tmp_path / "bad.json").write_text("{}", encoding="utf-8")
    assert apify_import.main([str(tmp_path / "bad.json")]) == 2
