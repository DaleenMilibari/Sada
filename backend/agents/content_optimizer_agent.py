"""Task 2 - Content & Publishing Optimizer Agent.

Evaluates a draft piece of content against Task 1's pattern store and
recommends the best variant, platform and publish time. See AGENT_SPEC.md for
the full spec.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.agents import behavior_analysis_agent, llm_client
from backend.topics import TOPICS

logger = logging.getLogger("sada.optimizer")

# Default candidates: the platforms the Data Collector actually measures.
PLATFORMS = ["youtube", "x", "instagram"]

# Real patterns measured on one platform only apply to drafts for that platform.
_SOURCE_PLATFORM = {"real_youtube_sba": "youtube", "real_instagram_sba": "instagram", "real_x_sba": "x"}


def _applies_to(pattern: dict[str, Any], platform: str) -> bool:
    return _SOURCE_PLATFORM.get(pattern.get("source", ""), platform) == platform

TIME_WINDOWS = {
    "weekday_morning_6_13": "صباح أيام العمل (6:00-13:00)",
    "weekday_afternoon_14_17": "بعد ظهر أيام العمل (14:00-17:00)",
    "weekday_evening_18_23": "مساء أيام العمل (18:00-23:00)",
    "weekend": "عطلة نهاية الأسبوع",
}


def _real_time_windows(patterns: list[dict[str, Any]]) -> dict[str, str]:
    """team.md Task 1 'on real data': time windows come from the real best

    hours, not the 4 hardcoded buckets - restrict candidates to slots that
    actually have a measured `timing_real` pattern (any platform/source).
    Falls back to the full hardcoded TIME_WINDOWS when the store has no real
    timing patterns yet (e.g. only the synthetic seed has been analyzed), so
    behavior is unchanged until real data exists.
    """
    real_slots = {p["slice_key"] for p in patterns if p["dimension"] == "timing_real"}
    real_slots &= TIME_WINDOWS.keys()  # hour_bucket() only ever produces these 4 keys
    return {k: TIME_WINDOWS[k] for k in real_slots} if real_slots else TIME_WINDOWS

TEXT_HEURISTIC_BONUS = 8.0
HASHTAG_BONUS = 3.0
BASELINE_SCORE = 100.0


def _generate_variants_via_llm(
    content_type: str, topic: str, original_text: str | None, tone: str | None = None
) -> list[str]:
    seed = f'النص الأصلي: "{original_text}"' if original_text else "لا يوجد نص أصلي، اقترح من الصفر."
    if tone:
        seed = f"استخدم نبرة {tone}. {seed}"
    topic_label = TOPICS.get(topic, topic)
    prompt = (
        "أنت مساعد صياغة محتوى لمنصة إعلامية عربية اسمها صدى. "
        f"اكتب 3 نسخ بديلة (متغيرات) لمنشور من نوع '{content_type}' حول موضوع '{topic_label}'. "
        f"{seed}\n"
        "أعد النتيجة فقط كمصفوفة JSON من 3 نصوص عربية قصيرة (بدون أي شرح إضافي)، مثال: "
        '["نص 1", "نص 2", "نص 3"]'
    )
    raw_text = llm_client.generate_json(prompt)
    return _parse_variants(raw_text)


def _parse_variants(raw_text: str) -> list[str]:
    """Up to 4 non-empty text variants from the model's reply, whatever JSON shape it chose."""
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):  # e.g. {"variants": [...]}
        parsed = next((v for v in parsed.values() if isinstance(v, list)), None)
    if isinstance(parsed, list):
        texts = [v if isinstance(v, str) else (v.get("text") if isinstance(v, dict) else None) for v in parsed]
        variants = [t.strip() for t in texts if isinstance(t, str) and t.strip()]
    else:  # not JSON: one variant per non-empty line
        variants = [line.strip("- ‏‎\"[],") for line in raw_text.splitlines()]
        variants = [v for v in variants if v]
    return list(dict.fromkeys(variants))[:4]


def _text_heuristic_bonus(variant: str) -> tuple[float, str | None]:
    bonus = 0.0
    notes = []
    if "؟" in variant or "?" in variant:
        bonus += TEXT_HEURISTIC_BONUS
        notes.append("صيغة سؤال تفاعلي")
    if "#" in variant:
        bonus += HASHTAG_BONUS
        notes.append("وسوم مرفقة")
    return bonus, "، ".join(notes) if notes else None


def _matching_patterns(
    patterns: list[dict[str, Any]],
    content_type: str,
    topic: str,
    platform: str,
    time_window: str,
    channel: str | None = None,
) -> list[dict[str, Any]]:
    matched = []
    for p in patterns:
        if not _applies_to(p, platform):
            continue
        if p["dimension"] == "content_type" and p["slice_key"] == content_type:
            matched.append(p)
        elif p["dimension"] == "timing" and p["slice_key"] == time_window:
            matched.append(p)
        elif p["dimension"] == "topic_platform" and p["slice_key"] == f"{topic}|{platform}":
            matched.append(p)
        # Real-data counterparts (team.md Task 1 "on real data") - same idea,
        # scored on performance_index by analyze_real_data() instead of the
        # synthetic seed, so a draft can be backed by both at once.
        elif p["dimension"] == "content_type_real" and p["slice_key"] == content_type:
            matched.append(p)
        elif p["dimension"] == "timing_real" and p["slice_key"] == time_window:
            matched.append(p)
        elif p["dimension"] == "topic_real" and p["slice_key"] == topic:
            matched.append(p)
        elif p["dimension"] == "platform_content_real" and p["slice_key"] == f"{platform}|{content_type}":
            matched.append(p)
        elif channel and p["dimension"] == "channel_topic_real" and p["slice_key"] == f"{channel}|{topic}":
            matched.append(p)
    return matched


