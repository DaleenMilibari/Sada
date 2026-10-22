"""Alerts & Diagnosis Agent: find the posts that left their normal range, then explain why.

One agent, two steps that run at different costs:

1. Detect (every Alerts load, pure statistics, cached 60 s) - `alerts()` / `detect()`.
   - Level: a post's main metric (views on YouTube and X, likes + comments on Instagram) vs the
     typical value of its peers (same platform + account + content type) AT THE SAME AGE.
     "same_age" interpolates the peers' snapshots at that age; "plateau" compares posts at least
     PLATEAU_AGE_DAYS old on current values, since by then most engagement has accumulated.
     Younger posts without bracketing snapshots are NOT guessed at.
   - Velocity: metric per hour between the latest two snapshots vs the interval before them -
     a post that suddenly takes off, or stalls.
   ratio >= SPIKE_RATIO is a spike, ratio <= DROP_RATIO a drop. Too few peers or a tiny expected
   value means no alert (insufficient evidence), never a guess.

2. Diagnose (on click, the LLM only words the result) - `diagnose_video()`.
   Root causes the team controls (root_cause.py: burst, crowding, timing, format) come first,
   then a comparison with comparable real posts retrieved from the database. Every factor is
   built from real records *before* the LLM is called, so it can't invent a metric or source.
   The MVP endpoints (`run()` on synthetic history, `diagnose_awj_topic()` on the AWJ | Sada
   package) use the same grounding. See AGENT_SPEC.md for the full spec.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from backend import db, repository
from backend.agents import behavior_analysis_agent, llm_client

# ---------------------------------------------------------------------------
# Step 1 - detect spikes and drops
# ---------------------------------------------------------------------------

SPIKE_RATIO = 3.0
DROP_RATIO = 0.33
HIGH_SPIKE_RATIO = 6.0
HIGH_DROP_RATIO = 0.15

MIN_PEERS = 5
MIN_AGE_HOURS = 6.0  # younger posts are too noisy to judge
PLATEAU_AGE_DAYS = 7.0
MIN_EXPECTED = {"views": 100, "interactions": 10}  # tiny baselines make any ratio meaningless
MIN_VELOCITY_EXPECTED = {"views": 5.0, "interactions": 0.5}  # per hour
MIN_VELOCITY_INTERVAL_H = 1.0
MAX_ALERTS = 60
CACHE_TTL_SECONDS = 60

_cache: dict[int, tuple[float, list[dict[str, Any]]]] = {}
_lock = threading.Lock()

Series = list[tuple[float, int]]  # (age in hours, metric value), ascending


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _metric(platform: str) -> str:
    return "views" if platform in ("youtube", "x") else "interactions"  # X: impressions


def _primary(platform: str, views, likes, comments) -> int | None:
    if platform in ("youtube", "x"):
        return views
    parts = [x for x in (likes, comments) if x is not None]
    return sum(parts) if parts else None


def value_at_age(series: Series, age_h: float) -> float | None:
    """Linear interpolation between the snapshots bracketing `age_h`; None if they don't (no extrapolation)."""
    before = after = None
    for point in series:
        if point[0] <= age_h:
            before = point
        else:
            after = point
            break
    if before is None or after is None:
        return None
    if after[0] - before[0] > max(2.0, 0.5 * age_h):  # too coarse a gap to trust
        return None
    (a0, v0), (a1, v1) = before, after
    return v0 + (v1 - v0) * (age_h - a0) / (a1 - a0)


def _severity(kind: str, ratio: float) -> str:
    if kind == "spike":
        return "high" if ratio >= HIGH_SPIKE_RATIO else "medium"
    return "high" if ratio <= HIGH_DROP_RATIO else "medium"


def _deviation(ratio: float) -> float:
    """How far from normal, in either direction: 3x and 1/3x rank the same; a full stall ranks highest."""
    return max(ratio, 1 / ratio) if ratio > 0 else math.inf


def _classify(ratio: float) -> str | None:
    if ratio >= SPIKE_RATIO:
        return "spike"
    if ratio <= DROP_RATIO:
        return "drop"
    return None


def _load(conn, days: int, now: datetime) -> tuple[dict[str, dict[str, Any]], dict[str, list[tuple[datetime, Any, Any, Any]]]]:
    """Posts published within the peer window (analysis window + the plateau lookback) and their snapshots."""
    v, c, s = db.videos.c, db.channels.c, db.video_snapshots.c
    since = now - timedelta(days=max(days, 60))
    posts = {
        r.video_id: repository._video_dict(r)
        for r in conn.execute(
            select(*repository._video_columns()).join(db.channels, v.channel_id == c.channel_id).where(v.published_at >= since)
        )
    }
    snaps: dict[str, list[tuple[datetime, Any, Any, Any]]] = {}
    for vid, at, views, likes, comments in conn.execute(
        select(s.video_id, s.captured_at, s.view_count, s.like_count, s.comment_count)
        .join(db.videos, v.video_id == s.video_id)
        .where(v.published_at >= since)
        .order_by(s.video_id, s.captured_at)
    ):
        snaps.setdefault(vid, []).append((db.as_utc(at), views, likes, comments))
    return posts, snaps


def _series(post: dict[str, Any], snaps: list[tuple[datetime, Any, Any, Any]]) -> Series:
    out: Series = []
    for at, views, likes, comments in snaps:
        value = _primary(post["platform"], views, likes, comments)
        age = (at - post["published_at"]).total_seconds() / 3600
        if value is not None and age >= 0:
            out.append((age, int(value)))
    return out


def _alert(post, kind, metric, observed, expected, ratio, detection, basis, peers, detected_at, explanation) -> dict[str, Any]:
    return {
        "alert_id": f"{detection}:{kind}:{post['video_id']}",
        "kind": kind,
        "video": post,
        "metric": metric,
        "observed": int(round(observed)),
        "expected": int(round(expected)),
        "ratio": round(ratio, 2),
        "severity": _severity(kind, ratio),
        "detected_at": detected_at,
        "detection": detection,
        "basis": basis,
        "peers": peers,
        "explanation": explanation,
    }


