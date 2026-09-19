"""Task 3 - Diagnostic & Recommendation Agent (RAG-grounded).

Explains why a published piece of content over/under-performed, grounded
in retrieved comparable history and Task 1's pattern store, and produces
actionable recommendations. See team.md for the full spec.

Retrieval is a deterministic metadata filter (team.md explicitly allows
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
