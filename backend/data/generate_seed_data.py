"""One-off generator for the three seed/mock datasets the agents read.

Run with `python -m backend.data.generate_seed_data` from the repo root to
regenerate data/engagement_records.json, data/content_history.json and
data/broadcast_mock.json. The generator is seeded so output is reproducible.

The engagement records are synthetic but built with intentional, known
correlations baked in (not pure noise) so Task 1's pattern detection has
real signal to recover:
  - video content_type outperforms image/text by a clear margin
  - weekday afternoon (14:00-17:00) publish hours underperform
  - the "national_event" topic on platform "x" spikes well above baseline
  - the "science" topic has very few samples, on purpose, to exercise the
    "don't fabricate a pattern from insufficient data" fallback path
"""

from __future__ import annotations

import json
import random
from pathlib import Path

DATA_DIR = Path(__file__).parent

random.seed(42)

PLATFORMS = ["x", "youtube", "instagram", "snapchat"]
CONTENT_TYPES = ["video", "image", "text"]
FORMATS = {
    "video": ["short_clip", "long_form"],
    "image": ["single_photo", "carousel"],
    "text": ["caption_only"],
}
TOPICS = ["national_event", "housing_support", "sports", "economy", "general", "science"]
WEEKDAYS = ["sun", "mon", "tue", "wed", "thu"]
WEEKEND = ["fri", "sat"]
ALL_DAYS = WEEKDAYS + WEEKEND


def _content_type_multiplier(content_type: str) -> float:
    return {"video": 3.0, "image": 1.0, "text": 0.8}[content_type]


def _hour_multiplier(day_of_week: str, hour: int) -> float:
    if day_of_week in WEEKDAYS and 14 <= hour <= 17:
        return 0.6
    return 1.0


def _topic_platform_multiplier(topic: str, platform: str) -> float:
    if topic == "national_event" and platform == "x":
        return 1.6
    return 1.0


def generate_engagement_records(n: int = 260) -> list[dict]:
    records = []
    for _ in range(n):
        content_type = random.choice(CONTENT_TYPES)
        fmt = random.choice(FORMATS[content_type])
        platform = random.choice(PLATFORMS)
        day = random.choice(ALL_DAYS)
        hour = random.randint(6, 23)

        # "science" is deliberately rare across the whole dataset.
        if random.random() < 0.02:
            topic = "science"
        else:
            topic = random.choice([t for t in TOPICS if t != "science"])

        # content_type drives reach (views); timing/topic-platform drive how
        # interested the audience is once reached (engagement rate + watch
        # time) - keeping these on separate axes means a rate-based
        # engagement score (likes/shares per view) can actually recover the
        # timing/topic signal instead of it cancelling out against views.
        base_views = random.uniform(4000, 9000)
        views = int(base_views * _content_type_multiplier(content_type) * random.uniform(0.85, 1.15))

        rate_mult = (
            _hour_multiplier(day, hour)
            * _topic_platform_multiplier(topic, platform)
            * random.uniform(0.85, 1.15)
        )
        base_engagement_rate = random.uniform(0.03, 0.06) * rate_mult
        likes = int(views * base_engagement_rate * random.uniform(0.9, 1.1))
        shares = int(views * base_engagement_rate * 0.3 * random.uniform(0.8, 1.2))

        watch_time_base = {"video": 45.0, "image": 6.0, "text": 4.0}[content_type]
        watch_time_seconds = round(watch_time_base * rate_mult * random.uniform(0.7, 1.3), 1)
        drop_off = (
            round(watch_time_seconds * random.uniform(0.4, 0.9), 1)
            if content_type == "video"
            else None
        )

        records.append(
            {
                "platform": platform,
                "content_type": content_type,
                "topic": topic,
                "format": fmt,
                "publish_hour": hour,
                "day_of_week": day,
                "views": views,
                "likes": likes,
                "shares": shares,
                "watch_time_seconds": watch_time_seconds,
                "drop_off_point_seconds": drop_off,
            }
        )
    return records


