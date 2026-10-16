"""Task 3 - Diagnostic & Recommendation Agent (RAG-grounded).

Explains why a published piece of content over/under-performed, grounded
in retrieved comparable history and Task 1's pattern store, and produces
actionable recommendations. See AGENT_SPEC.md for the full spec.

Retrieval is a deterministic metadata filter (AGENT_SPEC.md explicitly allows
this instead of a vector DB for MVP): every contributing factor is built
from real retrieved records or real patterns *before* the LLM is called.
The LLM's only job is to turn that grounded material into a readable
diagnosis + ranked recommendations - it never gets a chance to invent a
metric, source or number that isn't already in the factor list.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.agents import behavior_analysis_agent, llm_client

HISTORY_PATH = Path(__file__).parent.parent / "data" / "content_history.json"
AWJ_RAW_PATH = Path(__file__).parent.parent / "data" / "raw" / "awj_sada_data.json"

MIN_COMPARABLE = 4  # below this, retrieval falls back to a broader match; below MIN_COMPARABLE_FLOOR it gives up
MIN_COMPARABLE_FLOOR = 2


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
    raw_text = llm_client.generate_json(prompt)
    parsed = json.loads(raw_text)
    return parsed["diagnosis"], parsed["recommendations"], parsed["factor_order"]


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

    diagnosis_text, recommendations, factor_order = _synthesize_via_llm(context)
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
    raw_text = llm_client.generate_json(prompt)
    parsed = json.loads(raw_text)
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

    diagnosis_text, recommendations = _synthesize_awj_via_llm(context["item_label"], context["factors"])
    return {
        "diagnosis": diagnosis_text,
        "contributing_factors": context["factors"],
        "recommendations": recommendations,
        "low_confidence": False,
    }


# ---------------------------------------------------------------------------
# Task 4 - diagnosis of a real collected post (YouTube video or Instagram post)
#
# Comparable posts are retrieved from the database (same platform + account + topic +
# content type, published within +-14 days). Every factor is computed from those real posts
# and cites one of them by permalink *before* any LLM is involved; the LLM only words the
# result. With too few comparables the result is low_confidence - nothing is invented.
# Findings are correlations between a post and its peers, not proven causes.
# ---------------------------------------------------------------------------

import re
import statistics
from datetime import timedelta

from sqlalchemy import select

from backend import db, repository

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
        if len(group) >= 2 and gap >= 3 and near >= 0.4:  # only when the comparison group actually clusters around one hour
            factors.append({
                "reason": f"ساعة النشر ({my_hour}:00 بتوقيت الرياض) تختلف عن ساعة نشر المنشورات {word} (حوالي {ref_hour}:00).",
                "supporting_metric": f"فرق {gap} ساعات؛ {near * 100:.0f}% من {len(group)} منشورات مقارنة نُشرت خلال ±٢ ساعة من {ref_hour}:00",
                "evidence_source_title": anchor["title"],
                "evidence_url_or_ref": anchor["url"],
                "confidence": round(base_conf * 0.8, 2),
                "recommendation": f"جرّب النشر قرب الساعة {ref_hour}:00 بتوقيت الرياض، كما في المنشورات الأعلى أداءً." if fix else None,
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
        for name, label in _FEATURE_LABELS.items():
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
                    factors.append({
                        "reason": f"معدل التفاعل (إعجابات + تعليقات ÷ مشاهدات) {'أقل' if my_er < ref_er else 'أعلى'} من وسيط المنشورات المشابهة.",
                        "supporting_metric": f"{my_er * 100:.2f}% مقابل وسيط {ref_er * 100:.2f}% (n={len(ers)})",
                        "evidence_source_title": closest["title"],
                        "evidence_url_or_ref": closest["url"],
                        "confidence": round(base_conf * 0.8, 2),
                        "recommendation": None,
                    })

    return {"post": post, "comparable": comparable, "basis": basis, "factors": factors, "direction": direction, "ratio": ratio, "low_confidence": False}


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
    parsed = json.loads(llm_client.generate_json(prompt))
    return parsed["diagnosis"], [str(r) for r in parsed["recommendations"]]


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
    try:
        diagnosis, recs = _synthesize_video_via_llm(ctx)
    except Exception:  # no key / model error / malformed JSON: fall back to evidence-only wording
        diagnosis, recs = _deterministic_synthesis(ctx)
    if ctx["basis"] == "account":
        diagnosis += " (ملاحظة: المقارنة على مستوى الحساب ونوع المحتوى لقلة المنشورات بنفس الموضوع.)"
    factors = [{k: v for k, v in f.items() if k != "recommendation"} for f in ctx["factors"]]
    return {"diagnosis": diagnosis, "contributing_factors": factors, "recommendations": recs, "low_confidence": False}


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