def detect(days: int = 7, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or db.utcnow()
    with db.get_engine().connect() as conn:
        posts, snaps = _load(conn, days, now)

    series = {vid: _series(posts[vid], rows) for vid, rows in snaps.items() if vid in posts}
    peer_groups: dict[tuple[str, str, str], list[str]] = {}
    for vid, p in posts.items():
        peer_groups.setdefault((p["platform"], p["entity_key"], p["content_type"]), []).append(vid)

    def current(vid: str) -> tuple[float, int] | None:
        """Latest (age_h, value): newest snapshot, else the stored counts."""
        if series.get(vid):
            return series[vid][-1]
        p = posts[vid]
        value = _primary(p["platform"], p["view_count"], p["like_count"], p["comment_count"])
        stamp = p["stats_updated_at"]
        if value is None or stamp is None:
            return None
        return (stamp - p["published_at"]).total_seconds() / 3600, int(value)

    alerts: list[dict[str, Any]] = []
    for vid, post in posts.items():
        age_days = (now - post["published_at"]).total_seconds() / 86400
        if age_days > days:
            continue
        metric = _metric(post["platform"])
        peers = [x for x in peer_groups[(post["platform"], post["entity_key"], post["content_type"])] if x != vid]
        cur = current(vid)
        if cur is None or cur[0] < MIN_AGE_HOURS:
            continue
        age_h, observed = cur
        detected_at = post["stats_updated_at"] or now

        # --- level detection ---
        level = None
        expected_vals = [x for x in (value_at_age(series.get(p, []), age_h) for p in peers) if x is not None]
        if len(expected_vals) >= MIN_PEERS:
            level = ("same_age", statistics.median(expected_vals), len(expected_vals))
        elif age_h / 24 >= PLATEAU_AGE_DAYS:
            plateau = [
                cur_p[1]
                for p in peers
                if (cur_p := current(p)) is not None and cur_p[0] / 24 >= PLATEAU_AGE_DAYS
            ]
            if len(plateau) >= MIN_PEERS:
                level = ("plateau", statistics.median(plateau), len(plateau))
        if level and level[1] >= MIN_EXPECTED[metric]:
            basis, expected, n = level
            ratio = observed / expected
            kind = _classify(ratio)
            if kind:
                what = {"youtube": "المشاهدات", "x": "مرات الظهور"}.get(post["platform"], "التفاعل (إعجابات + تعليقات)")
                where = "عند نفس العمر" if basis == "same_age" else "لمنشورات بعمر ٧ أيام فأكثر"
                alerts.append(_alert(
                    post, kind, metric, observed, expected, ratio, "level", basis, n, detected_at,
                    f"{what} {observed:,} مقابل المعتاد {round(expected):,} {where} "
                    f"لنفس الحساب ونوع المحتوى (n={n}) — {ratio:.1f}×.",
                ))
                continue  # one alert per post; the level alert already says it

        # --- velocity detection (needs three snapshots) ---
        pts = series.get(vid, [])
        if len(pts) >= 3 and age_days <= PLATEAU_AGE_DAYS:
            (a0, v0), (a1, v1), (a2, v2) = pts[-3:]
            if a2 - a1 >= MIN_VELOCITY_INTERVAL_H and a1 - a0 >= MIN_VELOCITY_INTERVAL_H:
                # Platforms sometimes correct counts downward (removed spam views): a negative rate is a stall.
                prev, recent = (v1 - v0) / (a1 - a0), max(0.0, (v2 - v1) / (a2 - a1))
                if prev >= MIN_VELOCITY_EXPECTED[metric]:
                    ratio = recent / prev
                    kind = _classify(ratio)
                    if kind:
                        verb = "تسارع" if kind == "spike" else "تباطأ"
                        alerts.append(_alert(
                            post, kind, metric, recent, prev, ratio, "velocity", "snapshots", len(pts), detected_at,
                            f"{verb} نمو {'مرات الظهور' if post['platform'] == 'x' else 'المشاهدات' if metric == 'views' else 'التفاعل'} فجأة: "
                            f"{recent:,.1f}/ساعة بعد {prev:,.1f}/ساعة في القياس السابق ({ratio:.1f}×).",
                        ))

    alerts.sort(key=lambda a: (a["severity"] != "high", -_deviation(a["ratio"])))
    return alerts[:MAX_ALERTS]


def alerts(days: int = 7) -> list[dict[str, Any]]:
    """Cached for CACHE_TTL_SECONDS per window."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(days)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    result = detect(days)
    with _lock:
        _cache[days] = (now, result)
    return result


# ---------------------------------------------------------------------------
# Step 2 - diagnose: why a post over- or under-performed, and what to do
#
# Step 2a below is the MVP diagnosis of a content item against synthetic history and the
# pattern store; step 2b diagnoses a real collected post.
# ---------------------------------------------------------------------------

HISTORY_PATH = Path(__file__).parent.parent / "data" / "content_history.json"
AWJ_RAW_PATH = Path(__file__).parent.parent / "data" / "raw" / "awj_sada_data.json"

MIN_COMPARABLE = 4  # below this, retrieval falls back to a broader match; below MIN_COMPARABLE_FLOOR it gives up
MIN_COMPARABLE_FLOOR = 2


def _parse_llm_reply(raw_text: str) -> dict[str, Any]:
    """The model's JSON reply, checked: a non-empty "diagnosis" string and a list of recommendation strings.

    Raises ValueError on anything else, so callers fall back to evidence-only wording
    instead of showing a malformed answer (e.g. a recommendations string split into letters).
    """
    parsed = json.loads(raw_text)
    if not isinstance(parsed, dict):
        raise ValueError("LLM reply is not a JSON object")
    diagnosis = parsed.get("diagnosis")
    recs = parsed.get("recommendations")
    if isinstance(recs, str):
        recs = [recs]
    if not isinstance(diagnosis, str) or not diagnosis.strip() or not isinstance(recs, list):
        raise ValueError("LLM reply is missing diagnosis/recommendations")
    parsed["diagnosis"] = diagnosis.strip()
    parsed["recommendations"] = [str(r).strip() for r in recs if str(r).strip()][:3]
    return parsed


def _evidence_only(factors: list[dict[str, Any]], head: str | None = None) -> tuple[str, list[str]]:
    """Wording built only from the factors themselves, used when the LLM is unavailable."""
    reasons = [f["reason"] for f in factors[:3]]
    text = " ".join([head, *reasons] if head else reasons)
    recs = [f["recommendation"] for f in factors if f.get("recommendation")]
    return text, recs or ["راجع العوامل والأدلة المرفقة أدناه قبل نشر محتوى مشابه."]


def _load_history(path: Path = HISTORY_PATH) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def retrieve_comparable(item: dict[str, Any], history: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Deterministic metadata retrieval, narrowest match first."""
    same_topic = [h for h in history if h["topic"] == item["topic"] and h["content_id"] != item["content_id"]]
    if len(same_topic) >= MIN_COMPARABLE:
        return same_topic, "topic"

    same_type = [
        h
        for h in history
        if h["content_type"] == item["content_type"] and h["content_id"] != item["content_id"]
    ]
    if len(same_type) >= MIN_COMPARABLE:
        return same_type, "content_type"

    broadest = same_topic or same_type
    if len(broadest) >= MIN_COMPARABLE_FLOOR:
        return broadest, "topic" if same_topic else "content_type"

    return [], "none"


def _matching_patterns_for_item(item: dict[str, Any], patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    time_window = behavior_analysis_agent.hour_bucket(item.get("day_of_week", "mon"), item["publish_hour"])
    matched = []
    for p in patterns:
        if p["dimension"] == "content_type" and p["slice_key"] == item["content_type"]:
            matched.append(p)
        elif p["dimension"] == "timing" and p["slice_key"] == time_window:
            matched.append(p)
        elif p["dimension"] == "topic_platform" and p["slice_key"] == f"{item['topic']}|{item['platform']}":
            matched.append(p)
    return matched


def build_diagnosis_context(
    item: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Pure, deterministic retrieval + factor construction - no LLM call.

    Kept separate from synthesize/diagnose so it's fully testable without
    an API key, and so every fact handed to the LLM is traceable.
    """
    history = _load_history() if history is None else history
    patterns = behavior_analysis_agent.load_store() if patterns is None else patterns

    comparable, match_basis = retrieve_comparable(item, history)
    item_score = behavior_analysis_agent.engagement_score(item)

    if not comparable:
        return {
            "item": item,
            "item_score": item_score,
            "comparable": [],
            "baseline_mean": None,
            "delta_pct": None,
            "factors": [],
            "low_confidence": True,
        }

    comparable_scores = [behavior_analysis_agent.engagement_score(c) for c in comparable]
    baseline_mean = sum(comparable_scores) / len(comparable_scores)
    delta_pct = (item_score - baseline_mean) / baseline_mean * 100 if baseline_mean else 0.0
    direction = "أعلى" if delta_pct >= 0 else "أقل"

    factors: list[dict[str, Any]] = [
        {
            "reason": (
                f"أداء المنشور {direction} من متوسط المحتوى المشابه "
                f"({'نفس الموضوع' if match_basis == 'topic' else 'نفس نوع المحتوى'}) بنسبة {abs(delta_pct):.0f}%."
            ),
            "supporting_metric": (
                f"مؤشر تفاعل {item_score:.2f} مقابل متوسط مقارن {baseline_mean:.2f} (n={len(comparable)})"
            ),
            "evidence_source_title": "أرشيف المحتوى المشابه",
            "evidence_url_or_ref": "internal://archive/comparable_set",
            "confidence": round(min(0.95, 0.4 + min(len(comparable), 20) / 40), 2),
        }
    ]

    most_similar = min(
        comparable,
        key=lambda c: abs(behavior_analysis_agent.engagement_score(c) - item_score),
    )
    factors.append(
        {
            "reason": f"مقارنة مباشرة مع منشور مشابه بعنوان ‘{most_similar['title']}’.",
            "supporting_metric": (
                f"مؤشر تفاعل {behavior_analysis_agent.engagement_score(most_similar):.2f} "
                f"(views={most_similar['views']}, likes={most_similar['likes']}, shares={most_similar['shares']})"
            ),
            "evidence_source_title": most_similar["title"],
            "evidence_url_or_ref": most_similar["url_or_ref"],
            "confidence": 0.6,
        }
    )

    for p in _matching_patterns_for_item(item, patterns):
        factors.append(
            {
                "reason": p["pattern"],
                "supporting_metric": p["supporting_metric"],
                "evidence_source_title": "مخزن الأنماط المشترك (الوكيل الأول)",
                "evidence_url_or_ref": f"pattern://{p['pattern_id']}",
                "confidence": p["confidence"],
            }
        )

    return {
        "item": item,
        "item_score": item_score,
        "comparable": comparable,
        "baseline_mean": baseline_mean,
        "delta_pct": delta_pct,
        "factors": factors,
        "low_confidence": False,
    }


def _synthesize_via_llm(context: dict[str, Any]) -> tuple[str, list[str], list[int]]:
    item = context["item"]
    factors_desc = "\n".join(
        f"{i}. {f['reason']} | المقياس: {f['supporting_metric']} | الثقة: {f['confidence']}"
        for i, f in enumerate(context["factors"])
    )
    prompt = (
        "أنت محلل أداء محتوى لمنصة إعلامية عربية اسمها صدى. لديك منشور بعنوان "
        f"‘{item.get('title', item.get('content_id'))}’ انحرف أداؤه عن المتوقع بنسبة "
        f"{context['delta_pct']:.0f}% عن المحتوى المشابه.\n\n"
        f"العوامل المحتملة المستخرجة من البيانات الفعلية (لا تُضِف أي عامل أو رقم من عندك):\n{factors_desc}\n\n"
        "أعد فقط كائن JSON بالمفاتيح التالية:\n"
        '- "diagnosis": فقرة عربية قصيرة (2-3 جمل) تلخص السبب الأرجح، مبنية فقط على العوامل أعلاه.\n'
        '- "factor_order": قائمة بأرقام العوامل (0-based) مرتبة من الأكثر إلى الأقل تأثيراً.\n'
        '- "recommendations": قائمة من 2-3 توصيات عملية قصيرة مبنية على العوامل.\n'
    )
    parsed = _parse_llm_reply(llm_client.generate_json(prompt))
    order = parsed.get("factor_order")
    order = [int(i) for i in order if isinstance(i, (int, str)) and str(i).lstrip("-").isdigit()] if isinstance(order, list) else []
    return parsed["diagnosis"], parsed["recommendations"], order


def diagnose(
    item: dict[str, Any],
    history: list[dict[str, Any]] | None = None,
    patterns: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    context = build_diagnosis_context(item, history, patterns)

    if context["low_confidence"]:
        return {
            "diagnosis": "لا تتوفر بيانات كافية عن محتوى مشابه لتقديم تشخيص موثوق لهذا المنشور.",
            "contributing_factors": [],
            "recommendations": ["جمع المزيد من بيانات الأداء لمحتوى مشابه قبل إجراء تشخيص دقيق."],
            "low_confidence": True,
        }

    try:
        diagnosis_text, recommendations, factor_order = _synthesize_via_llm(context)
    except Exception:  # no key / model error / malformed reply: evidence-only wording
        diagnosis_text, recommendations = _evidence_only(context["factors"])
        factor_order = []
    ordered_factors = [context["factors"][i] for i in factor_order if 0 <= i < len(context["factors"])]
    if not ordered_factors:
        ordered_factors = context["factors"]

    return {
        "diagnosis": diagnosis_text,
        "contributing_factors": ordered_factors,
        "recommendations": recommendations,
        "low_confidence": False,
    }


def run(item: dict[str, Any]) -> dict[str, Any]:
    return diagnose(item)


# ---------------------------------------------------------------------------
# Real-data diagnosis: AWJ | Sada podcast/X dataset (backend/data/raw/awj_sada_data.json)
#
# Unlike diagnose() above, this doesn't match a submitted item against the
# synthetic content_history.json - a real AWJ episode's topic/content_type
# never matches that synthetic taxonomy, so it would always fall through to
# low_confidence. Instead this explains one of the real, already-computed
# awj_sada_real patterns (behavior_analysis_agent.analyze_real_awj_sada),
# grounded in the individual real episode/post records behind it. A generic
# synthetic pattern is added as one extra, clearly-labeled contextual factor
# when useful - never blended into or presented as part of the real numbers.
# ---------------------------------------------------------------------------

AWJ_TOPIC_LABELS = {
    "podcast_reach": "أداء حلقات رهان مقارنةً بحلقات SO على يوتيوب",
    "x_relationship": "تفاعل منشورات الحساب الرسمي @Medhalpodcast مقارنةً بمنشورات إعادة النشر على X",
}


def _load_awj_raw(path: Path = AWJ_RAW_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _demo_context_factor(patterns: list[dict[str, Any]]) -> dict[str, Any] | None:
    """One generic synthetic pattern added as broader context, capped low and
    labeled as demo data so it's never mistaken for a real AWJ | Sada number."""
    demo = next(
        (p for p in patterns if p["source"] == "synthetic_seed_engagement_records" and p["dimension"] == "content_type" and p["slice_key"] == "video"),
        None,
    )
    if demo is None:
        return None
    return {
        "reason": f"للسياق العام فقط (بيانات تجريبية موسّعة، وليست جزءاً من بيانات أوج | صدى الحقيقية): {demo['pattern']}",
        "supporting_metric": demo["supporting_metric"],
        "evidence_source_title": "بيانات تجريبية (خط أساس عام لأنواع المحتوى)",
        "evidence_url_or_ref": f"pattern://{demo['pattern_id']}",
        "confidence": round(min(demo["confidence"], 0.5), 2),
    }


def build_awj_diagnosis_context(
    topic: str,
    patterns: list[dict[str, Any]] | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure, deterministic factor construction over real AWJ | Sada records - no LLM call."""
    patterns = behavior_analysis_agent.load_store() if patterns is None else patterns
    raw = _load_awj_raw() if raw is None else raw
    awj_patterns = [p for p in patterns if p["source"] == "real_awj_sada"]

    factors: list[dict[str, Any]] = []

    if topic == "podcast_reach":
        for p in awj_patterns:
            if p["slice_key"].startswith("podcast_youtube_views"):
                factors.append(
                    {
                        "reason": p["pattern"],
                        "supporting_metric": p["supporting_metric"],
                        "evidence_source_title": "بيانات أوج | صدى الحقيقية (حلقات يوتيوب)",
                        "evidence_url_or_ref": f"pattern://{p['pattern_id']}",
                        "confidence": p["confidence"],
                    }
                )
        for ep in raw.get("episodes", []):
            views, likes = ep.get("youtube_views"), ep.get("youtube_likes")
            has_data = views is not None
            factors.append(
                {
                    "reason": (
                        f"حلقة «{ep['episode_title']}» ({ep['podcast']}) - "
                        + ("مشاهدات يوتيوب موثقة علنياً." if has_data else "لا تتوفر بيانات مشاهدات يوتيوب علنية لهذه الحلقة.")
                    ),
                    "supporting_metric": (
                        f"views={views:,}" if has_data else "غير متاح"
                    ) + (f", likes={likes:,}" if likes is not None else ""),
                    "evidence_source_title": ep["episode_title"],
                    "evidence_url_or_ref": ep.get("youtube_url") or ep.get("apple_url") or "",
                    "confidence": 0.9 if has_data else 0.3,
                }
            )
    elif topic == "x_relationship":
        for p in awj_patterns:
            if p["slice_key"].startswith("x_relationship_views"):
                factors.append(
                    {
                        "reason": p["pattern"],
                        "supporting_metric": p["supporting_metric"],
                        "evidence_source_title": "بيانات أوج | صدى الحقيقية (منشورات X)",
                        "evidence_url_or_ref": f"pattern://{p['pattern_id']}",
                        "confidence": p["confidence"],
                    }
                )
        for post in raw.get("x_posts", []):
            factors.append(
                {
                    "reason": f"منشور من {post['source_account']} ({post['relationship']}).",
                    "supporting_metric": (
                        f"views={post.get('views', 'غير متاح')}, likes={post.get('likes', 'غير متاح')}, "
                        f"reposts={post.get('reposts', 'غير متاح')}"
                    ),
                    "evidence_source_title": post["source_account"],
                    "evidence_url_or_ref": post.get("source_url", ""),
                    "confidence": 0.85 if post.get("verification_level") == "VERIFIED_PUBLIC" else 0.6,
                }
            )
    else:
        raise ValueError(f"Unknown AWJ diagnosis topic: {topic}")

    if not factors:
        return {"item_label": AWJ_TOPIC_LABELS.get(topic, topic), "factors": [], "low_confidence": True}

    demo_factor = _demo_context_factor(patterns)
    if demo_factor is not None:
        factors.append(demo_factor)

    return {"item_label": AWJ_TOPIC_LABELS.get(topic, topic), "factors": factors, "low_confidence": False}


def _synthesize_awj_via_llm(item_label: str, factors: list[dict[str, Any]]) -> tuple[str, list[str]]:
    factors_desc = "\n".join(
        f"{i}. {f['reason']} | المقياس: {f['supporting_metric']} | الثقة: {f['confidence']}"
        for i, f in enumerate(factors)
    )
    prompt = (
        "أنت محلل أداء محتوى لمنصة إعلامية عربية اسمها صدى. اشرح التالي بالاستناد حصراً إلى "
        f"العوامل أدناه: {item_label}.\n\n"
        f"العوامل المستخرجة من البيانات الفعلية (لا تُضِف أي عامل أو رقم من عندك، ونوّه بوضوح "
        f"متى كان عامل من 'بيانات تجريبية' وليس من بيانات أوج | صدى الحقيقية):\n{factors_desc}\n\n"
        "أعد فقط كائن JSON بالمفاتيح التالية:\n"
        '- "diagnosis": فقرة عربية قصيرة (2-4 جمل) تلخص السبب الأرجح، مبنية فقط على العوامل أعلاه.\n'
        '- "recommendations": قائمة من 2-3 توصيات عملية قصيرة مبنية على العوامل.\n'
    )
    parsed = _parse_llm_reply(llm_client.generate_json(prompt))
    return parsed["diagnosis"], parsed["recommendations"]


def diagnose_awj_topic(
    topic: str,
    patterns: list[dict[str, Any]] | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = build_awj_diagnosis_context(topic, patterns, raw)

    if context["low_confidence"]:
        return {
            "diagnosis": "لا تتوفر بيانات كافية في مجموعة بيانات أوج | صدى الحقيقية لتقديم تشخيص لهذا الجانب.",
            "contributing_factors": [],
            "recommendations": ["استكمال جمع بيانات X التاريخية عبر Full Archive API لتوسيع العينة الحقيقية."],
            "low_confidence": True,
        }

    try:
        diagnosis_text, recommendations = _synthesize_awj_via_llm(context["item_label"], context["factors"])
    except Exception:  # no key / model error / malformed reply: evidence-only wording
        diagnosis_text, recommendations = _evidence_only(context["factors"], f"{context['item_label']}:")
    return {
        "diagnosis": diagnosis_text,
        "contributing_factors": context["factors"],
        "recommendations": recommendations,
        "low_confidence": False,
    }


# ---------------------------------------------------------------------------
# Step 2b - diagnosis of a real collected post (an alert clicked in the Alerts view)
#
# Comparable posts are retrieved from the database (same platform + account + topic +
# content type, published within +-14 days). Every factor is computed from those real posts
# and cites one of them by permalink *before* any LLM is involved; the LLM only words the
# result. With too few comparables the result is low_confidence - nothing is invented.
# Findings are correlations between a post and its peers, not proven causes.
# ---------------------------------------------------------------------------

COMPARABLE_WINDOW_DAYS = 14
MIN_REAL_COMPARABLES = 3
UNDER, OVER = 0.8, 1.25  # ratio to the comparables' median beyond which a post counts as under/over-performing
_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")

_FEATURE_LABELS = {
    "question": "علامة استفهام",
    "number": "رقم",
    "emoji": "إيموجي",
    "long_title": "عنوان طويل (أكثر من ٧٠ حرفاً)",
}


def _primary_value(p: dict[str, Any]) -> int | None:
    if p["platform"] in ("youtube", "x"):  # X: impressions
        return p["view_count"]
    parts = [x for x in (p["like_count"], p["comment_count"]) if x is not None]
    return sum(parts) if parts else None


def _clock(hour: int) -> str:
    """Riyadh clock hour as people read it: 0 -> "12 ص", 13 -> "1 م"."""
    return f"{hour % 12 or 12} {'ص' if hour % 24 < 12 else 'م'}"


def _local_hour(p: dict[str, Any]) -> int:
    return p["published_at"].astimezone(repository.RIYADH_TZ).hour


def title_features(title: str) -> dict[str, bool]:
    t = title or ""
    return {
        "question": "?" in t or "؟" in t,
        "number": bool(re.search("[0-9٠-٩]", t)),
        "emoji": bool(_EMOJI.search(t)),
        "long_title": len(t) > 70,
    }


def _engagement_rate(p: dict[str, Any]) -> float | None:
    parts = [x for x in (p["like_count"], p["comment_count"]) if x is not None]
    return sum(parts) / p["view_count"] if parts and p.get("view_count") else None


# X posts are read once and never refreshed: counts captured this young are still growing,
# so they can't be compared with posts measured later.
MIN_MEASURED_DAYS_X = 3


def _measured_too_young(p: dict[str, Any]) -> bool:
    if p["platform"] != "x" or p["stats_updated_at"] is None:
        return False
    return p["stats_updated_at"] - p["published_at"] < timedelta(days=MIN_MEASURED_DAYS_X)


def _load_comparables(post: dict[str, Any], same_topic: bool) -> list[dict[str, Any]]:
    v, c = db.videos.c, db.channels.c
    stmt = (
        select(*repository._video_columns())
        .join(db.channels, v.channel_id == c.channel_id)
        .where(v.platform == post["platform"], c.entity_key == post["entity_key"], v.content_type == post["content_type"])
        .where(v.video_id != post["video_id"])
        .where(v.published_at >= post["published_at"] - timedelta(days=COMPARABLE_WINDOW_DAYS))
        .where(v.published_at <= post["published_at"] + timedelta(days=COMPARABLE_WINDOW_DAYS))
    )
    if same_topic:
        stmt = stmt.where(v.topic == post["topic"])
    with db.get_engine().connect() as conn:
        rows = [repository._video_dict(r) for r in conn.execute(stmt)]
    return [r for r in rows if _primary_value(r) is not None and not _measured_too_young(r)]


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


def build_video_diagnosis_context(post: dict[str, Any]) -> dict[str, Any]:
    """Deterministic retrieval + factor construction. No LLM, no invented numbers."""
    empty = {"post": post, "comparable": [], "basis": "none", "factors": [], "direction": None, "ratio": None, "low_confidence": True}
    value = _primary_value(post)
    if value is None or _measured_too_young(post):
        return empty

    basis = "topic"
    comparable = _load_comparables(post, same_topic=True)
    if len(comparable) < MIN_REAL_COMPARABLES:
        basis = "account"  # broaden once (any topic) - flagged in the output
        comparable = _load_comparables(post, same_topic=False)
    if len(comparable) < MIN_REAL_COMPARABLES:
        return empty

    median = statistics.median(_primary_value(c) for c in comparable)
    if not median:
        return empty
    ratio = value / median
    direction = "under" if ratio < UNDER else "over" if ratio > OVER else "in_line"
    metric_ar = {"youtube": "المشاهدات", "x": "مرات الظهور"}.get(post["platform"], "التفاعل (إعجابات + تعليقات)")
    ranked = sorted(comparable, key=_primary_value, reverse=True)
    half = max(1, len(ranked) // 2)
    top, bottom = ranked[:half], ranked[-half:]
    base_conf = round(min(0.9, 0.4 + len(comparable) / 40), 2)
    scope = "نفس الحساب والموضوع ونوع المحتوى" if basis == "topic" else "نفس الحساب ونوع المحتوى (دون اشتراط الموضوع لقلة العينة)"

    closest = min(comparable, key=lambda c: abs(_primary_value(c) - median))
    factors: list[dict[str, Any]] = [{
        "reason": f"{metric_ar} {'أقل' if ratio < 1 else 'أعلى'} من وسيط المنشورات المشابهة ({scope}، ±{COMPARABLE_WINDOW_DAYS} يوماً) بنسبة {abs(ratio - 1) * 100:.0f}%.",
        "supporting_metric": f"{_fmt(value)} مقابل وسيط {_fmt(median)} (n={len(comparable)})",
        "evidence_source_title": closest["title"],
        "evidence_url_or_ref": closest["url"],
        "confidence": base_conf,
        "recommendation": None,
    }]

    from backend.agents import root_cause

    rc = root_cause.analyze(post)
    drivers = rc["drivers"] if rc and direction != "in_line" else []
    driver_kinds = {d["kind"] for d in drivers}
    for d in drivers:
        factors.insert(len(factors) - 1, {  # before the headline comparison
            "reason": d["reason"],
            "supporting_metric": d["metric"],
            "evidence_source_title": d["evidence"]["title"],
            "evidence_url_or_ref": d["evidence"]["url"],
            "confidence": round(min(0.95, base_conf + 0.1), 2),
            "recommendation": d["decision"],
            "driver": d["kind"],
        })

    if direction != "in_line":
        # An under-performer is compared with the best peers, an over-performer with the worst.
        group, other = (top, bottom) if direction == "under" else (bottom, top)
        word = "الأعلى أداءً" if direction == "under" else "الأقل أداءً"
        anchor = group[0]
        fix = direction == "under"

        hours = [_local_hour(c) for c in group]
        ref_hour, my_hour = round(statistics.median(hours)), _local_hour(post)
        gap = min(abs(my_hour - ref_hour), 24 - abs(my_hour - ref_hour))
        near = sum(min(abs(h - ref_hour), 24 - abs(h - ref_hour)) <= 2 for h in hours) / len(hours)
        if len(group) >= 2 and gap >= 3 and near >= 0.4 and "timing" not in driver_kinds:  # clusters around one hour; not already a driver
            factors.append({
                "reason": f"ساعة النشر ({_clock(my_hour)} بتوقيت الرياض) تختلف عن ساعة نشر المنشورات {word} (حوالي {_clock(ref_hour)}).",
                "supporting_metric": f"فرق {gap} ساعات؛ {near * 100:.0f}% من {len(group)} منشورات مقارنة نُشرت خلال ±٢ ساعة من {_clock(ref_hour)}",
                "evidence_source_title": anchor["title"],
                "evidence_url_or_ref": anchor["url"],
                "confidence": round(base_conf * 0.8, 2),
                "recommendation": f"جرّب النشر قرب الساعة {_clock(ref_hour)} بتوقيت الرياض، كما في المنشورات الأعلى أداءً." if fix else None,
            })

        my_dur = post.get("duration_seconds")
        durs = [c["duration_seconds"] for c in group if c.get("duration_seconds")]
        if my_dur and len(durs) >= 2:
            ref_dur = statistics.median(durs)
            if abs(my_dur - ref_dur) / ref_dur >= 0.4:
                factors.append({
                    "reason": f"مدة المقطع ({my_dur} ث) تختلف جوهرياً عن مدة المنشورات {word} (وسيطها {ref_dur:.0f} ث).",
                    "supporting_metric": f"{my_dur} ث مقابل وسيط {ref_dur:.0f} ث (n={len(durs)})",
                    "evidence_source_title": anchor["title"],
                    "evidence_url_or_ref": anchor["url"],
                    "confidence": round(base_conf * 0.8, 2),
                    "recommendation": f"قرّب مدة المقطع من {ref_dur:.0f} ثانية." if fix else None,
                })

        mine = title_features(post["title"])
        for name, label in ({} if drivers else _FEATURE_LABELS).items():  # weak cues - only when no root cause was found
            rate = sum(title_features(c["title"])[name] for c in group) / len(group)
            rate_other = sum(title_features(c["title"])[name] for c in other) / len(other)
            if len(group) < 2 or abs(rate - rate_other) < 0.4:
                continue
            majority = rate >= 0.5
            if mine[name] == majority:
                continue  # the post already looks like the comparison group on this feature
            example = next((c for c in group if title_features(c["title"])[name] == majority), anchor)
            factors.append({
                "reason": (
                    f"عنوان المنشور {'يحتوي على' if mine[name] else 'لا يحتوي على'} {label}، بينما "
                    f"{(rate if majority else 1 - rate) * 100:.0f}% من المنشورات {word} {'تحتوي' if majority else 'لا تحتوي'} عليه."
                ),
                "supporting_metric": f"{rate * 100:.0f}% مقابل {rate_other * 100:.0f}% في المجموعة المقابلة (n={len(group)})",
                "evidence_source_title": example["title"],
                "evidence_url_or_ref": example["url"],
                "confidence": round(base_conf * 0.6, 2),
                "recommendation": f"{'أضف' if majority else 'تجنّب'} {label} في عناوين المحتوى المشابه." if fix else None,
            })

        if post["platform"] in ("youtube", "x"):
            my_er = _engagement_rate(post)
            ers = [e for e in (_engagement_rate(c) for c in comparable) if e is not None]
            if my_er is not None and len(ers) >= MIN_REAL_COMPARABLES:
                ref_er = statistics.median(ers)
                if ref_er and abs(my_er / ref_er - 1) >= 0.3:
                    reach_word = "الظهور" if post["platform"] == "x" else "المشاهدات"
                    if direction == "under" and my_er > ref_er:
                        er_reason = (f"من شاهد المنشور تفاعل معه أكثر من المعتاد: المحتوى نفسه لاقى قبولاً، "
                                     f"فالمشكلة في الوصول (عدد {reach_word}) لا في المحتوى.")
                    elif direction == "under":
                        er_reason = "حتى من شاهد المنشور تفاعل معه أقل من المعتاد: المحتوى نفسه لم يجذب الجمهور، لا التوزيع وحده."
                    else:
                        er_reason = f"معدل التفاعل (إعجابات + تعليقات ÷ {reach_word}) {'أقل' if my_er < ref_er else 'أعلى'} من وسيط المنشورات المشابهة."
                    factors.append({
                        "reason": er_reason,
                        "supporting_metric": f"{my_er * 100:.2f}% مقابل وسيط {ref_er * 100:.2f}% (n={len(ers)})",
                        "evidence_source_title": post["title"],  # the rate is this post's own
                        "evidence_url_or_ref": post["url"],
                        "confidence": round(base_conf * 0.8, 2),
                        "recommendation": None,
                    })

    audience = _audience_factor(post, base_conf)
    if audience:
        factors.append(audience)

    return {"post": post, "comparable": comparable, "basis": basis, "factors": factors, "direction": direction, "ratio": ratio,
            "low_confidence": False, "drivers": drivers, "root_cause": rc}


MIN_AUDIENCE_COMMENTS = 5
_INTENT_AR = {"praise": "إشادة", "criticism": "انتقاد", "request": "طلبات", "question": "أسئلة", "reaction": "تفاعل مع الحدث", "other": "أخرى"}


def _audience_factor(post: dict[str, Any], base_conf: float) -> dict[str, Any] | None:
    """What this post's own audience said (audience_agent's classification) - context, not a cause."""
    a = db.audience_comments.c
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            select(a.intent, a.sentiment).where(a.video_id == post["video_id"], a.intent.isnot(None))
        ).all()
    if len(rows) < MIN_AUDIENCE_COMMENTS:
        return None
    counts: dict[str, int] = {}
    for intent, _ in rows:
        counts[intent] = counts.get(intent, 0) + 1
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    breakdown = "، ".join(f"{_INTENT_AR.get(k, k)} {v * 100 // len(rows)}%" for k, v in top)
    criticism = counts.get("criticism", 0)
    return {
        "reason": (
            f"ردود الجمهور على هذا المنشور ({len(rows)} رداً مصنّفاً): {breakdown}."
            + (f" منها {criticism} انتقاداً موجّهاً للقناة أو المحتوى." if criticism else "")
        ),
        "supporting_metric": f"تصنيف وكيل تحليل الجمهور لـ {len(rows)} رداً على المنشور نفسه",
        "evidence_source_title": post["title"],
        "evidence_url_or_ref": post["url"],
        "confidence": round(base_conf * 0.6, 2),
        "recommendation": "راجع الانتقادات الموجّهة للمحتوى في ردود الجمهور قبل نشر محتوى مشابه." if criticism >= 3 else None,
    }


def _deterministic_synthesis(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    """Evidence-only wording, used when the LLM is unavailable."""
    post, ratio, direction = ctx["post"], ctx["ratio"], ctx["direction"]
    head = {
        "under": f"أداء «{post['title']}» أقل من المعتاد لمنشورات مشابهة ({ratio:.2f}× الوسيط).",
        "over": f"أداء «{post['title']}» أعلى من المعتاد لمنشورات مشابهة ({ratio:.2f}× الوسيط).",
        "in_line": f"أداء «{post['title']}» ضمن المعتاد لمنشورات مشابهة ({ratio:.2f}× الوسيط)؛ لا يوجد انحراف يستدعي تفسيراً.",
    }[direction]
    extra = [f["reason"] for f in ctx["factors"][1:3]]
    recs = [f["recommendation"] for f in ctx["factors"] if f.get("recommendation")]
    if not recs:
        recs = (
            ["لم يظهر فرق واضح في التوقيت أو المدة أو العنوان؛ قد يعود الأداء إلى عوامل غير مرصودة في البيانات."]
            if direction == "under"
            else ["لا توجد توصية محددة مدعومة بالأدلة؛ استمر في مراقبة الأداء."]
        )
    return " ".join([head, *extra]), recs


def _synthesize_video_via_llm(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    post = ctx["post"]
    factors_desc = "\n".join(f"{i}. {f['reason']} | المقياس: {f['supporting_metric']}" for i, f in enumerate(ctx["factors"]))
    prompt = (
        f"أنت محلل أداء محتوى لهيئة الإذاعة والتلفزيون السعودية. اشرح أداء المنشور ‘{post['title']}’ "
        f"(نسبته إلى وسيط المنشورات المشابهة: {ctx['ratio']:.2f}×) بالاستناد حصراً إلى العوامل التالية المستخرجة من بيانات حقيقية. "
        "لا تُضِف أي سبب أو رقم من عندك، وصرّح بأن الارتباط لا يثبت السببية.\n\n"
        f"{factors_desc}\n\n"
        'أعد فقط JSON بالمفاتيح: "diagnosis" (2-3 جمل بالعربية) و"recommendations" (قائمة 1-3 توصيات قصيرة مبنية على العوامل).'
    )
    parsed = _parse_llm_reply(llm_client.generate_json(prompt))
    return parsed["diagnosis"], parsed["recommendations"] or _deterministic_synthesis(ctx)[1]


def _root_cause_synthesis(ctx: dict[str, Any]) -> tuple[str, list[str]]:
    post, rc, drivers = ctx["post"], ctx["root_cause"], ctx["drivers"]
    first = drivers[0]
    value = _primary_value(post) or 0
    usual = f"{rc['index']:.2f}× المنشور المعتاد للحساب ({_fmt(value)} مقابل {_fmt(rc['baseline'])} {rc['metric']})"
    verb = "تراجع" if ctx["direction"] == "under" else "تفوّق"
    parts = [f"{verb} المنشور إلى {usual}." if ctx["direction"] == "under" else f"{verb} المنشور: {usual}.",
             f"السبب الأرجح: {first['reason']}"]
    if len(drivers) > 1:
        parts.append("وعامل مساعد: " + drivers[1]["reason"])
    er = next((f["reason"] for f in ctx["factors"] if "فالمشكلة في الوصول" in f["reason"] or "لم يجذب الجمهور" in f["reason"]), None)
    if er:
        parts.append(er)
    recs = [d["decision"] for d in drivers]
    if er and "فالمشكلة في الوصول" in er:
        recs.append("لا تغيّر المحتوى نفسه؛ أعد نشره أو انشر مثله مع تطبيق القرار أعلاه.")
    return " ".join(parts), recs


def diagnose_video(video_id: str) -> dict[str, Any] | None:
    """Diagnosis of a collected post, or None if the post doesn't exist."""
    post = repository.get_video(video_id)
    if post is None:
        return None
    post.pop("snapshots", None)
    ctx = build_video_diagnosis_context(post)
    if ctx["low_confidence"]:
        return {
            "diagnosis": "لا تتوفر منشورات مشابهة كافية (نفس الحساب ونوع المحتوى خلال ±١٤ يوماً) لتقديم تشخيص موثوق لهذا المنشور.",
            "contributing_factors": [],
            "recommendations": ["انتظر تراكم المزيد من المنشورات المشابهة قبل التشخيص."],
            "low_confidence": True,
        }
    evidence_hash = _evidence_hash(ctx)
    cached = None if ctx.get("drivers") else _cached_wording(video_id, evidence_hash)
    if ctx.get("drivers"):
        diagnosis, recs = _root_cause_synthesis(ctx)  # grounded wording; no LLM needed
    elif cached:
        diagnosis, recs = cached
    else:
        try:
            diagnosis, recs = _synthesize_video_via_llm(ctx)
            _save_wording(video_id, evidence_hash, diagnosis, recs)
        except Exception:  # no key / model error / malformed JSON: evidence-only wording, not cached
            diagnosis, recs = _deterministic_synthesis(ctx)
    if ctx["basis"] == "account":
        diagnosis += " (ملاحظة: المقارنة على مستوى الحساب ونوع المحتوى لقلة المنشورات بنفس الموضوع.)"
    factors = [{k: v for k, v in f.items() if k not in ("recommendation", "driver")} for f in ctx["factors"]]
    return {"diagnosis": diagnosis, "contributing_factors": factors, "recommendations": recs,
            "low_confidence": False, "from_cache": cached is not None}


def _evidence_hash(ctx: dict[str, Any]) -> str:
    """Fingerprint of everything the LLM is shown: same factors and ratio -> same wording, no new call."""
    material = [round(ctx["ratio"], 2), ctx["basis"], [[f["reason"], f["supporting_metric"]] for f in ctx["factors"]]]
    return hashlib.sha1(json.dumps(material, ensure_ascii=False).encode("utf-8")).hexdigest()


def _cached_wording(video_id: str, evidence_hash: str) -> tuple[str, list[str]] | None:
    d = db.diagnoses.c
    with db.get_engine().connect() as conn:
        row = conn.execute(select(d.diagnosis, d.recommendations).where(d.video_id == video_id, d.evidence_hash == evidence_hash)).first()
    return (row.diagnosis, json.loads(row.recommendations)) if row else None


def _save_wording(video_id: str, evidence_hash: str, diagnosis: str, recs: list[str]) -> None:
    row = {"video_id": video_id, "evidence_hash": evidence_hash, "diagnosis": diagnosis,
           "recommendations": json.dumps(recs, ensure_ascii=False), "model": llm_client.get_model(), "created_at": db.utcnow()}
    with db.get_engine().begin() as conn:
        db.upsert(conn, db.diagnoses, [row], "video_id", [k for k in row if k != "video_id"])


if __name__ == "__main__":
    sample_item = {
        "content_id": "diag-1",
        "title": "تجربة: حديث عن الدعم السكني",
        "platform": "x",
        "content_type": "video",
        "topic": "national_event",
        "format": "short_clip",
        "publish_hour": 20,
        "day_of_week": "tue",
        "views": 2000,
        "likes": 20,
        "shares": 5,
        "watch_time_seconds": 10.0,
    }
    print(json.dumps(run(sample_item), ensure_ascii=False, indent=2))
