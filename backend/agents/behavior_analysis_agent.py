"""Task 1 - Behavior Analysis Agent.

Detects engagement patterns across content type, topic, timing and platform
from the seeded engagement dataset, and maintains a persistent pattern store
that Tasks 2 and 3 read from. See AGENT_SPEC.md for the full spec.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.topics import TOPICS

logger = logging.getLogger("sada.behavior")

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


# --- Real SBA post statistics -------------------------------------------------
#
# Per-post performance ratios are heavy-tailed (a few viral posts sit at 50-200x
# the account's typical value), so means and plain t-tests are dominated by
# outliers. Real-data slices are therefore tested on log(index) with Welch's
# t-test, the effect is reported as the ratio of medians (what the *typical*
# post in the slice gets vs. the typical post outside it), and because one
# refresh tests dozens of slices, p-values are corrected for multiple
# comparisons (Benjamini-Hochberg, false discovery rate FDR_Q).
FDR_Q = 0.05
INDEX_FLOOR = 0.01  # log() guard for posts that got ~0 of the metric

CONTENT_TYPE_AR = {
    "video": "الفيديو", "short": "المقاطع القصيرة", "live": "البث المباشر",
    "image": "الصور", "carousel": "الألبومات", "text": "المنشورات النصية",
}
TIMING_AR = {
    "weekend": "نهاية الأسبوع",
    "weekday_afternoon_14_17": "عصر أيام الأسبوع (2-5 م)",
    "weekday_evening_18_23": "مساء أيام الأسبوع (6-11 م)",
    "weekday_morning_6_13": "صباح أيام الأسبوع",
}


def _p_value(t_stat: float, a: list[float], b: list[float]) -> float:
    """Two-sided p-value of Welch's t with Welch-Satterthwaite degrees of freedom."""
    from scipy import stats

    va, vb = statistics.variance(a) / len(a), statistics.variance(b) / len(b)
    df = (va + vb) ** 2 / ((va**2) / (len(a) - 1) + (vb**2) / (len(b) - 1)) if va + vb else 1.0
    return float(2 * stats.t.sf(abs(t_stat), df))


def _bh_adjust(p_values: list[float]) -> list[float]:
    """Benjamini-Hochberg adjusted p-values (q-values), same order as the input."""
    m = len(p_values)
    order = sorted(range(m), key=lambda i: p_values[i])
    adjusted = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, p_values[i] * m / rank)
        adjusted[i] = running
    return adjusted


# What each platform's performance_index measures, as the noun a reader sees in a sentence.
METRIC_NOUN_AR = {"youtube": "مشاهدات", "x": "مرات ظهور", "instagram": "إعجابات وتعليقات"}
METRIC_TITLE_AR = {"youtube": "المشاهدات", "x": "مرات الظهور", "instagram": "الإعجابات والتعليقات"}


def _ratio_phrase(ratio: float, noun: str = "أداءً") -> str:
    """'مشاهدات أكثر بـ 53%' / 'مرات ظهور أقل بـ 26%' / 'أداءً أعلى بـ 102% (أي 2.0×)' - no statistics vocabulary."""
    pct = abs(ratio - 1) * 100
    more, less = ("أعلى", "أقل") if noun == "أداءً" else ("أكثر", "أقل")
    phrase = f"{noun} {more if ratio > 1 else less} بـ {pct:.0f}%"
    return f"{phrase} (أي {ratio:.1f}×)" if ratio >= 1.95 else phrase


def _real_candidates(records, dimension, key_fn, index_key, describe_fn, label_fn) -> list[dict[str, Any]]:
    """`label_fn(key)` -> (short title, platform or None, metric title) - what the dashboard shows as the card heading."""
    # Every slice with enough posts on both sides, with its effect and raw p-value (not yet filtered).
    buckets: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        buckets.setdefault(key_fn(r), []).append(r)

    def value(r: dict[str, Any]) -> float:
        return max(r.get(index_key, r["performance_index"]), INDEX_FLOOR)

    out = []
    for key, bucket in buckets.items():
        rest = [r for r in records if key_fn(r) != key]
        if len(bucket) < MIN_SAMPLES or len(rest) < MIN_SAMPLES:
            continue  # not enough evidence for this slice (or its complement)
        a = [math.log(value(r)) for r in bucket]
        b = [math.log(value(r)) for r in rest]
        if statistics.variance(a) == 0 and statistics.variance(b) == 0:
            continue
        t_stat = _welch_t_stat(a, b)
        med_a, med_b = statistics.median(value(r) for r in bucket), statistics.median(value(r) for r in rest)
        out.append({
            "dimension": dimension, "key": key, "n": len(bucket), "n_rest": len(rest), "t": t_stat,
            "p": _p_value(t_stat, a, b) if t_stat else 1.0, "ratio": med_a / med_b, "med_a": med_a, "med_b": med_b,
            "types": sorted({r["content_type"] for r in bucket}), "describe": describe_fn, "label": label_fn(key),
        })
    return out


