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
    client = llm_client.get_client()
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
    response = client.messages.create(
        model=llm_client.get_model(),
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    raw_text = "".join(block.text for block in response.content if block.type == "text")
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
