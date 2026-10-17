"""Root causes a team can act on, measured on the account's own history.

The comparable-posts diagnosis says *that* a post under- or over-performed; this module
says *why, in terms of a decision*. For a post it checks the levers a social team
controls and, for each one the post is on the wrong (or right) side of, measures from
the same account's own posts how much that lever usually costs or pays:

- burst: published within BURST_GAP_MIN minutes after another post of the same account
  (a series dumped at once - the platform pushes the first and the rest compete with it);
- crowding: unusually many same-account posts in the surrounding hours;
- timing: published in a day/time band the account's posts usually under-perform in;
- format: a content type that does worse than the account's best type.

Every effect is the median "account index" (post / the account's typical post) of posts
with the attribute vs. the reference group, from at least MIN_GROUP posts each; nothing
is reported on fewer. Drivers are ranked by how much they cost (or pay), so the first one
is "the most likely reason", with a concrete decision and the post that proves it.
"""

from __future__ import annotations

import statistics
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from backend import db, repository
from backend.playbook import CONTENT_TYPE_AR, _BAND_OF_HOUR, BANDS

HISTORY_DAYS = 60
BURST_GAP_MIN = 10
CROWD_WINDOW_H = 3
MIN_GROUP = 8
HURTS = 0.8  # an attribute must cost at least 20% to be called a cause
HELPS = 1.25
MIN_MEASURED_DAYS_X = 3  # X counts are frozen at collection; younger measurements aren't comparable

_BAND_LABEL = {key: label for key, label, _ in BANDS}


def _primary(p: dict[str, Any]) -> int | None:
    if p["platform"] in ("youtube", "x"):
        return p["view_count"]
    parts = [x for x in (p["like_count"], p["comment_count"]) if x is not None]
    return sum(parts) if parts else None


def _fmt(n: float) -> str:
    return f"{n:,.0f}"


def _times(r: float) -> str:
    if r >= 1.95:
        return f"{r:.1f} ضعف"
    pct = round(abs(r - 1) * 100)
    return f"أعلى بـ {pct}%" if r > 1 else f"أقل بـ {pct}%"


def _history(post: dict[str, Any]) -> list[dict[str, Any]]:
    """The account's posts within ±HISTORY_DAYS of this one, with their primary value."""
    v, c = db.videos.c, db.channels.c
    start = post["published_at"] - timedelta(days=HISTORY_DAYS)
    end = post["published_at"] + timedelta(days=HISTORY_DAYS)
    with db.get_engine().connect() as conn:
        rows = [
            repository._video_dict(r)
            for r in conn.execute(
                select(*repository._video_columns())
                .join(db.channels, v.channel_id == c.channel_id)
                .where(v.channel_id == post["channel_id"], v.published_at.between(start, end))
                .order_by(v.published_at)
            )
        ]
    for r in rows:
        r["value"] = _primary(r)
    return rows


def _measurable(r: dict[str, Any]) -> bool:
    if r["value"] is None:
        return False
    if r["platform"] == "x" and r["stats_updated_at"] is not None:
        return r["stats_updated_at"] - r["published_at"] >= timedelta(days=MIN_MEASURED_DAYS_X)
    return True


def _annotate(rows: list[dict[str, Any]]) -> None:
    """Burst rank (0 = led the burst / alone), burst leader, crowd size and Riyadh time band."""
    leader = None
    prev = None
    for r in rows:  # rows are sorted by published_at
        if prev is not None and r["published_at"] - prev["published_at"] <= timedelta(minutes=BURST_GAP_MIN):
            r["burst_rank"] = prev["burst_rank"] + 1
            r["burst_leader"] = leader
        else:
            r["burst_rank"] = 0
            r["burst_leader"] = r
            leader = r
        prev = r
    window = timedelta(hours=CROWD_WINDOW_H)
    times = [r["published_at"] for r in rows]
    for r in rows:
        t = r["published_at"]
        r["crowd"] = sum(1 for x in times if abs(x - t) <= window) - 1
        local = t.astimezone(repository.RIYADH_TZ)
        r["band"] = _BAND_OF_HOUR[local.hour][0]


def _median(xs: list[float]) -> float:
    return statistics.median(xs)