CONTENT_TITLES = {
    "national_event": [
        "تغطية حية للاحتفال الوطني",
        "لقطات من الفعالية الوطنية الكبرى",
        "جمهور غفير يحتفل باليوم الوطني",
    ],
    "housing_support": [
        "حديث عن مبادرات الدعم السكني",
        "شرح برنامج التمويل العقاري الجديد",
        "قصص نجاح من مستفيدي الدعم السكني",
    ],
    "sports": [
        "ملخص مباراة نهائي البطولة",
        "تحليل أداء المنتخب الوطني",
        "أبرز أهداف الجولة",
    ],
    "economy": [
        "نظرة على مؤشرات الاقتصاد المحلي",
        "تقرير النمو الاقتصادي الفصلي",
    ],
    "general": [
        "جولة إخبارية يومية",
        "أبرز عناوين اليوم",
        "لقاء مع أحد المسؤولين",
    ],
    "science": [
        "ندوة حول الابتكار العلمي",
    ],
}


def generate_content_history(n_per_topic: int = 8) -> list[dict]:
    items = []
    counter = 0
    for topic, titles in CONTENT_TITLES.items():
        # "science" stays sparse on purpose (mirrors the engagement dataset).
        count = 2 if topic == "science" else n_per_topic
        for i in range(count):
            counter += 1
            content_type = random.choice(CONTENT_TYPES)
            fmt = random.choice(FORMATS[content_type])
            platform = random.choice(PLATFORMS)
            hour = random.randint(6, 23)
            day = random.choice(ALL_DAYS)

            base_views = random.uniform(4000, 9000)
            views = int(base_views * _content_type_multiplier(content_type) * random.uniform(0.85, 1.15))
            rate_mult = (
                _hour_multiplier(day, hour)
                * _topic_platform_multiplier(topic, platform)
                * random.uniform(0.85, 1.15)
            )
            base_engagement_rate = random.uniform(0.03, 0.06) * rate_mult
            likes = int(views * base_engagement_rate * random.uniform(0.9, 1.1))
            shares = int(views * base_engagement_rate * 0.3 * random.uniform(0.8, 1.2))
            watch_time_base = {"video": 45.0, "image": 6.0, "text": 4.0}[content_type]
            watch_time_seconds = round(watch_time_base * rate_mult * random.uniform(0.7, 1.3), 1)

            content_id = f"c-{counter:04d}"
            items.append(
                {
                    "content_id": content_id,
                    "title": random.choice(titles),
                    "platform": platform,
                    "content_type": content_type,
                    "topic": topic,
                    "format": fmt,
                    "publish_hour": hour,
                    "views": views,
                    "likes": likes,
                    "shares": shares,
                    "watch_time_seconds": watch_time_seconds,
                    "url_or_ref": f"internal://archive/{content_id}",
                }
            )
    return items


def generate_broadcast_mock() -> dict:
    """~20 minutes (1200s) sampled every 10s, with two intentional spikes."""
    segments = [
        {"start_seconds": 0, "end_seconds": 300, "label": "افتتاحية البرنامج"},
        {"start_seconds": 300, "end_seconds": 620, "label": "حديث الدعم السكني"},
        {"start_seconds": 620, "end_seconds": 900, "label": "فقرة رياضية"},
        {"start_seconds": 900, "end_seconds": 1200, "label": "ختام ولقاء الجمهور"},
    ]

    signal = []
    for t in range(0, 1200, 10):
        baseline = 20 + 5 * random.uniform(-1, 1)
        # Spike 1: inside "housing support" segment.
        if 440 <= t <= 470:
            baseline += 55
        # Spike 2: inside the closing segment.
        elif 1080 <= t <= 1110:
            baseline += 40
        else:
            baseline += random.uniform(-4, 4)  # ordinary noise, not a spike
        signal.append({"timestamp_seconds": t, "engagement_level": round(max(baseline, 0), 1)})

    return {"segments": segments, "signal": signal}


def main() -> None:
    engagement_records = generate_engagement_records()
    content_history = generate_content_history()
    broadcast_mock = generate_broadcast_mock()

    (DATA_DIR / "engagement_records.json").write_text(
        json.dumps(engagement_records, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_DIR / "content_history.json").write_text(
        json.dumps(content_history, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (DATA_DIR / "broadcast_mock.json").write_text(
        json.dumps(broadcast_mock, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"Wrote {len(engagement_records)} engagement records, "
        f"{len(content_history)} content history items, "
        f"{len(broadcast_mock['signal'])} broadcast signal points."
    )


if __name__ == "__main__":
    main()
