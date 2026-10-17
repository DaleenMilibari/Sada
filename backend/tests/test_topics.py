from datetime import datetime, timezone

from sqlalchemy import insert, select

from backend import db, topics
from backend.topics import TOPIC_HINTS, TOPICS, classify_by_rules

NOW = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)


def test_every_topic_has_a_classifier_hint():
    assert set(TOPIC_HINTS) == set(TOPICS)


def test_rules_split_the_old_broad_topics():
    assert classify_by_rules("ترحيب دولي بإدانة مجلس الأمن لهجمات ميليشيا الحوثي", "news") == "politics"
    assert classify_by_rules("صلاة المغرب من المسجد النبوي الشريف", "religious") == "quran_prayer"
    assert classify_by_rules("نور على الدرب مع معالي الشيخ صالح بن حميد ح629", "religious") == "religious"
    assert classify_by_rules("الحج المبرور | التعجل في الحج", "religious") == "hajj_umrah"
    assert classify_by_rules("صيف ديرتنا | صيفنا على كيفنا", "other") == "tourism"
    assert classify_by_rules("مسلسل وجوه بلا ملامح - الحلقة الثامنة", "entertainment") == "drama"


def test_rules_match_whole_words_not_fragments():
    # "الحج" inside "الحجر", "الطبي" inside "الطبيعة", "حاج" inside "يحتاج" must not match.
    assert classify_by_rules("برنامج الوجيز في التفسير سورة الحجر", "other") == "religious"
    assert classify_by_rules("محافظة المندق؛ وجهةٌ سياحية تنبض بجمال الطبيعة", "other") == "tourism"
    assert classify_by_rules("يحتاج الطالب إلى وقت", "other") == "other"


def test_migrate_taxonomy_resorts_once_and_queues_llm_refinement(_isolated_database):
    engine = _isolated_database
    with engine.begin() as conn:
        conn.execute(insert(db.channels).values(
            channel_id="c1", platform="x", entity_key="ekhbariya", handle="@a", name_ar="قناة الإخبارية",
        ))
        conn.execute(insert(db.videos), [
            {"video_id": "v1", "platform": "x", "channel_id": "c1", "title": "روسيا وأوكرانيا.. اتهامات",
             "published_at": NOW, "content_type": "text", "topic": "news", "topic_source": "llm", "first_seen_at": NOW},
            {"video_id": "v2", "platform": "x", "channel_id": "c1", "title": "عاجل: الدفاع المدني",
             "published_at": NOW, "content_type": "text", "topic": "news", "topic_source": "llm", "first_seen_at": NOW},
        ])

    assert topics.migrate_taxonomy(engine) == 1  # only v1 changes topic
    with engine.connect() as conn:
        rows = dict(conn.execute(select(db.videos.c.video_id, db.videos.c.topic)).all())
        sources = {r for (r,) in conn.execute(select(db.videos.c.topic_source))}
    assert rows == {"v1": "politics", "v2": "news"}
    assert sources == {"rule"}  # both go back to the Gemini queue for the new topic list
    assert topics.migrate_taxonomy(engine) == 0  # recorded in app_meta - never runs twice
