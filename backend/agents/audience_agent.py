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

from sqlalchemy import bindparam, func, select, update

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
        _themes_cache.clear()


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
        except (llm_client.MissingApiKeyError, llm_client.QuotaExhaustedError, llm_client.DeadlineExceededError) as e:
            logger.warning("Audience classification stopped: %s", e)  # the rest wait for the next run
            break
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
        # About SBA / the channel / its content (not reactions to the news, not off-topic):
        # the meaningful base for "how does the audience feel about us".
        "directed": sum(1 for r in classified if r["intent"] not in SBA_NEUTRAL_INTENTS),
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


# ---------------------------------------------------------------------------
# Human review: blind labels and measured accuracy
# ---------------------------------------------------------------------------
#
# A reviewer labels comments WITHOUT seeing the agent's label (no anchoring); the
# agent's accuracy is then measured on every comment both have labeled. Same
# definitions as the classifier, including "reaction"/"other" => neutral toward SBA.

MIN_FOR_ACCURACY = 30  # below this the numbers are shown as preliminary


def review_queue(limit: int = 1) -> list[dict[str, Any]]:
    """Next agent-classified comments with no human label yet - text only, never the agent's label."""
    a, l, v, c = db.audience_comments.c, db.audience_labels.c, db.videos.c, db.channels.c
    stmt = (
        select(a.comment_id, a.text, a.platform, c.name_ar.label("channel_name_ar"), v.url, v.title)
        .join(db.videos, a.video_id == v.video_id)
        .join(db.channels, v.channel_id == c.channel_id)
        .outerjoin(db.audience_labels, l.comment_id == a.comment_id)
        .where(a.sentiment.isnot(None), l.comment_id.is_(None))
        .order_by(func.substr(a.comment_id, -3), a.comment_id)  # spread across posts/accounts, deterministic
        .limit(limit)
    )
    with db.get_engine().connect() as conn:
        return [r._asdict() for r in conn.execute(stmt)]


def save_label(comment_id: str, sentiment: str, intent: str) -> bool:
    if sentiment not in SENTIMENTS or intent not in INTENTS:
        raise ValueError("invalid label")
    if intent in SBA_NEUTRAL_INTENTS:
        sentiment = "neutral"
    with db.get_engine().begin() as conn:
        exists_ = conn.execute(
            select(db.audience_comments.c.comment_id).where(db.audience_comments.c.comment_id == comment_id)
        ).first()
        if not exists_:
            return False
        db.upsert(conn, db.audience_labels,
                  [{"comment_id": comment_id, "sentiment": sentiment, "intent": intent, "labeled_at": db.utcnow()}],
                  "comment_id", ["sentiment", "intent", "labeled_at"])
    return True


