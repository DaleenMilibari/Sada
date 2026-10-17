"""Suggest a first draft description for a new post, grounded in what is working now.

The optimizer used to start from a fixed template whatever the topic or account. This
picks SBA's best-performing recent posts on the same topic (on the chosen accounts when
they have any, else on any account), ranked by performance_index (vs the account's
usual, so big accounts don't win by size), and asks Gemini for a short new post idea in
that vein. The model is told not to copy them or invent facts; the posts it was given are
returned so the user sees what the suggestion is based on. Without an LLM, the strongest
recent post's title is used as the starting point.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from backend import repository, saudi_context
from backend.agents import llm_client
from backend.playbook import CONTENT_TYPE_AR, PLATFORM_AR
from backend.topics import TOPICS

logger = logging.getLogger("sada.draft")

RECENT_DAYS = (7, 30)  # look at the last week first, widen if the topic is quiet
MIN_AGE_DAYS = 0.5  # a few hours of engagement before a post counts as "working"
EXAMPLES = 5
MAX_CHARS = 250


def _examples(topic: str, entity_keys: list[str]) -> list[dict[str, Any]]:
    for days in RECENT_DAYS:
        rows = [r for r in repository.analysis_records(days=days, min_age_days=MIN_AGE_DAYS) if r["topic"] == topic]
        mine = [r for r in rows if r["entity_key"] in entity_keys] if entity_keys else rows
        pool = mine or rows
        if pool:
            pool.sort(key=lambda r: r["performance_index"], reverse=True)
            above = [r for r in pool if r["performance_index"] >= 1.0]  # beat their account's usual
            return (above if len(above) >= 2 else pool)[:EXAMPLES]
    return []


def suggest(topic: str, content_type: str, entity_keys: list[str], tone: str | None = None) -> dict[str, Any]:
    topic_ar = TOPICS.get(topic, topic)
    type_ar = CONTENT_TYPE_AR.get(content_type, content_type)
    examples = _examples(topic, entity_keys)
    based_on = [
        {"title": r["title"][:200], "url": r["url"], "channel_name_ar": r["channel_name_ar"], "platform": r["platform"],
         "performance_index": round(r["performance_index"], 2)}
        for r in examples
    ]
    if not examples:
        return {"text": f"منشور {type_ar} عن «{topic_ar}»: اكتب هنا فكرة المنشور الأساسية.", "source": "generic", "based_on": []}

    accounts = sorted({r["channel_name_ar"] for r in examples if not entity_keys or r["entity_key"] in entity_keys})
    lines = "\n".join(
        f"- [{PLATFORM_AR.get(r['platform'], r['platform'])} · {r['channel_name_ar']} · {r['performance_index']:.1f}× المعتاد] {r['title'][:220]}"
        for r in examples
    )
    prompt = (
        "أنت محرر محتوى رقمي في هيئة الإذاعة والتلفزيون السعودية.\n"
        f"اكتب وصفاً أولياً لمنشور {type_ar} جديد عن موضوع «{topic_ar}»"
        + (f" لحساب {('، '.join(accounts))}" if accounts else "")
        + ". الوصف هو فكرة المنشور التي سيحسّن صياغتها وكيل آخر لاحقاً.\n"
        "هذه أحدث منشورات الهيئة الأعلى أداءً في هذا الموضوع (مقارنة بالمعتاد لكل حساب):\n"
        f"{lines}\n\n"
        f"{saudi_context.writing_voice(tone)}\n"
        f"{saudi_context.local_moment()}\n"
        "المطلوب: فكرة منشور جديد يواكب ما يتفاعل معه الجمهور الآن في هذه المنشورات. "
        f"جملة أو جملتان بالعربية، أقل من {MAX_CHARS} حرفاً. لا تنسخ أي منشور حرفياً، "
        "ولا تخترع أرقاماً أو أسماء أو أحداثاً غير موجودة في المنشورات أعلاه. "
        "ابدأ بنص المنشور مباشرة دون مقدمات مثل «فكرة المنشور:».\n"
        'أعد JSON فقط: {"text": "..."}'
    )
    try:
        text = str(json.loads(llm_client.generate_json(prompt)).get("text") or "").strip()
        if text:
            return {"text": text[:400], "source": "ai", "based_on": based_on}
    except llm_client.MissingApiKeyError:
        pass
    except Exception:
        logger.exception("Draft suggestion failed - falling back to the strongest recent post")
    return {"text": f"متابعة لـ: {examples[0]['title'][:MAX_CHARS]}", "source": "recent_post", "based_on": based_on}
