import json
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend import db, repository
from backend.instagram_import import import_file, scraped_at

SCRAPED = datetime(2026, 10, 16, 15, 39, 19, tzinfo=timezone.utc)


def _post(post_id, *, type_="Image", product="feed", likes=10, comments=None, ts="2026-10-05T13:28:15.000Z", **extra):
    return {
        "id": post_id, "type": type_, "productType": product, "shortCode": f"S{post_id}",
        "caption": "المنتخب في نهائي كأس الخليج", "url": f"https://www.instagram.com/p/S{post_id}/",
        "commentsCount": len(comments or []), "latestComments": comments or [],
        "likesCount": likes, "timestamp": ts,
        "ownerFullName": "هيئة الإذاعة والتلفزيون", "ownerUsername": "sbagovsa", "ownerId": "52244420729",
        **extra,
    }


def _comment(comment_id, text="ماشاء الله", replies=None):
    return {"id": comment_id, "text": text, "ownerUsername": "someone", "timestamp": "2026-10-07T17:40:21.000Z",
            "likesCount": 1, "replies": replies}


def _write(tmp_path, items):
    path = tmp_path / "dataset_instagram-scraper_2026-10-16_15-39-19-781.json"
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return path


def test_scrape_time_comes_from_file_name(tmp_path):
    assert scraped_at(tmp_path / "dataset_instagram-scraper_2026-10-16_15-39-19-781.json") == SCRAPED


def test_import_stores_posts_and_comments_like_the_collector(tmp_path):
    path = _write(tmp_path, [
        {"url": "https://www.instagram.com/saudiatv/", "username": "saudiatv", "error": "not_found"},
        _post("1", comments=[_comment("c1", replies=[_comment("c2", text="رد")]), _comment("c3", text="  ")]),
        _post("2", type_="Video", product="clips", likes=-1, videoDuration=35.7, videoPlayCount=4658),
        _post("3", type_="Sidecar", product="carousel_container"),
    ])

    result = import_file(path)

    assert result["channels_new"] == 1 and result["posts_new"] == 3 and result["comments_new"] == 2
    assert result["skipped_accounts"] == ["saudiatv"]
    with db.get_engine().connect() as conn:
        channel = conn.execute(select(db.channels)).mappings().one()
        posts = {r["video_id"]: r for r in conn.execute(select(db.videos)).mappings()}
        comments = conn.execute(select(db.audience_comments)).mappings().all()
    assert (channel["platform"], channel["entity_key"], channel["handle"]) == ("instagram", "sba", "@sbagovsa")
    assert {k: p["content_type"] for k, p in posts.items()} == {"1": "image", "2": "short", "3": "carousel"}
    assert posts["2"]["like_count"] is None  # hidden likes are unknown, not 0
    assert posts["2"]["duration_seconds"] == 36 and posts["2"]["view_count"] is None
    assert all(p["platform"] == "instagram" and p["topic"] == "sports" for p in posts.values())
    assert {c["comment_id"] for c in comments} == {"ig_c1", "ig_c2"}
    assert all(c["video_id"] == "1" and c["sentiment"] is None for c in comments)
    assert "ownerUsername" not in json.dumps([dict(c) for c in comments], default=str)

    # The posts reach the same feed every agent reads.
    assert len(repository.analysis_records(min_age_days=0, platform="instagram")) == 3


def test_reimport_adds_nothing_and_keeps_classifications(tmp_path):
    path = _write(tmp_path, [_post("1", comments=[_comment("c1")])])
    import_file(path)
    with db.get_engine().begin() as conn:
        conn.execute(db.audience_comments.update().values(sentiment="positive", intent="praise"))

    result = import_file(path)

    assert (result["posts_new"], result["posts_updated"], result["snapshots"], result["comments_new"]) == (0, 0, 0, 0)
    with db.get_engine().connect() as conn:
        assert conn.execute(select(func.count()).select_from(db.video_snapshots)).scalar() == 1
        assert conn.execute(select(db.audience_comments.c.sentiment)).scalar() == "positive"


def test_older_scrape_never_overwrites_fresher_stats(tmp_path):
    import_file(_write(tmp_path, [_post("1", likes=10)]))
    later = datetime(2026, 10, 20, tzinfo=timezone.utc)
    with db.get_engine().begin() as conn:
        conn.execute(db.videos.update().values(like_count=99, stats_updated_at=later))

    old = tmp_path / "dataset_instagram-scraper_2026-10-01_00-00-00-000.json"
    old.write_text(json.dumps([_post("1", likes=5)]), encoding="utf-8")
    result = import_file(old)

    assert result["posts_updated"] == 0
    with db.get_engine().connect() as conn:
        assert conn.execute(select(db.videos.c.like_count)).scalar() == 99