def _finalize(candidates: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    """Keep slices that survive the FDR correction and are big enough to matter; build pattern dicts."""
    if not candidates:
        return []
    q_values = _bh_adjust([c["p"] for _, c in candidates])
    patterns = []
    for (source, c), q in zip(candidates, q_values):
        lift = c["ratio"] - 1
        if q > FDR_Q or abs(lift) < MIN_LIFT:
            continue
        patterns.append({
            # The same dimension/slice exists once per platform (e.g. "video" on YouTube and on X):
            # the source keeps their ids apart so one never overwrites the other.
            "pattern_id": _pattern_id(c["dimension"], f"{source}:{c['key']}"),
            "pattern": c["describe"](c["key"], c["ratio"]),
            "supporting_metric": (
                f"المنشور المعتاد هنا يحقق {c['med_a']:.2f}× من المعتاد لحسابه، مقابل {c['med_b']:.2f}× لبقية المنشورات · "
                f"مبني على {c['n']} منشوراً مقابل {c['n_rest']} · احتمال أن يكون الفرق صدفة q={q:.2g} "
                f"(بعد تصحيح المقارنات المتعددة؛ Welch t={c['t']:.1f} على المقياس اللوغاريتمي)"
            ),
            "confidence": round(min(0.99, 1 - q), 2),
            "affected_content_types": c["types"],
            "dimension": c["dimension"],
            "slice_key": c["key"],
            "lift_pct": round(lift * 100, 1),
            "sample_size": c["n"],
            "q_value": round(q, 6),
            "typical_ratio": round(c["ratio"], 3),
            "source": source,
            "title": c["label"][0],
            "platform": c["label"][1],
            "metric_ar": c["label"][2],
            "n_rest": c["n_rest"],
        })
    return patterns


def analyze_real_data(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Patterns from real SBA posts (YouTube, Instagram, X).

    `records` is backend.repository.analysis_records() output. Two indices are used:
    - `account_index` (post / its account's typical post, any content type) for content-type
      comparisons - the per-content-type `performance_index` is 1.0 at every type's median
      by construction, so it can't tell content types apart.
    - `performance_index` (post / account+content-type typical) for timing, topic and
      account-topic slices, so a slice isn't "good" just because it is mostly video.
    Each platform is sliced separately; one cross-platform pass compares content types
    across platforms. All candidate slices of one run share one FDR correction.
    """
    if not records:
        return []
    candidates: list[tuple[str, dict[str, Any]]] = []

    for platform in ("youtube", "instagram", "x"):
        rows = [r for r in records if r["platform"] == platform]
        if not rows:
            continue
        on = f"على {PLATFORM_LABELS_AR.get(platform, platform)}"
        noun, metric = METRIC_NOUN_AR[platform], METRIC_TITLE_AR[platform]
        names = {r["entity_key"]: r["channel_name_ar"] for r in rows}
        source = f"real_{platform}_sba"

        def channel_topic(k: str, names=names) -> tuple[str, str]:
            entity, topic = k.split("|")
            return names.get(entity, entity), TOPICS.get(topic, topic)

        found = _real_candidates(
            rows, "content_type_real", lambda r: r["content_type"], "account_index",
            lambda k, ratio, on=on, noun=noun: (
                f"منشورات {CONTENT_TYPE_AR.get(k, k)} {on} تحصل عادةً على {_ratio_phrase(ratio, noun)} "
                f"من بقية أنواع المحتوى في نفس الحسابات."
            ),
            lambda k, platform=platform, metric=metric: (CONTENT_TYPE_AR.get(k, k), platform, metric),
        )
        found += _real_candidates(
            rows, "timing_real", lambda r: hour_bucket(r["day_of_week"], r["publish_hour"]), "performance_index",
            lambda k, ratio, on=on, noun=noun: (
                f"المنشورات في {TIMING_AR.get(k, k)} {on} تحصل عادةً على {_ratio_phrase(ratio, noun)} "
                f"من المنشورات في بقية الأوقات (مقارنةً بالمعتاد لكل حساب)."
            ),
            lambda k, platform=platform, metric=metric: (TIMING_AR.get(k, k), platform, metric),
        )
        found += _real_candidates(
            rows, "topic_real", lambda r: r["topic"], "performance_index",
            lambda k, ratio, on=on, noun=noun: (
                f"منشورات «{TOPICS.get(k, k)}» {on} تحصل عادةً على {_ratio_phrase(ratio, noun)} "
                f"من منشورات بقية المواضيع (مقارنةً بالمعتاد لكل حساب)."
            ),
            lambda k, platform=platform, metric=metric: (f"«{TOPICS.get(k, k)}»", platform, metric),
        )
        found += _real_candidates(
            rows, "channel_topic_real", lambda r: f"{r['entity_key']}|{r['topic']}", "performance_index",
            lambda k, ratio, on=on, noun=noun, ct=channel_topic: (
                f"منشورات {ct(k)[0]} {on} عن «{ct(k)[1]}» تحصل عادةً على {_ratio_phrase(ratio, noun)} "
                f"من المنشور المعتاد للحساب نفسه."
            ),
            lambda k, platform=platform, metric=metric, ct=channel_topic: (f"{ct(k)[0]} · {ct(k)[1]}", platform, metric),
        )
        candidates += [(source, c) for c in found]

    if len({r["platform"] for r in records}) >= 2:
        cross = _real_candidates(
            records, "platform_content_real", lambda r: f"{r['platform']}|{r['content_type']}", "account_index",
            lambda k, ratio: (
                f"منشورات {CONTENT_TYPE_AR.get(k.split('|')[1], k.split('|')[1])} على {PLATFORM_LABELS_AR.get(k.split('|')[0], k.split('|')[0])} "
                f"تحقق عادةً {_ratio_phrase(ratio)} من بقية المحتوى على كل المنصات (مقارنةً بالمعتاد لكل حساب)."
            ),
            lambda k: (CONTENT_TYPE_AR.get(k.split("|")[1], k.split("|")[1]), k.split("|")[0], "الأداء مقارنةً بالمعتاد للحساب"),
        )
        candidates += [("real_sba", c) for c in cross]

    return _finalize(candidates)


def _load_real_hajj_totals(path: Path = REAL_DATA_PATH) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


METRIC_LABELS_AR = {"impressions": "مرات الظهور", "views": "المشاهدات"}
# Platform names in this source (meta/tiktok aren't collected per post, so they aren't in PLATFORM_LABELS_AR).
HAJJ_PLATFORM_AR = {"youtube": "يوتيوب", "x": "إكس", "meta": "ميتا (فيسبوك وإنستغرام)", "tiktok": "تيك توك"}
RATE_LABELS_AR = {
    ("engagement", "views"): "التفاعل لكل مشاهدة",
    ("engagement", "impressions"): "التفاعل لكل ظهور",
}


def _real_pattern(
    slice_key: str, text: str, metric_line: str, lift: float, n_reporting: int, title: str, platform: str,
    share_pct: float | None = None,
) -> dict[str, Any]:
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
        "title": title,
        "platform": platform,
        "share_pct": share_pct,
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
        name = HAJJ_PLATFORM_AR.get(platform, platform)
        text = (
            f"خلال موسم حج 1445هـ جاءت {share * 100:.{0 if share >= 0.1 else 1}f}% من {label_ar} عبر {name}، "
            f"من بين {len(reporting)} منصات (لو توزعت بالتساوي لكان نصيب كل منصة {baseline_share * 100:.0f}%)."
        )
        metric_line = (
            f"{name}: {value:,.0f} من إجمالي {total:,.0f} بين {len(reporting)} منصات "
            f"({'، '.join(HAJJ_PLATFORM_AR.get(p, p) for p in sorted(reporting))}) · الحصة {share * 100:.1f}%"
        )
        out.append(_real_pattern(
            f"{metric}:{platform}", text, metric_line, lift, len(reporting),
            title=f"{name} · حصة {label_ar}", platform=platform, share_pct=round(share * 100, 1),
        ))
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
        name = HAJJ_PLATFORM_AR.get(platform, platform)
        text = (
            f"خلال موسم حج 1445هـ كان معدل {label_ar} على {name} {rate * 100:.2f}%، "
            f"مقابل {others_mean * 100:.2f}% في المتوسط على المنصات الأخرى"
            + (f"، أي {1 + lift:.1f}× ما تحققه." if lift >= 0.95 else f"، أي {'أعلى' if lift > 0 else 'أقل'} بـ {abs(lift) * 100:.0f}%.")
        )
        metric_line = (
            f"{name}: {label_ar} = {rate * 100:.2f}% مقابل متوسط بقية المنصات {others_mean * 100:.2f}% "
            f"(الفرق {lift * 100:+.0f}%) · مقارنة بين {len(rates)} منصات تُبلغ عن الرقمين"
        )
        out.append(_real_pattern(
            f"{numerator}_per_{denominator}:{platform}", text, metric_line, lift, len(rates),
            title=f"{name} · معدل {label_ar}", platform=platform,
        ))
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


def _awj_pattern(slice_key: str, text: str, metric_line: str, lift: float, n_samples: int, title: str, platform: str) -> dict[str, Any]:
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
        "sample_size": n_samples,
        "title": title,
        "platform": platform,
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
            text = (
                f"حلقات بودكاست {name} تحصل في المتوسط على {_ratio_phrase(1 + lift, 'مشاهدات')} على يوتيوب "
                f"من متوسط بودكاستات أوج | صدى المرصودة."
            )
            metric_line = (
                f"{name}: متوسط مشاهدات={avg_views:,.0f} (n={n}) مقابل المتوسط العام "
                f"{overall:,.0f}؛ lift={lift * 100:.1f}%"
            )
            patterns.append(_awj_pattern(
                f"podcast_youtube_views:{name}", text, metric_line, lift, n, title=f"بودكاست {name}", platform="youtube",
            ))

    by_rel = data.get("x_by_relationship", {})
    official = by_rel.get("official account")
    amplification = by_rel.get("related amplification tagging @Medhalpodcast")
    if official and amplification and official.get("avg_views") and amplification.get("avg_views"):
        lift = (official["avg_views"] - amplification["avg_views"]) / amplification["avg_views"]
        if abs(lift) >= REAL_AWJ_MIN_LIFT:
            text = (
                f"منشورات الحساب الرسمي @Medhalpodcast على إكس تحصل في المتوسط على {_ratio_phrase(1 + lift, 'مشاهدات')} "
                f"من منشورات الحسابات الأخرى التي تعيد نشر البودكاست."
            )
            metric_line = (
                f"رسمي: متوسط مشاهدات={official['avg_views']:,.0f} (n={official['post_count']}) مقابل "
                f"إعادة نشر: {amplification['avg_views']:,.0f} (n={amplification['post_count']})؛ "
                f"lift={lift * 100:.1f}%"
            )
            n_total = official["post_count"] + amplification["post_count"]
            patterns.append(
                _awj_pattern(
                    "x_relationship_views:official_vs_amplification", text, metric_line, lift, n_total,
                    title="الحساب الرسمي مقابل إعادة النشر", platform="x",
                )
            )

    return patterns


def load_store(store_path: Path = STORE_PATH) -> list[dict[str, Any]]:
    """The persisted patterns; an unreadable or corrupt store reads as empty instead of failing every caller."""
    try:
        patterns = json.loads(store_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        logger.exception("Pattern store %s is unreadable - treating it as empty", store_path)
        return []
    return patterns if isinstance(patterns, list) else []


def _write_store(store_path: Path, patterns: list[dict[str, Any]]) -> None:
    """Write to a temp file and swap it in, so a concurrent reader never sees a half-written store."""
    store_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = store_path.with_name(f"{store_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(patterns, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, store_path)


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
    computed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for p in unique:
        p["computed_at"] = computed_at  # lets the dashboard say how fresh the store is
    _write_store(store_path, unique)
    return unique


if __name__ == "__main__":
    result = run()
    print(f"Pattern store now has {len(result)} pattern(s).")
    for p in result:
        print(f"- [{p['confidence']}] {p['pattern']}")