def analyze(post: dict[str, Any]) -> dict[str, Any] | None:
    """{"baseline", "index", "direction", "drivers": [...]} or None when the account history is too thin."""
    rows = _history(post)
    me = next((r for r in rows if r["video_id"] == post["video_id"]), None)
    if me is None or me["value"] is None:
        return None
    _annotate(rows)
    peers = [r for r in rows if _measurable(r) and r["video_id"] != post["video_id"]]
    if len(peers) < 2 * MIN_GROUP:
        return None
    baseline = _median([r["value"] for r in peers]) or 1
    for r in rows:
        r["idx"] = (r["value"] or 0) / baseline
    my_idx = me["idx"]
    direction = "under" if my_idx < 0.67 else "over" if my_idx > 1.5 else "in_line"
    metric = {"youtube": "مشاهدة", "x": "مرة ظهور"}.get(me["platform"], "تفاعل")
    drivers: list[dict[str, Any]] = []

    def effect(with_attr: list[dict[str, Any]], without: list[dict[str, Any]]) -> float | None:
        if len(with_attr) < MIN_GROUP or len(without) < MIN_GROUP:
            return None
        ref = _median([r["idx"] for r in without])
        return _median([r["idx"] for r in with_attr]) / ref if ref else None

    # 1) Burst: a series posted back to back.
    if me["burst_rank"] >= 1:
        leader = me["burst_leader"]
        size = sum(1 for r in rows if r["burst_leader"] is leader)
        hist = effect([r for r in peers if r["burst_rank"] >= 1], [r for r in peers if r["burst_rank"] == 0])
        drop = (me["value"] or 0) / leader["value"] if leader["value"] else None
        if (hist is not None and hist <= HURTS) or (drop is not None and drop <= 0.5):
            drivers.append({
                "kind": "burst",
                "effect": hist if hist is not None else drop,
                "reason": (
                    f"نُشر ضمن دفعة من {size} منشورات للحساب خلال دقائق (ترتيبه {me['burst_rank'] + 1}): المنصة دفعت المنشور الأول "
                    f"({_fmt(leader['value'])} {metric}) وتنافست البقية على نفس الجمهور، فحقق هذا {_fmt(me['value'])} فقط."
                    + (f" وتاريخياً المنشورات التالية في الدفعات على هذا الحساب تحقق {_times(hist)} من المنشورات المنفردة." if hist else "")
                ),
                "metric": f"{_fmt(me['value'])} مقابل {_fmt(leader['value'])} لأول منشور في الدفعة"
                + (f"؛ أثر تاريخي {hist:.2f}× (n={sum(1 for r in peers if r['burst_rank'] >= 1)})" if hist else ""),
                "evidence": leader,
                "decision": f"لا تنشر السلسلة دفعة واحدة: اجمعها في ثريد أو منشور واحد (ألبوم)، أو وزّعها بفاصل ساعة على الأقل بين كل منشور.",
            })

    # The other levers are measured on posts that weren't the tail of a burst, so a burst
    # isn't counted twice (e.g. a time slot looking bad only because a series filled it).
    clean = [r for r in peers if r["burst_rank"] == 0]

    # 2) Crowding: many posts around it (only when it isn't already explained as a burst).
    if not any(d["kind"] == "burst" for d in drivers) and len(clean) >= 2 * MIN_GROUP:
        peers_c = clean
        crowd_cut = sorted(r["crowd"] for r in peers_c)[int(len(peers_c) * 0.75)]
        if me["crowd"] > max(crowd_cut, 2):
            hist = effect([r for r in peers_c if r["crowd"] > crowd_cut], [r for r in peers_c if r["crowd"] <= crowd_cut])
            if hist is not None and hist <= HURTS:
                drivers.append({
                    "kind": "crowding",
                    "effect": hist,
                    "reason": f"نُشر وسط زحمة: {me['crowd']} منشوراً آخر من نفس الحساب خلال ±{CROWD_WINDOW_H} ساعات، والمنشورات المزدحمة على هذا الحساب تحقق {_times(hist)} من غيرها.",
                    "metric": f"{me['crowd']} منشوراً حوله مقابل {crowd_cut} أو أقل عادةً؛ أثر تاريخي {hist:.2f}×",
                    "evidence": max((r for r in peers_c if r["crowd"] <= crowd_cut), key=lambda r: r["idx"]),
                    "decision": f"خفّف كثافة النشر: لا أكثر من {max(crowd_cut, 1)} منشورات خلال {CROWD_WINDOW_H} ساعات على هذا الحساب.",
                })

    # 3) Time of day (band, any day - enough posts per band to judge).
    by_slot: dict[str, list[dict[str, Any]]] = {}
    for r in clean:
        by_slot.setdefault(r["band"], []).append(r)
    slots = {k: _median([r["idx"] for r in v]) for k, v in by_slot.items() if len(v) >= MIN_GROUP}
    mine_slot = me["band"]
    if slots and mine_slot in slots:
        best_slot = max(slots, key=slots.get)
        ratio = slots[mine_slot] / slots[best_slot] if slots[best_slot] else None
        label = _BAND_LABEL[best_slot]
        if ratio is not None and best_slot != mine_slot and ratio <= HURTS and direction != "over":
            drivers.append({
                "kind": "timing",
                "effect": ratio,
                "reason": f"وقت النشر ({_BAND_LABEL[me['band']]}) يحقق على هذا الحساب {_times(ratio)} من أفضل فترة له ({label}).",
                "metric": f"وسيط {slots[mine_slot]:.2f}× مقابل {slots[best_slot]:.2f}× من المعتاد (n={len(by_slot[mine_slot])} و{len(by_slot[best_slot])})",
                "evidence": max(by_slot[best_slot], key=lambda r: r["idx"]),
                "decision": f"انشر المحتوى المشابه {label} بتوقيت الرياض.",
            })

    # 4) Format.
    by_type: dict[str, list[dict[str, Any]]] = {}
    for r in clean:
        by_type.setdefault(r["content_type"], []).append(r)
    types = {t: _median([r["idx"] for r in v]) for t, v in by_type.items() if len(v) >= MIN_GROUP}
    if me["content_type"] in types and len(types) >= 2:
        best_type = max(types, key=types.get)
        ratio = types[me["content_type"]] / types[best_type] if types[best_type] else None
        if ratio is not None and best_type != me["content_type"] and ratio <= HURTS and direction != "over":
            drivers.append({
                "kind": "format",
                "effect": ratio,
                "reason": f"نوع المحتوى ({CONTENT_TYPE_AR.get(me['content_type'], me['content_type'])}) يحقق على هذا الحساب {_times(ratio)} من {CONTENT_TYPE_AR.get(best_type, best_type)}.",
                "metric": f"وسيط {types[me['content_type']]:.2f}× مقابل {types[best_type]:.2f}× من المعتاد (n={len(by_type[me['content_type']])} و{len(by_type[best_type])})",
                "evidence": max(by_type[best_type], key=lambda r: r["idx"]),
                "decision": f"قدّم المحتوى المشابه بصيغة {CONTENT_TYPE_AR.get(best_type, best_type)}.",
            })

    drivers.sort(key=lambda d: d["effect"])  # the costliest first
    return {"baseline": baseline, "index": my_idx, "direction": direction, "metric": metric, "drivers": drivers,
            "n_history": len(peers)}
