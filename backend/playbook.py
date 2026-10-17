"""Publishing playbook: one direct decision per topic - where, what, which account, when.

The pattern store lists statistically tested facts one dimension at a time
("live does better", "weekends do better"...). This module combines the same
real post records into a complete recommendation a person can act on without
further analysis:

For a topic, every account with at least MIN_TOPIC_POSTS posts on it is an option:
- expected reach = the account's typical post (median views / impressions /
  interactions) x how this topic performs on that account (median account_index
  of its topic posts: 1.0 = the account's usual);
- content type = the type whose topic posts do best on that account (falls back to
  the account's best type overall when the topic sample per type is too small);
- time = the day + time band whose posts beat the account's usual most
  (performance_index, so it isn't just "the slot that had more video").
Every effect is shrunk toward 1.0 by its sample size before ranking and display, so a
handful of lucky posts can't outrank a well-measured slot, type or account.
Options are ranked by relative reach: expected reach / the typical SBA account's typical
post on the same platform. Views (YouTube) and impressions (X) are different units, and
raw reach would always pick the biggest account; the ratio is unitless and comparable
across platforms. The best option per platform is returned too.
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from typing import Any

from backend import db, repository
from backend.topics import TOPICS

MIN_TOPIC_POSTS = 5  # an account needs this many posts on the topic to be an option
# Shrinkage: a topic effect measured on few posts is pulled toward "usual" (1.0) on the
# log scale - multiplier ** (n / (n + PRIOR_POSTS)) - so 5 lucky posts can't outrank 40.
PRIOR_POSTS = 10
MIN_TYPE_POSTS_TOPIC = 5
MIN_TYPE_POSTS_ACCOUNT = 5
MIN_SLOT_POSTS = 5
CACHE_TTL_SECONDS = 60

PLATFORM_AR = {"youtube": "يوتيوب", "x": "إكس", "instagram": "إنستغرام"}
REACH_UNIT_AR = {"youtube": "مشاهدة", "x": "مرة ظهور", "instagram": "تفاعل"}
CONTENT_TYPE_AR = {
    "video": "فيديو", "short": "مقطع قصير", "live": "بث مباشر",
    "image": "صورة", "carousel": "ألبوم صور", "text": "منشور نصي",
}
DAY_AR = {"sun": "الأحد", "mon": "الاثنين", "tue": "الثلاثاء", "wed": "الأربعاء", "thu": "الخميس", "fri": "الجمعة", "sat": "السبت"}
# (key, Arabic label, hours) - Riyadh time
BANDS = [
    ("morning", "صباحاً (6-11)", range(6, 12)),
    ("noon", "ظهراً (12-3)", range(12, 16)),
    ("afternoon", "عصراً (4-6)", range(16, 19)),
    ("evening", "مساءً (7-10)", range(19, 23)),
    ("night", "ليلاً (11م-5ص)", [23, 0, 1, 2, 3, 4, 5]),
]
_BAND_OF_HOUR = {h: (key, label) for key, label, hours in BANDS for h in hours}

_cache: dict[int, tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _phrase(ratio: float) -> str:
    if ratio >= 1.95:
        return f"{ratio:.1f} ضعف المعتاد"
    pct = round(abs(ratio - 1) * 100)
    if pct < 5:
        return "مثل المعتاد"
    return f"أعلى من المعتاد بـ {pct}%" if ratio > 1 else f"أقل من المعتاد بـ {pct}%"


def _median(values: list[float]) -> float:
    return statistics.median(values)


def _shrink(multiplier: float, n: int) -> float:
    """Pull an effect measured on n posts toward 1.0 (log scale); small samples move less."""
    return math.exp(n / (n + PRIOR_POSTS) * math.log(max(multiplier, 0.01)))


def _best_content_type(topic_rows: list[dict[str, Any]], account_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    def best(rows: list[dict[str, Any]], min_n: int) -> tuple[str, float, int] | None:
        groups: dict[str, list[float]] = {}
        for r in rows:
            groups.setdefault(r["content_type"], []).append(r["account_index"])
        ranked = [(t, _shrink(_median(v), len(v)), len(v)) for t, v in groups.items() if len(v) >= min_n]
        return max(ranked, key=lambda x: x[1]) if ranked else None

    pick = best(topic_rows, MIN_TYPE_POSTS_TOPIC)
    scope = "topic"
    if pick is None or pick[1] < 1.0:  # nothing clearly better within the topic: use the account's best type
        account_pick = best(account_rows, MIN_TYPE_POSTS_ACCOUNT)
        if account_pick is not None and (pick is None or account_pick[1] > pick[1]):
            pick, scope = account_pick, "account"
    if pick is None:
        return None
    content_type, mult, n = pick
    return {"content_type": content_type, "label_ar": CONTENT_TYPE_AR.get(content_type, content_type),
            "multiplier": round(mult, 3), "n": n, "scope": scope}


def _best_time(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best (day, band) by median performance_index; falls back to the best band on any day."""
    by_slot: dict[tuple[str, str], list[float]] = {}
    by_band: dict[str, list[float]] = {}
    for r in rows:
        band, _ = _BAND_OF_HOUR[r["publish_hour"]]
        by_slot.setdefault((r["day_of_week"], band), []).append(r["performance_index"])
        by_band.setdefault(band, []).append(r["performance_index"])
    labels = {key: label for key, label, _ in BANDS}
    slots = [(d, b, _shrink(_median(v), len(v)), len(v)) for (d, b), v in by_slot.items() if len(v) >= MIN_SLOT_POSTS]
    if slots:
        day, band, mult, n = max(slots, key=lambda x: x[2])
        return {"day_of_week": day, "band": band, "label_ar": f"{DAY_AR[day]} {labels[band]}", "multiplier": round(mult, 3), "n": n}
    bands = [(b, _shrink(_median(v), len(v)), len(v)) for b, v in by_band.items() if len(v) >= MIN_SLOT_POSTS]
    if not bands:
        return None
    band, mult, n = max(bands, key=lambda x: x[1])
    return {"day_of_week": None, "band": band, "label_ar": f"أي يوم {labels[band]}", "multiplier": round(mult, 3), "n": n}


