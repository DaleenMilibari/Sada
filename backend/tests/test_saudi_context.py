import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import insert

from backend import db, draft_suggest, saudi_context
from backend.agents import audience_agent, llm_client


def test_voice_per_tone_is_saudi():
    interactive = saudi_context.writing_voice("تفاعلي")
    formal = saudi_context.writing_voice("رسمي")
    assert "لهجة سعودية بيضاء" in interactive and "وش رأيكم" in interactive
    assert "فصحى" in formal and "وش رأيكم" not in formal
    for v in (interactive, formal, saudi_context.writing_voice(None)):
        assert "التعابير المصرية والشامية" in v  # always steer away from non-Saudi dialects


def test_occasions_and_weekend():
    assert saudi_context.upcoming_occasions(date(2026, 9, 10)) == [("اليوم الوطني السعودي", 13)]
    assert saudi_context.upcoming_occasions(date(2026, 10, 17)) == []
    assert ("يوم التأسيس", 64) in saudi_context.upcoming_occasions(date(2026, 12, 20), window_days=70)  # next year
    friday = datetime(2026, 10, 16, 9, 0, tzinfo=timezone.utc)
    assert "الجمعة" in saudi_context.local_moment(friday) and "عطلة نهاية الأسبوع" in saudi_context.local_moment(friday)
    assert "صلاة الجمعة" in saudi_context.local_moment(friday)
    assert "عطلة" not in saudi_context.local_moment(friday + timedelta(days=3))


def test_hijri_calendar_and_seasons():
    # Known Saudi dates (the arithmetic calendar is within a day of Umm al-Qura).
    assert saudi_context.to_hijri(date(2026, 2, 18)) == (1447, 9, 1)
    assert saudi_context.from_hijri(1447, 12, 10) == date(2026, 5, 27)
    assert "1448هـ" in saudi_context.local_moment(datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc))
    # Ramadan 1448 starts around 8 Feb 2027: announced (approximately) ahead, then shapes the timing.
    before = saudi_context.local_moment(datetime(2027, 1, 30, 9, 0, tzinfo=timezone.utc))
    assert "شهر رمضان بعد 9 أيام تقريباً" in before
    during = saudi_context.local_moment(datetime(2027, 3, 3, 9, 0, tzinfo=timezone.utc))
    assert "نحن في شهر رمضان" in during and "العشر الأواخر" in during and "بعد الإفطار" in during
    assert "عيد الفطر" in during  # coming up within the window
    assert "موسم الحج" in saudi_context.local_moment(datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc))
    assert saudi_context.current_season(date(2026, 10, 22)) is None


def test_audience_classification_gets_dialect_guide(_isolated_database, monkeypatch):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@r", "name_ar": "الرياضية"})
        conn.execute(insert(db.videos), {
            "video_id": "v1", "platform": "youtube", "channel_id": "UC1", "title": "t", "url": "u", "published_at": db.utcnow(),
            "content_type": "video", "topic": "sports", "topic_source": "rule", "first_seen_at": db.utcnow()})
        conn.execute(insert(db.audience_comments), {
            "comment_id": "c1", "platform": "youtube", "video_id": "v1", "text": "كفو يعطيكم العافية",
            "published_at": db.utcnow(), "collected_at": db.utcnow()})
    prompts = []
    monkeypatch.setattr(llm_client, "generate_json", lambda p: prompts.append(p) or json.dumps({"0": {"s": "positive", "i": "praise"}}))

    assert audience_agent.classify_pending(10) == 1
    assert "هلالي، نصراوي" in prompts[0] and "«كفو»" in prompts[0]


def test_draft_suggestion_uses_saudi_voice_for_the_chosen_tone(_isolated_database, monkeypatch):
    with _isolated_database.begin() as conn:
        conn.execute(insert(db.channels), {"channel_id": "UC1", "platform": "youtube", "entity_key": "riyadiya", "handle": "@r", "name_ar": "الرياضية", "subscriber_count": 1})
        conn.execute(insert(db.videos), {
            "video_id": "v1", "platform": "youtube", "channel_id": "UC1", "title": "هدف", "url": "u",
            "published_at": db.utcnow() - timedelta(days=2), "content_type": "video", "topic": "sports", "topic_source": "rule",
            "view_count": 10, "like_count": 1, "comment_count": 1, "first_seen_at": db.utcnow(), "stats_updated_at": db.utcnow()})
    prompts = []
    monkeypatch.setattr(llm_client, "generate_json", lambda p: prompts.append(p) or json.dumps({"text": "x"}))

    draft_suggest.suggest("sports", "video", ["riyadiya"], tone="تفاعلي")

    assert "لهجة سعودية بيضاء" in prompts[0] and "بتوقيت الرياض" in prompts[0]
