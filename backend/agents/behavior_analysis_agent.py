"""Task 1 - Behavior Analysis Agent.

Detects engagement patterns across content type, topic, timing and platform
from the seeded engagement dataset, and maintains a persistent pattern store
that Tasks 2 and 3 read from. See AGENT_SPEC.md for the full spec.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from backend.topics import TOPICS

DATA_PATH = Path(__file__).parent.parent / "data" / "engagement_records.json"
REAL_DATA_PATH = Path(__file__).parent.parent / "data" / "hajj_1445_platform_totals.json"
AWJ_REAL_DATA_PATH = Path(__file__).parent.parent / "data" / "awj_sada_real.json"
STORE_PATH = Path(__file__).parent.parent / "store" / "pattern_store.json"

MIN_SAMPLES = 10
MIN_LIFT = 0.20  # a slice must beat (or trail) the baseline by >=20% to count
MIN_T_STAT = 2.5  # Welch's t-stat threshold so noise from small buckets doesn't pass as a pattern

# Real-data (hajj_1445_platform_totals.json) thresholds. This source is
# season-level totals per platform, not per-post records, so there is no
# sample to t-test - REAL_MIN_LIFT alone gates which comparisons are worth
# surfacing, and REAL_MIN_PLATFORMS ensures we only compare platforms that
# actually report a given metric (never treat a missing cell as zero).
REAL_MIN_LIFT = 0.30
REAL_MIN_PLATFORMS = 2

# Real-data (awj_sada_real.json) thresholds. Same rationale as the hajj
# thresholds above - 6 episodes / 5 X posts is too few to t-test, so
# REAL_AWJ_MIN_LIFT alone gates which descriptive comparisons surface.
REAL_AWJ_MIN_LIFT = 0.30


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
                "source": "synthetic_seed_engagement_records",
            }
        )
    return patterns


PLATFORM_LABELS_AR = {"youtube": "يوتيوب", "instagram": "إنستغرام", "x": "إكس"}


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


def analyze_real_data(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Patterns from real SBA YouTube + Instagram posts.

    `records` is the output of backend.repository.analysis_records(): one flat
    dict per post, already restricted to posts old enough to have settled
    engagement, with `performance_index` (the post's primary metric divided by
    its own platform+channel+content_type median) as the comparable score -
    no extra normalization needed here, unlike analyze()'s synthetic path.

    Each platform is sliced separately (content type, timing, topic, and
    channel|topic) and tagged with its own source, since YouTube and
    Instagram posts aren't on the same scale even after indexing. A separate
    pass compares content types *across* both platforms at once (e.g. "Reels
    on Instagram vs. Shorts on YouTube"), tagged source="real_sba" since it
    isn't about one platform. Reuses the same significance gates as analyze()
    (MIN_SAMPLES / MIN_LIFT / MIN_T_STAT via _slice_pattern) so a channel or
    topic with too few real posts never produces a pattern.
    """
    if not records:
        return []

    def score_fn(r: dict[str, Any]) -> float:
        return r["performance_index"]

    def _tag_source(patterns: list[dict[str, Any]], source: str) -> list[dict[str, Any]]:
        for p in patterns:
            p["source"] = source
        return patterns

    all_patterns: list[dict[str, Any]] = []

    for platform in ("youtube", "instagram", "x"):
        platform_records = [r for r in records if r["platform"] == platform]
        if not platform_records:
            continue
        platform_ar = PLATFORM_LABELS_AR.get(platform, platform)
        source = f"real_{platform}_sba"
        channel_names = {r["entity_key"]: r["channel_name_ar"] for r in platform_records}

        content_patterns = _slice_pattern(
            platform_records,
            "content_type_real",
            key_fn=lambda r: r["content_type"],
            describe_fn=lambda key, lift, direction, platform_ar=platform_ar: (
                f"محتوى {key} على {platform_ar} يحقق مؤشر أداء {direction} بنسبة {abs(lift) * 100:.0f}% "
                f"عن بقية أنواع المحتوى على المنصة نفسها."
            ),
            score_fn=score_fn,
        )
        all_patterns += _tag_source(content_patterns, source)

        timing_patterns = _slice_pattern(
            platform_records,
            "timing_real",
            key_fn=lambda r: hour_bucket(r["day_of_week"], r["publish_hour"]),
            describe_fn=lambda key, lift, direction, platform_ar=platform_ar: (
                f"النشر في الفترة ({key}) على {platform_ar} يرتبط بمؤشر أداء {direction} بنسبة "
                f"{abs(lift) * 100:.0f}% عن بقية الأوقات على المنصة نفسها."
            ),
            score_fn=score_fn,
        )
        all_patterns += _tag_source(timing_patterns, source)

        topic_patterns = _slice_pattern(
            platform_records,
            "topic_real",
            key_fn=lambda r: r["topic"],
            describe_fn=lambda key, lift, direction, platform_ar=platform_ar: (
                f"موضوع '{TOPICS.get(key, key)}' على {platform_ar} يحقق مؤشر أداء {direction} بنسبة "
                f"{abs(lift) * 100:.0f}% عن بقية الموضوعات على المنصة نفسها."
            ),
            score_fn=score_fn,
        )
        all_patterns += _tag_source(topic_patterns, source)

        channel_topic_patterns = _slice_pattern(
            platform_records,
            "channel_topic_real",
            key_fn=lambda r: f"{r['entity_key']}|{r['topic']}",
            describe_fn=lambda key, lift, direction, platform_ar=platform_ar, channel_names=channel_names: (
                f"حساب {channel_names.get(key.split('|')[0], key.split('|')[0])} على {platform_ar} يحقق مؤشر "
                f"أداء {direction} بنسبة {abs(lift) * 100:.0f}% في موضوع '{TOPICS.get(key.split('|')[1], key.split('|')[1])}' "
                f"مقارنة ببقية محتواه."
            ),
            score_fn=score_fn,
        )
        all_patterns += _tag_source(channel_topic_patterns, source)

    # Cross-platform: does this content type on this platform beat the pooled
    # cross-platform baseline for content type (e.g. Reels on Instagram vs.
    # Shorts on YouTube)? Needs both platforms present to mean anything.
    platforms_seen = {r["platform"] for r in records}
    if len(platforms_seen) >= 2:
        cross_patterns = _slice_pattern(
            records,
            "platform_content_real",
            key_fn=lambda r: f"{r['platform']}|{r['content_type']}",
            describe_fn=lambda key, lift, direction: (
                f"محتوى {key.split('|')[1]} على {PLATFORM_LABELS_AR.get(key.split('|')[0], key.split('|')[0])} "
                f"يحقق مؤشر أداء {direction} بنسبة {abs(lift) * 100:.0f}% عن بقية أنواع المحتوى عبر كل المنصات."
            ),
            score_fn=score_fn,
        )
        all_patterns += _tag_source(cross_patterns, "real_sba")

    return all_patterns