def _confidence(n: int) -> str:
    return "high" if n >= 20 else "medium" if n >= 10 else "low"


def _option(topic: str, platform: str, rows: list[dict[str, Any]], topic_rows: list[dict[str, Any]], platform_typical: float) -> dict[str, Any]:
    typical = _median([r["primary_value"] for r in rows])
    mult = _median([r["account_index"] for r in topic_rows])
    n = len(topic_rows)
    mult_shrunk = _shrink(mult, n)
    ctype = _best_content_type(topic_rows, rows)
    # Topic-specific timing when the topic has enough posts and a slot actually beats usual;
    # otherwise the account's best time overall.
    when = _best_time(topic_rows) if len(topic_rows) >= 15 else None
    if when is None or when["multiplier"] < 1.0:
        account_when = _best_time(rows)
        if account_when is not None and (when is None or account_when["multiplier"] > when["multiplier"]):
            when = account_when
    unit = REACH_UNIT_AR[platform]
    name = rows[0]["channel_name_ar"]
    topic_ar = TOPICS.get(topic, topic)
    reasons = [
        f"منشورات «{topic_ar}» على {name} في {PLATFORM_AR[platform]} تحقق {_phrase(mult)} للحساب "
        f"({len(topic_rows)} منشوراً).",
    ]
    if ctype:
        where = f"في «{topic_ar}» على هذا الحساب" if ctype["scope"] == "topic" else "على هذا الحساب عموماً"
        reasons.append(f"{ctype['label_ar']} هو أفضل نوع {where}: {_phrase(ctype['multiplier'])} ({ctype['n']} منشوراً).")
    if when:
        reasons.append(f"النشر {when['label_ar']} يحقق {_phrase(when['multiplier'])} لنفس الحساب ({when['n']} منشوراً).")
    return {
        "platform": platform,
        "entity_key": rows[0]["entity_key"],
        "name_ar": name,
        "topic_posts": len(topic_rows),
        "topic_multiplier": round(mult, 3),
        "typical_reach": round(typical),
        "expected_reach": round(typical * mult_shrunk),
        # x the typical SBA account on this platform - unitless, comparable across platforms
        "relative_reach": round(typical * mult_shrunk / platform_typical, 3) if platform_typical else None,
        "reach_unit_ar": unit,
        "content_type": ctype,
        "best_time": when,
        "confidence": _confidence(len(topic_rows)),
        "reasons": reasons,
    }


def build(days: int = 60) -> dict[str, Any]:
    records = repository.analysis_records(days=days)
    accounts: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in records:
        accounts.setdefault((r["platform"], r["entity_key"]), []).append(r)

    # The typical SBA account's typical post, per platform (median over accounts).
    per_platform: dict[str, list[float]] = {}
    for (platform, _), rows in accounts.items():
        per_platform.setdefault(platform, []).append(_median([r["primary_value"] for r in rows]))
    platform_typical = {p: _median(v) for p, v in per_platform.items()}

    topics = []
    for topic, label in TOPICS.items():
        options = []
        for (platform, _), rows in accounts.items():
            topic_rows = [r for r in rows if r["topic"] == topic]
            if len(topic_rows) >= MIN_TOPIC_POSTS:
                options.append(_option(topic, platform, rows, topic_rows, platform_typical[platform]))
        options.sort(key=lambda o: o["relative_reach"] or 0, reverse=True)
        best_per_platform: dict[str, dict[str, Any]] = {}
        for o in options:
            best_per_platform.setdefault(o["platform"], o)
        topics.append({
            "topic": topic,
            "label_ar": label,
            "posts": sum(1 for r in records if r["topic"] == topic),
            "best": options[0] if options else None,
            "by_platform": list(best_per_platform.values()),
            "options": options,
        })
    topics.sort(key=lambda t: t["posts"], reverse=True)
    return {"generated_at": db.utcnow(), "days": days, "min_topic_posts": MIN_TOPIC_POSTS, "topics": topics}


def playbook(days: int = 60) -> dict[str, Any]:
    now = time.monotonic()
    with _lock:
        hit = _cache.get(days)
        if hit and now - hit[0] < CACHE_TTL_SECONDS:
            return hit[1]
    result = build(days)
    with _lock:
        _cache[days] = (now, result)
    return result