def _score_combo(
    variant: str,
    platform: str,
    time_window: str,
    content_type: str,
    topic: str,
    patterns: list[dict[str, Any]],
    channel: str | None = None,
) -> tuple[float, list[dict[str, Any]], str | None]:
    matched = _matching_patterns(patterns, content_type, topic, platform, time_window, channel)
    score = BASELINE_SCORE
    for p in matched:
        score *= 1 + (p["lift_pct"] / 100.0) * p["confidence"]
    text_bonus, note = _text_heuristic_bonus(variant)
    score += text_bonus
    return round(score, 1), matched, note


def optimize(draft: dict[str, Any], patterns: list[dict[str, Any]]) -> dict[str, Any]:
    content_type = draft["content_type"]
    topic = draft["topic"]
    platform_options = draft.get("platform_options") or PLATFORMS
    # None when no channel_options given - every candidate keeps channel=None,
    # which is exactly today's behavior (no channel-level matching/output).
    channel_options: list[str | None] = draft.get("channel_options") or [None]
    time_windows = _real_time_windows(patterns)

    variants = [v.strip() for v in draft.get("variants") or [] if v and v.strip()]
    variants_note = None
    if not variants:
        original = (draft.get("original_text") or "").strip()
        try:
            variants = _generate_variants_via_llm(content_type, topic, original or None, draft.get("tone"))
        except Exception:
            if not original:
                raise  # nothing to score at all - the API maps this to 503/502
            logger.exception("Variant generation failed - scoring the original text only")
            variants = []
        if not variants and original:
            variants = [original]
            variants_note = "تعذّر توليد صيغ بديلة بالذكاء الاصطناعي حالياً، فقُيّم النص الأصلي وحده."
    if not variants:
        raise ValueError("No variants supplied and none could be generated.")

    candidates = []
    for variant in variants:
        for platform in platform_options:
            for channel in channel_options:
                for time_window in time_windows:
                    score, matched, note = _score_combo(
                        variant, platform, time_window, content_type, topic, patterns, channel
                    )
                    candidates.append(
                        {
                            "variant": variant,
                            "platform": platform,
                            "channel": channel,
                            "time_window": time_window,
                            "predicted_engagement": score,
                            "matched_patterns": matched,
                            "note": note,
                        }
                    )

    candidates.sort(key=lambda c: c["predicted_engagement"], reverse=True)
    best = candidates[0]
    low_confidence = len(best["matched_patterns"]) == 0

    # platform_reach_real / awj_sada_real patterns describe season-level or
    # podcast-level comparisons (see schemas.Pattern), not per-draft
    # content/variant/timing behavior - never usable as fallback evidence.
    descriptive_only = {"platform_reach_real", "awj_sada_real"}
    fallback_candidates = [p for p in patterns if p["dimension"] not in descriptive_only]
    if low_confidence and fallback_candidates:
        # Fallback: no pattern applies to this content type/topic/platform
        # combo at all - fall back to the single highest-confidence pattern
        # we have, explicitly flagged as lower-confidence, per AGENT_SPEC.md.
        # Prefer one measured on the recommended platform, so the evidence
        # never describes a different platform than the one recommended.
        same_platform = [p for p in fallback_candidates if _applies_to(p, best["platform"])]
        fallback_pattern = max(same_platform or fallback_candidates, key=lambda p: p["confidence"])
        best["matched_patterns"] = [fallback_pattern]

    def evidence_for(matched: list[dict[str, Any]], note: str | None) -> list[dict[str, Any]]:
        ev = [
            {"pattern_id": p["pattern_id"], "pattern": p["pattern"], "note": None}
            for p in matched
        ]
        if note:
            ev.append({"pattern_id": "text_heuristic", "pattern": note, "note": "خاصية نصية في المتغير نفسه"})
        if variants_note:
            ev.append({"pattern_id": "variants_fallback", "pattern": variants_note, "note": None})
        return ev

    ranked_alternatives = [
        {
            "variant": c["variant"],
            "platform": c["platform"],
            "channel": c["channel"],
            "time_window": time_windows[c["time_window"]],
            "predicted_engagement": c["predicted_engagement"],
            "evidence": [p["pattern"] for p in c["matched_patterns"]] or ["لا يوجد نمط مطابق مباشر"],
        }
        for c in candidates[1:6]
    ]

    return {
        "recommended_variant": best["variant"],
        "predicted_engagement": best["predicted_engagement"],
        "recommended_platform": best["platform"],
        "recommended_channel": best["channel"],
        "recommended_time": time_windows[best["time_window"]],
        "ranked_alternatives": ranked_alternatives,
        "evidence": evidence_for(best["matched_patterns"], best["note"]),
        "low_confidence": low_confidence,
    }


def run(draft: dict[str, Any]) -> dict[str, Any]:
    patterns = behavior_analysis_agent.load_store()
    return optimize(draft, patterns)


if __name__ == "__main__":
    sample_draft = {
        "content_type": "video",
        "topic": "national_event",
        "platform_options": ["x", "instagram"],
        "original_text": "بث مباشر للحدث اليوم. تابعونا للوقوف على أبرز المستجدات والتفاصيل على الهواء.",
    }
    result = run(sample_draft)
    print(json.dumps(result, ensure_ascii=False, indent=2))