def _load_real_hajj_totals(path: Path = REAL_DATA_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


METRIC_LABELS_AR = {"impressions": "مرات الظهور", "views": "المشاهدات"}
RATE_LABELS_AR = {
    ("engagement", "views"): "التفاعل لكل مشاهدة",
    ("engagement", "impressions"): "التفاعل لكل ظهور",
}


def _real_pattern(slice_key: str, text: str, metric_line: str, lift: float, n_reporting: int) -> dict[str, Any]:
    confidence = round(min(0.85, 0.5 + min(abs(lift), 2.0) / 4 + max(n_reporting - REAL_MIN_PLATFORMS, 0) * 0.05), 2)
    return {
        "pattern_id": _pattern_id("platform_reach_real", slice_key),
        "pattern": text,
        "supporting_metric": metric_line,
        "confidence": confidence,
        "affected_content_types": [],
        "dimension": "platform_reach_real",
        "slice_key": slice_key,
        "lift_pct": round(lift * 100, 1),
        "source": "real_hajj_1445_sba",
    }


def _share_patterns(platforms: dict[str, dict[str, Any]], metric: str, label_ar: str) -> list[dict[str, Any]]:
    """Each reporting platform's share of a metric vs. an equal-split baseline.

    Only platforms that actually report `metric` are included - a platform
    that doesn't report it (e.g. TikTok has no impressions figure in this
    source) is left out of the comparison entirely rather than counted as 0.
    """
    reporting = {p: v[metric] for p, v in platforms.items() if v.get(metric) is not None}
    if len(reporting) < REAL_MIN_PLATFORMS:
        return []
    total = sum(reporting.values())
    if total == 0:
        return []
    baseline_share = 1 / len(reporting)
    reported_list = "، ".join(sorted(reporting.keys()))
    out = []
    for platform, value in reporting.items():
        share = value / total
        lift = (share - baseline_share) / baseline_share
        if abs(lift) < REAL_MIN_LIFT:
            continue
        direction = "أعلى" if lift > 0 else "أقل"
        text = (
            f"منصة {platform} حصتها من {label_ar} خلال موسم حج 1445هـ {direction} من حصة متساوية متوقعة "
            f"بين المنصات المُبلغة ({share * 100:.1f}% مقابل {baseline_share * 100:.1f}%)."
        )
        metric_line = (
            f"{platform}={value:,.0f} من إجمالي {total:,.0f} مُبلَّغ بين {len(reporting)} منصات ({reported_list}); "
            f"حصة={share * 100:.1f}%, lift={lift * 100:.1f}%"
        )
        out.append(_real_pattern(f"{metric}:{platform}", text, metric_line, lift, len(reporting)))
    return out


def _rate_patterns(platforms: dict[str, dict[str, Any]], numerator: str, denominator: str, label_ar: str) -> list[dict[str, Any]]:
    """Compare platforms on numerator/denominator, but only where both are reported.

    e.g. engagement/views excludes YouTube here (no engagement figure) and
    engagement/impressions excludes TikTok (no impressions figure) - each
    rate is only ever compared across platforms on the same basis.
    """
    rates = {}
    for platform, vals in platforms.items():
        num, den = vals.get(numerator), vals.get(denominator)
        if num is not None and den:
            rates[platform] = num / den
    if len(rates) < REAL_MIN_PLATFORMS:
        return []
    out = []
    for platform, rate in rates.items():
        others = [r for p, r in rates.items() if p != platform]
        others_mean = statistics.mean(others)
        if others_mean == 0:
            continue
        lift = (rate - others_mean) / others_mean
        if abs(lift) < REAL_MIN_LIFT:
            continue
        direction = "أعلى" if lift > 0 else "أقل"
        text = (
            f"منصة {platform} يحقق معدل {label_ar} {direction} بنسبة {abs(lift) * 100:.0f}% عن بقية "
            f"المنصات القابلة للمقارنة خلال موسم حج 1445هـ."
        )
        metric_line = (
            f"{platform}: {numerator}/{denominator}={rate * 100:.2f}% مقابل متوسط بقية المنصات "
            f"{others_mean * 100:.2f}% (lift={lift * 100:.1f}%)"
        )
        out.append(_real_pattern(f"{numerator}_per_{denominator}:{platform}", text, metric_line, lift, len(rates)))
    return out


def analyze_real_hajj_platforms(totals: dict[str, Any]) -> list[dict[str, Any]]:
    """Descriptive patterns from real SBA Hajj 1445H season totals.

    This source (backend/data/hajj_1445_platform_totals.json, parsed from
    the raw SBA open-data file) is season-level totals per platform, not
    per-post records like engagement_records.json - so unlike analyze(),
    there's no sample to Welch-t-test. Each platform reports a different
    subset of metrics, so every comparison here is scoped to the platforms
    that actually report the metric(s) involved; a platform missing a
    metric is skipped for that comparison rather than treated as 0.
    """
    platforms = totals.get("platforms", {})
    patterns: list[dict[str, Any]] = []
    for metric, label in METRIC_LABELS_AR.items():
        patterns += _share_patterns(platforms, metric, label)
    for (numerator, denominator), label in RATE_LABELS_AR.items():
        patterns += _rate_patterns(platforms, numerator, denominator, label)
    return patterns


def _load_real_awj_sada(path: Path = AWJ_REAL_DATA_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _awj_pattern(slice_key: str, text: str, metric_line: str, lift: float, n_samples: int) -> dict[str, Any]:
    # Confidence capped well below the synthetic pipeline's ceiling - these
    # are descriptive comparisons over a handful of real records, not
    # t-tested results.
    confidence = round(min(0.75, 0.4 + min(abs(lift), 2.0) / 4 + min(n_samples, 5) * 0.03), 2)
    return {
        "pattern_id": _pattern_id("awj_sada_real", slice_key),
        "pattern": text,
        "supporting_metric": metric_line,
        "confidence": confidence,
        "affected_content_types": [],
        "dimension": "awj_sada_real",
        "slice_key": slice_key,
        "lift_pct": round(lift * 100, 1),
        "source": "real_awj_sada",
    }


def analyze_real_awj_sada(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Descriptive patterns from the real AWJ | Sada podcast/X dataset.

    Only 6 episodes and 5 X posts total - far below MIN_SAMPLES for the
    Welch-t-test pipeline in analyze(), so like analyze_real_hajj_platforms
    this reports plain descriptive comparisons (no significance test) at a
    capped confidence, tagged source="real_awj_sada". A metric that's null
    for a group (e.g. SO's youtube_likes, with 0 episodes reporting it) is
    skipped for that comparison rather than treated as 0.
    """
    patterns: list[dict[str, Any]] = []

    podcasts = data.get("podcasts", {})
    reporting = {
        name: p["avg_youtube_views"]
        for name, p in podcasts.items()
        if p.get("avg_youtube_views") is not None
    }
    if len(reporting) >= 2:
        overall = statistics.mean(reporting.values())
        for name, avg_views in reporting.items():
            if overall == 0:
                continue
            lift = (avg_views - overall) / overall
            if abs(lift) < REAL_AWJ_MIN_LIFT:
                continue
            n = podcasts[name]["youtube_views_reported"]
            direction = "أعلى" if lift > 0 else "أقل"
            text = (
                f"حلقات بودكاست {name} تحقق متوسط مشاهدات يوتيوب {direction} بنسبة "
                f"{abs(lift) * 100:.0f}% عن متوسط البودكاستات المرصودة."
            )
            metric_line = (
                f"{name}: متوسط مشاهدات={avg_views:,.0f} (n={n}) مقابل المتوسط العام "
                f"{overall:,.0f}؛ lift={lift * 100:.1f}%"
            )
            patterns.append(_awj_pattern(f"podcast_youtube_views:{name}", text, metric_line, lift, n))

    by_rel = data.get("x_by_relationship", {})
    official = by_rel.get("official account")
    amplification = by_rel.get("related amplification tagging @Medhalpodcast")
    if official and amplification and official.get("avg_views") and amplification.get("avg_views"):
        lift = (official["avg_views"] - amplification["avg_views"]) / amplification["avg_views"]
        if abs(lift) >= REAL_AWJ_MIN_LIFT:
            direction = "أعلى" if lift > 0 else "أقل"
            text = (
                f"منشورات الحساب الرسمي @Medhalpodcast على X تحقق مشاهدات {direction} بنسبة "
                f"{abs(lift) * 100:.0f}% مقارنةً بمنشورات إعادة النشر من حسابات أخرى."
            )
            metric_line = (
                f"رسمي: متوسط مشاهدات={official['avg_views']:,.0f} (n={official['post_count']}) مقابل "
                f"إعادة نشر: {amplification['avg_views']:,.0f} (n={amplification['post_count']})؛ "
                f"lift={lift * 100:.1f}%"
            )
            n_total = official["post_count"] + amplification["post_count"]
            patterns.append(
                _awj_pattern("x_relationship_views:official_vs_amplification", text, metric_line, lift, n_total)
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
    place instead of duplicating them, per AGENT_SPEC.md's acceptance criteria.
    """
    existing = {p["pattern_id"]: p for p in load_store(store_path)}
    for p in new_patterns:
        existing[p["pattern_id"]] = p
    merged = list(existing.values())
    _write_store(store_path, merged)
    return merged


def run(
    store_path: Path = STORE_PATH,
    real_data_path: Path = REAL_DATA_PATH,
    awj_real_data_path: Path = AWJ_REAL_DATA_PATH,
    real_sba_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Rebuild the pattern store from real data only: SBA's collected posts first,
    then the Hajj 1445 and AWJ | Sada season-level sources. The synthetic MVP seed
    (DATA_PATH, analyze()) is no longer published - the dashboard and the
    optimizer must only ever show real numbers (team.md "Real numbers only").

    The store is replaced, not merged: a pattern that stops being significant on
    fresh data disappears instead of lingering from an older run.

    `real_sba_records` is backend.repository.analysis_records() output - pass
    it explicitly from tests against a seeded database. When omitted, this
    fetches it itself so every caller (startup, POST /api/patterns/refresh)
    gets real patterns without wiring repository through every call site; if
    the database isn't reachable yet (e.g. a fresh environment with nothing
    collected), it degrades to no real patterns rather than failing the run.
    """
    patterns: list[dict[str, Any]] = []

    if real_sba_records is None:
        try:
            from backend import repository

            real_sba_records = repository.analysis_records()
        except Exception:
            real_sba_records = []
    patterns += analyze_real_data(real_sba_records)

    real_totals = _load_real_hajj_totals(real_data_path)
    if real_totals:
        patterns += analyze_real_hajj_platforms(real_totals)

    awj_real = _load_real_awj_sada(awj_real_data_path)
    if awj_real:
        patterns += analyze_real_awj_sada(awj_real)

    unique = list({p["pattern_id"]: p for p in patterns}.values())
    _write_store(store_path, unique)
    return unique


if __name__ == "__main__":
    result = run()
    print(f"Pattern store now has {len(result)} pattern(s).")
    for p in result:
        print(f"- [{p['confidence']}] {p['pattern']}")