def _scores(pairs: list[tuple[str, str]], classes: list[str]) -> dict[str, Any]:
    """Accuracy, macro-F1, Cohen's kappa and per-class precision/recall over (human, model) pairs."""
    n = len(pairs)
    correct = sum(h == m for h, m in pairs)
    per_class, f1s = [], []
    for k in classes:
        tp = sum(h == k and m == k for h, m in pairs)
        pred = sum(m == k for _, m in pairs)
        true = sum(h == k for h, _ in pairs)
        if true == 0 and pred == 0:
            continue
        precision = tp / pred if pred else 0.0
        recall = tp / true if true else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1s.append(f1)
        per_class.append({"label": k, "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3), "support": true})
    p_o = correct / n
    p_e = sum((sum(h == k for h, _ in pairs) / n) * (sum(m == k for _, m in pairs) / n) for k in classes)
    kappa = (p_o - p_e) / (1 - p_e) if p_e < 1 else 1.0
    return {
        "accuracy": round(p_o, 3),
        "macro_f1": round(sum(f1s) / len(f1s), 3) if f1s else None,
        "kappa": round(kappa, 3),
        "per_class": per_class,
    }


def accuracy() -> dict[str, Any]:
    a, l = db.audience_comments.c, db.audience_labels.c
    with db.get_engine().connect() as conn:
        rows = conn.execute(
            select(l.sentiment, l.intent, a.sentiment.label("m_sentiment"), a.intent.label("m_intent"))
            .join(db.audience_comments, a.comment_id == l.comment_id)
            .where(a.sentiment.isnot(None))
        ).all()
        pending = conn.execute(
            select(func.count()).select_from(db.audience_comments)
            .outerjoin(db.audience_labels, l.comment_id == a.comment_id)
            .where(a.sentiment.isnot(None), l.comment_id.is_(None))
        ).scalar() or 0
    n = len(rows)
    result: dict[str, Any] = {
        "n": n,
        "pending": pending,
        "min_for_accuracy": MIN_FOR_ACCURACY,
        "preliminary": n < MIN_FOR_ACCURACY,
        "model": llm_client.get_model(),
        "sentiment": None,
        "intent": None,
    }
    if n:
        result["sentiment"] = _scores([(r.sentiment, r.m_sentiment) for r in rows], list(SENTIMENTS))
        result["intent"] = _scores([(r.intent, r.m_intent) for r in rows], list(INTENTS))
    return result


# ---------------------------------------------------------------------------
# Themes: what the audience asks for / criticizes, turned into recommendations
# ---------------------------------------------------------------------------
#
# Gemini groups request + criticism comments into themes and words one actionable
# recommendation per theme. Everything countable is computed here, not by the model:
# members are validated indices into the comments sent, counts and accounts come from
# the data, and a theme needs MIN_THEME_EVIDENCE real comments to be shown.

THEME_KINDS = ("request", "criticism")
MIN_THEME_EVIDENCE = 2
MAX_THEME_INPUT = 300
THEMES_TTL_SECONDS = 6 * 3600
_themes_cache: dict[tuple[int, str | None, int], tuple[float, dict[str, Any]]] = {}


def _theme_comments(days: int, platform: str | None) -> list[dict[str, Any]]:
    rows = [r for r in _comment_rows(days, platform) if r["intent"] in THEME_KINDS]
    rows.sort(key=lambda r: r["like_count"] or 0, reverse=True)
    return rows[:MAX_THEME_INPUT]


def build_themes(days: int = 30, platform: str | None = None) -> dict[str, Any]:
    from backend.topics import TOPICS

    rows = _theme_comments(days, platform)
    result: dict[str, Any] = {"generated_at": db.utcnow(), "days": days, "platform": platform,
                              "n_comments": len(rows), "themes": [], "status": "ok"}
    if len(rows) < MIN_THEME_EVIDENCE:
        result["status"] = "not_enough_comments"
        return result
    lines = "\n".join(
        f"{i} | {r['intent']} | {r['channel_name_ar']} | {r['text'][:220].replace(chr(10), ' ')}" for i, r in enumerate(rows)
    )
    topics = ", ".join(f'"{k}" ({v})' for k, v in TOPICS.items())
    prompt = (
        "أنت محلل جمهور لهيئة الإذاعة والتلفزيون السعودية. هذه طلبات الجمهور وانتقاداته لقنوات الهيئة.\n"
        "كل سطر: رقم | النوع (request طلب / criticism انتقاد) | القناة | النص.\n"
        f"{lines}\n\n"
        "جمّعها في 3 إلى 6 مواضيع واضحة، كل موضوع يجمع تعليقات تقول الشيء نفسه تقريباً. لكل موضوع أعد:\n"
        '- "title": عنوان قصير وواضح بالعربية (أقل من 8 كلمات)\n'
        '- "kind": "request" أو "criticism"\n'
        '- "recommendation": توصية عملية واحدة لفريق المحتوى في الهيئة (جملة واحدة تبدأ بفعل)\n'
        f'- "topic": أقرب موضوع من القائمة: {topics}\n'
        '- "members": أرقام التعليقات التي تنتمي لهذا الموضوع فقط\n'
        "لا تخترع مواضيع لا تدعمها التعليقات. تجاهل التعليقات التي لا تنتمي لأي موضوع.\n"
        "تجاهل أيضاً أي تعليقات هي في الحقيقة تفاعل مع الخبر أو الحدث نفسه (دعاء، تنديد بطرف، رأي في الحكم أو الفرق) "
        "وليست طلباً من الهيئة أو انتقاداً لقنواتها ومحتواها وتغطيتها.\n"
        'أعد JSON فقط بالشكل: {"themes": [ ... ]}'
    )
    try:
        data = json.loads(llm_client.generate_json(prompt))
    except llm_client.MissingApiKeyError:
        result["status"] = "no_llm"
        return result
    except Exception:
        logger.exception("Audience theme extraction failed")
        result["status"] = "llm_failed"
        return result

    used: set[int] = set()
    for t in (data.get("themes") if isinstance(data, dict) else None) or []:
        if not isinstance(t, dict) or t.get("kind") not in THEME_KINDS:
            continue
        raw_members = t.get("members") if isinstance(t.get("members"), list) else []
        indices = {int(m) for m in raw_members if isinstance(m, int) or (isinstance(m, str) and m.strip().isdigit())}
        members = sorted(m for m in indices if 0 <= m < len(rows) and m not in used)
        if len(members) < MIN_THEME_EVIDENCE:
            continue  # not enough real comments behind it - never shown
        used.update(members)
        group = [rows[m] for m in members]
        accounts = Counter((r["platform"], r["entity_key"], r["channel_name_ar"]) for r in group)
        (top_platform, top_entity, _), _ = accounts.most_common(1)[0]
        result["themes"].append({
            "title": str(t.get("title") or "")[:80],
            "kind": t["kind"],
            "recommendation": str(t.get("recommendation") or "")[:300],
            "topic": t.get("topic") if t.get("topic") in TOPICS else "other",
            "count": len(group),
            "likes": sum(r["like_count"] or 0 for r in group),
            "accounts": [{"platform": p, "entity_key": k, "name_ar": n, "count": c} for (p, k, n), c in accounts.most_common()],
            "main_platform": top_platform,
            "main_entity_key": top_entity,
            "examples": [{"text": r["text"][:200], "url": r["url"], "channel_name_ar": r["channel_name_ar"],
                          "platform": r["platform"], "like_count": r["like_count"]} for r in group[:3]],
        })
    result["themes"].sort(key=lambda t: t["count"], reverse=True)
    return result


def themes(days: int = 30, platform: str | None = None) -> dict[str, Any]:
    """One Gemini call per (window, platform, comment set), cached for THEMES_TTL_SECONDS."""
    key = (days, platform, len(_theme_comments(days, platform)))
    now = time.monotonic()
    with _lock:
        hit = _themes_cache.get(key)
        if hit and now - hit[0] < THEMES_TTL_SECONDS:
            return hit[1]
    result = build_themes(days, platform)
    if result["status"] == "ok":
        with _lock:
            _themes_cache[key] = (now, result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Classify collected audience comments with Gemini.")
    parser.add_argument("--limit", type=int, default=500, help="comments to classify")
    args = parser.parse_args()
    db.init_db()
    print(f"Classified {classify_pending(args.limit)} comment(s).")
