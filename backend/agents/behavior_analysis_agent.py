"""Task 1 - Behavior Analysis Agent.

Detects engagement patterns across content type, topic, timing and platform
from the seeded engagement dataset, and maintains a persistent pattern store
that Tasks 2 and 3 read from. See team.md for the full spec.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).parent.parent / "data" / "engagement_records.json"
STORE_PATH = Path(__file__).parent.parent / "store" / "pattern_store.json"

MIN_SAMPLES = 10
MIN_LIFT = 0.20  # a slice must beat (or trail) the baseline by >=20% to count
MIN_T_STAT = 2.5  # Welch's t-stat threshold so noise from small buckets doesn't pass as a pattern


def engagement_score(record: dict[str, Any]) -> float:
    """A single comparable engagement number per record."""
    views = max(record["views"], 1)
    return (record["likes"] + record["shares"] * 2) / views + record["watch_time_seconds"] / 60


def _pattern_id(dimension: str, value: str) -> str:
    return hashlib.sha1(f"{dimension}:{value}".encode("utf-8")).hexdigest()[:12]


def _load_records(dataset_path: Path) -> list[dict[str, Any]]:
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def _welch_t_stat(sample: list[float], rest: list[float]) -> float:
    n1, n2 = len(sample), len(rest)
    if n1 < 2 or n2 < 2:
        return 0.0
    m1, m2 = statistics.mean(sample), statistics.mean(rest)
    v1, v2 = statistics.variance(sample), statistics.variance(rest)
    se = ((v1 / n1) + (v2 / n2)) ** 0.5
    if se == 0:
        return 0.0
    return (m1 - m2) / se


def _content_type_normalized_score_fn(records: list[dict[str, Any]]):
    """Score relative to that record's own content_type baseline.

    content_type has by far the largest effect on raw engagement (video vs.
    image vs. text), which would otherwise swamp the variance used to test
    smaller timing/topic effects and hide them. Normalizing removes that
    confound so those slices are tested on a comparable scale.
    """
    by_type: dict[str, list[float]] = {}
    for r in records:
        by_type.setdefault(r["content_type"], []).append(engagement_score(r))
    type_means = {t: statistics.mean(scores) for t, scores in by_type.items()}

    def scorer(r: dict[str, Any]) -> float:
        mean = type_means.get(r["content_type"]) or 1.0
        return engagement_score(r) / mean

    return scorer


def _slice_pattern(
    records: list[dict[str, Any]],
    dimension: str,
    key_fn,
    describe_fn,
    score_fn=engagement_score,
) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        key = key_fn(r)
        buckets.setdefault(key, []).append(r)

    patterns = []
    for key, bucket in buckets.items():
        rest = [r for r in records if key_fn(r) != key]
        if len(bucket) < MIN_SAMPLES or len(rest) < MIN_SAMPLES:
            # Not enough evidence for this slice (or its complement) - skip rather than guess.
            continue

        bucket_scores = [score_fn(r) for r in bucket]
        rest_scores = [score_fn(r) for r in rest]
        bucket_mean = statistics.mean(bucket_scores)
        rest_mean = statistics.mean(rest_scores)
        if rest_mean == 0:
            continue
        lift = (bucket_mean - rest_mean) / rest_mean
        if abs(lift) < MIN_LIFT:
            continue

        t_stat = _welch_t_stat(bucket_scores, rest_scores)
        if abs(t_stat) < MIN_T_STAT:
            # Effect isn't statistically distinguishable from noise at this sample size.
            continue

        affected_types = sorted({r["content_type"] for r in bucket})
        direction = "أعلى" if lift > 0 else "أقل"
        text = describe_fn(key, lift, direction)
        patterns.append(
            {
                "pattern_id": _pattern_id(dimension, key),
                "pattern": text,
                "supporting_metric": (
                    f"متوسط مؤشر التفاعل {bucket_mean:.2f} مقابل بقية العينة {rest_mean:.2f} "
                    f"(n={len(bucket)}, lift={lift * 100:.1f}%, t={t_stat:.1f})"
                ),
                "confidence": round(min(0.99, 0.5 + min(len(bucket), 60) / 120 + min(abs(t_stat), 10) / 20), 2),
                "affected_content_types": affected_types,
                "dimension": dimension,
                "slice_key": key,
                "lift_pct": round(lift * 100, 1),
            }
        )
    return patterns


def hour_bucket(day_of_week: str, hour: int) -> str:
    is_weekday = day_of_week in {"sun", "mon", "tue", "wed", "thu"}
    if not is_weekday:
        return "weekend"
    if 14 <= hour <= 17:
        return "weekday_afternoon_14_17"
    if hour >= 18:
        return "weekday_evening_18_23"
    return "weekday_morning_6_13"


def analyze(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not records:
        return []

    patterns: list[dict[str, Any]] = []
    normalized_score = _content_type_normalized_score_fn(records)

    patterns += _slice_pattern(
        records,
        "content_type",
        key_fn=lambda r: r["content_type"],
        describe_fn=lambda key, lift, direction: (
            f"محتوى {key} يحقق تفاعلاً {direction} بنسبة {abs(lift) * 100:.0f}% عن بقية أنواع المحتوى."
        ),
    )

    patterns += _slice_pattern(
        records,
        "timing",
        key_fn=lambda r: hour_bucket(r["day_of_week"], r["publish_hour"]),
        describe_fn=lambda key, lift, direction: (
            f"الفترة الزمنية ({key}) ترتبط بتفاعل {direction} بنسبة {abs(lift) * 100:.0f}% عن بقية الأوقات "
            f"(بعد ضبط أثر نوع المحتوى)."
        ),
        score_fn=normalized_score,
    )

    patterns += _slice_pattern(
        records,
        "topic_platform",
        key_fn=lambda r: f"{r['topic']}|{r['platform']}",
        describe_fn=lambda key, lift, direction: (
            f"موضوع '{key.split('|')[0]}' على منصة '{key.split('|')[1]}' يحقق تفاعلاً {direction} "
            f"بنسبة {abs(lift) * 100:.0f}% عن بقية المحتوى (بعد ضبط أثر نوع المحتوى)."
        ),
        score_fn=normalized_score,
    )

    return patterns


def load_store(store_path: Path = STORE_PATH) -> list[dict[str, Any]]:
    if not store_path.exists():
        return []
    return json.loads(store_path.read_text(encoding="utf-8"))


def _write_store(store_path: Path, patterns: list[dict[str, Any]]) -> None:
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8")


def upsert_store(new_patterns: list[dict[str, Any]], store_path: Path = STORE_PATH) -> list[dict[str, Any]]:
    """Merge new_patterns into the persisted store, keyed by pattern_id.

    Re-running the agent on refreshed data updates existing patterns in
    place instead of duplicating them, per team.md's acceptance criteria.
    """
    existing = {p["pattern_id"]: p for p in load_store(store_path)}
    for p in new_patterns:
        existing[p["pattern_id"]] = p
    merged = list(existing.values())
    _write_store(store_path, merged)
    return merged


def run(dataset_path: Path = DATA_PATH, store_path: Path = STORE_PATH) -> list[dict[str, Any]]:
    records = _load_records(dataset_path)
    patterns = analyze(records)
    return upsert_store(patterns, store_path)


if __name__ == "__main__":
    result = run()
    print(f"Pattern store now has {len(result)} pattern(s).")
    for p in result:
        print(f"- [{p['confidence']}] {p['pattern']}")
