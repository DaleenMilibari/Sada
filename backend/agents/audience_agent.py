"""Audience Analysis agent - what SBA's audience says, and how it grows.

- Goal: Turn public comments (YouTube) and replies (X) on SBA posts into an
  aggregate picture: sentiment, what people ask for, praise or criticize, which
  posts drive discussion, and follower growth per account.
- Input: `audience_comments` and `follower_snapshots` (filled by the Data
  Collector's audience step, audience_collector.py), joined to posts/channels.
- Tools: Gemini (llm_client) classifies comment batches; everything else is
  deterministic aggregation.
- Evidence: every share comes with its sample size; every intent lists real
  example comments with a link to the post they were written on.
- Privacy: no author data exists in the database; output is aggregate only.
- Failure/fallback: without a Gemini key, comments stay unclassified and the
  summary says so (classified < comments). Unclassified is never counted as neutral.
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
from collections import Counter
from datetime import timedelta
from typing import Any

from sqlalchemy import bindparam, select, update

from backend import db, repository
from backend.agents import llm_client

logger = logging.getLogger("sada.audience")

SENTIMENTS = ("positive", "negative", "neutral")
INTENTS = {
    "praise": "إشادة وثناء",
    "criticism": "انتقاد وملاحظات",
    "request": "طلبات واقتراحات محتوى",
    "question": "أسئلة واستفسارات",
    "reaction": "تفاعل مع الحدث نفسه",
    "other": "أخرى",
}
# Not about SBA or its content -> neutral toward SBA by definition, whatever tone the model read.
SBA_NEUTRAL_INTENTS = ("reaction", "other")
BATCH_SIZE = 100  # comments per Gemini request (free keys allow ~20 requests/day)
MIN_FOR_SHARE = 10  # fewer classified comments than this -> shares are null, not a guess
EXAMPLES_PER_INTENT = 3
CACHE_TTL_SECONDS = 60

_cache: dict[tuple[int, str | None], tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


# ---------------------------------------------------------------------------
# Classification (Gemini)
# ---------------------------------------------------------------------------


def classify_pending(limit: int) -> int:
    """Classify up to `limit` unclassified comments. Returns how many were classified."""
    if limit <= 0:
        return 0
    a = db.audience_comments.c
    with db.get_engine().connect() as conn:
        pending = conn.execute(
            select(a.comment_id, a.text).where(a.sentiment.is_(None)).order_by(a.collected_at.desc()).limit(limit)
        ).all()
    classified = 0
    for i in range(0, len(pending), BATCH_SIZE):
        batch = pending[i : i + BATCH_SIZE]
        lines = "\n".join(f"{n} | {text[:300].replace(chr(10), ' ')}" for n, (_, text) in enumerate(batch))
        prompt = (
            "أنت محلل جمهور لهيئة الإذاعة والتلفزيون السعودية. هذه تعليقات الجمهور على منشورات قنوات الهيئة.\n"
            "المطلوب قياس موقف الجمهور من الهيئة وقنواتها ومحتواها وتغطيتها ومذيعيها - وليس من الخبر أو الحدث نفسه.\n"
            '- "s": المشاعر تجاه الهيئة/القناة/المحتوى/التغطية: "positive" أو "negative" أو "neutral". '
            'إذا لم يتحدث التعليق عن الهيئة أو محتواها فهو "neutral".\n'
            '- "i": نوع التعليق:\n'
            '  "praise": مدح القناة أو البرنامج أو التغطية أو المذيع.\n'
            '  "criticism": انتقاد القناة أو جودة التغطية أو المحتوى أو البث أو المذيع.\n'
            '  "request": طلب أو اقتراح محتوى أو خدمة من القناة.\n'
            '  "question": سؤال موجّه للقناة أو عن المحتوى.\n'
            '  "reaction": تفاعل مع الحدث أو الخبر نفسه وليس مع القناة: دعاء، تعاطف، فرح أو غضب من الحدث، '
            'رأي في الفرق أو التحكيم أو الأطراف. مثال: "الله ينتقم من المعتدين" أو "الحكم ظلم الهلال" = reaction و neutral.\n'
            '  "other": إعلانات، أو كلام لا علاقة له.\n'
            "كل سطر بالشكل: رقم | نص التعليق.\n"
            f"{lines}\n"
            'أعد كائن JSON فقط يربط كل رقم بنتيجته، مثال: {"0": {"s": "positive", "i": "praise"}}'
        )
        try:
            mapping = json.loads(llm_client.generate_json(prompt))
        except llm_client.MissingApiKeyError:
            return classified
        except Exception:
            logger.exception("Audience classification batch failed")
            continue
        now = db.utcnow()
        updates = []
        for n, (comment_id, _) in enumerate(batch):
            label = mapping.get(str(n)) if isinstance(mapping, dict) else None
            if not isinstance(label, dict):
                continue
            s, intent = label.get("s"), label.get("i")
            if s in SENTIMENTS and intent in INTENTS:  # anything else stays unclassified
                if intent in SBA_NEUTRAL_INTENTS:
                    s = "neutral"
                updates.append({"cid": comment_id, "s": s, "i": intent, "at": now})
        if updates:
            with db.get_engine().begin() as conn:
                conn.execute(
                    update(db.audience_comments)
                    .where(db.audience_comments.c.comment_id == bindparam("cid"))
                    .values(sentiment=bindparam("s"), intent=bindparam("i"), classified_at=bindparam("at")),
                    updates,
                )
            classified += len(updates)
    if classified:
        clear_cache()
    return classified


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def _shares(rows: list[dict[str, Any]]) -> dict[str, Any]:
    classified = [r for r in rows if r["sentiment"] is not None]
    counts = Counter(r["sentiment"] for r in classified)
    enough = len(classified) >= MIN_FOR_SHARE
    share = lambda k: round(counts[k] / len(classified), 4) if enough else None  # noqa: E731
    return {
        "comments": len(rows),
        "classified": len(classified),
        "positive": counts["positive"],
        "negative": counts["negative"],
        "neutral": counts["neutral"],
        "positive_share": share("positive"),
        "negative_share": share("negative"),
        # (positive - negative) / classified, -1..1
        "net_sentiment": round((counts["positive"] - counts["negative"]) / len(classified), 4) if enough else None,
    }


def _comment_rows(days: int, platform: str | None) -> list[dict[str, Any]]:
    a, v, c = db.audience_comments.c, db.videos.c, db.channels.c
    stmt = (
        select(a.comment_id, a.platform, a.video_id, a.text, a.published_at, a.like_count, a.sentiment, a.intent,
               c.entity_key, c.name_ar.label("channel_name_ar"), v.url)
        .join(db.videos, a.video_id == v.video_id)
        .join(db.channels, v.channel_id == c.channel_id)
        .where(a.published_at >= db.utcnow() - timedelta(days=days))
    )
    if platform:
        stmt = stmt.where(a.platform == platform)
    with db.get_engine().connect() as conn:
        return [r._asdict() for r in conn.execute(stmt)]


def _follower_growth(days: int, platform: str | None) -> list[dict[str, Any]]:
    f, c = db.follower_snapshots.c, db.channels.c
    stmt = (
        select(f.channel_id, f.captured_at, f.followers, c.platform, c.entity_key, c.name_ar)
        .join(db.channels, f.channel_id == c.channel_id)
        .where(f.captured_at >= db.utcnow() - timedelta(days=days))
        .order_by(f.channel_id, f.captured_at)
    )
    if platform:
        stmt = stmt.where(c.platform == platform)
    series: dict[str, list[Any]] = {}
    with db.get_engine().connect() as conn:
        for r in conn.execute(stmt):
            series.setdefault(r.channel_id, []).append(r)
    out = []
    for points in series.values():
        first, last = points[0], points[-1]
        span_days = (db.as_utc(last.captured_at) - db.as_utc(first.captured_at)).total_seconds() / 86400
        out.append({
            "platform": first.platform,
            "entity_key": first.entity_key,
            "name_ar": first.name_ar,
            "first_at": db.as_utc(first.captured_at),
            "last_at": db.as_utc(last.captured_at),
            "first": first.followers,
            "last": last.followers,
            # Growth needs two measurements a meaningful time apart - otherwise null, never 0.
            "change": last.followers - first.followers if len(points) > 1 and span_days >= 0.5 else None,
            "change_pct": round((last.followers - first.followers) / first.followers, 5)
            if len(points) > 1 and span_days >= 0.5 and first.followers else None,
            "points": [{"at": db.as_utc(p.captured_at), "followers": p.followers} for p in points],
        })
    out.sort(key=lambda g: g["last"], reverse=True)
    return out


def build_summary(days: int = 30, platform: str | None = None) -> dict[str, Any]:
    rows = _comment_rows(days, platform)

    by_channel = []
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        grouped.setdefault((r["platform"], r["entity_key"]), []).append(r)
    for (p, key), group in grouped.items():
        by_channel.append({"platform": p, "entity_key": key, "name_ar": group[0]["channel_name_ar"], **_shares(group)})
    by_channel.sort(key=lambda x: x["comments"], reverse=True)

    classified = [r for r in rows if r["intent"] is not None]
    intents = []
    for intent, label in INTENTS.items():
        group = [r for r in classified if r["intent"] == intent]
        if not group:
            continue
        top = sorted(group, key=lambda r: r["like_count"] or 0, reverse=True)[:EXAMPLES_PER_INTENT]
        intents.append({
            "intent": intent,
            "label_ar": label,
            "count": len(group),
            "share": round(len(group) / len(classified), 4) if len(classified) >= MIN_FOR_SHARE else None,
            "examples": [
                {"text": r["text"][:280], "url": r["url"], "platform": r["platform"],
                 "channel_name_ar": r["channel_name_ar"], "like_count": r["like_count"], "sentiment": r["sentiment"]}
                for r in top
            ],
        })
    intents.sort(key=lambda x: x["count"], reverse=True)

    per_post: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        per_post.setdefault(r["video_id"], []).append(r)
    discussed = []
    for video_id, group in sorted(per_post.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]:
        video = repository.get_video(video_id)
        if video:
            video.pop("snapshots", None)
            discussed.append({"video": video, **_shares(group)})

    return {
        "generated_at": db.utcnow(),
        "days": days,
        "platform": platform,
        "totals": _shares(rows),
        "by_channel": by_channel,
        "intents": intents,
        "discussed_posts": discussed,
        "follower_growth": _follower_growth(days, platform),
    }


def summary(days: int = 30, platform: str | None = None) -> dict[str, Any]:
    """Cached for CACHE_TTL_SECONDS per (days, platform)."""
    key = (days, platform)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    result = build_summary(days, platform)
    with _lock:
        _cache[key] = (now, result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Classify collected audience comments with Gemini.")
    parser.add_argument("--limit", type=int, default=500, help="comments to classify")
    args = parser.parse_args()
    db.init_db()
    print(f"Classified {classify_pending(args.limit)} comment(s).")
