"""One-off parser for the real AWJ | Sada podcast/X dataset.

Reads backend/data/raw/awj_sada_data.json (a copy of the verified AWJ | Sada
data package - see ../../newData/README_AWJ_Sada.txt for the collection
scope and data-quality policy) and writes awj_sada_real.json: a small
analysis-ready aggregate over real podcast episodes (رهان, SO) and their X
reach, grouped by podcast and by X-account relationship (official vs.
related amplification).

Unlike engagement_records.json (75 synthetic per-post records), this source
has only 6 episodes and 5 X posts - far too few for the Welch-t-test
pipeline in analyze(). It feeds a separate descriptive path
(analyze_real_awj_sada in behavior_analysis_agent.py), the same way
hajj_1445_platform_totals.json feeds analyze_real_hajj_platforms, tagged
source="real_awj_sada" rather than mixed into the synthetic patterns.

Run with `python -m backend.data.parse_awj_sada_real_data` from the repo root.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).parent
RAW_PATH = DATA_DIR / "raw" / "awj_sada_data.json"
OUT_PATH = DATA_DIR / "awj_sada_real.json"


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 1) if values else None


def _summarize_podcast(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    views = [e["youtube_views"] for e in episodes if e.get("youtube_views") is not None]
    likes = [e["youtube_likes"] for e in episodes if e.get("youtube_likes") is not None]
    return {
        "episode_count": len(episodes),
        "episode_keys": [e["episode_key"] for e in episodes],
        "youtube_views_reported": len(views),
        "avg_youtube_views": _mean(views),
        "avg_youtube_likes": _mean(likes),
    }


def _summarize_relationship(posts: list[dict[str, Any]]) -> dict[str, Any]:
    views = [p["views"] for p in posts if p.get("views") is not None]
    likes = [p["likes"] for p in posts if p.get("likes") is not None]
    reposts = [p["reposts"] for p in posts if p.get("reposts") is not None]
    return {
        "post_count": len(posts),
        "record_ids": [p["record_id"] for p in posts],
        "avg_views": _mean(views),
        "avg_likes": _mean(likes),
        "avg_reposts": _mean(reposts),
    }


def parse(raw_path: Path = RAW_PATH) -> dict[str, Any]:
    raw = json.loads(raw_path.read_text(encoding="utf-8"))

    episodes_by_podcast: dict[str, list[dict[str, Any]]] = {}
    for ep in raw.get("episodes", []):
        episodes_by_podcast.setdefault(ep["podcast"], []).append(ep)
    podcasts = {name: _summarize_podcast(eps) for name, eps in episodes_by_podcast.items()}

    posts_by_relationship: dict[str, list[dict[str, Any]]] = {}
    for post in raw.get("x_posts", []):
        posts_by_relationship.setdefault(post["relationship"], []).append(post)
    x_by_relationship = {rel: _summarize_relationship(posts) for rel, posts in posts_by_relationship.items()}

    return {
        "source": {
            "title_ar": "بيانات أوج | صدى - حلقات رهان وSO وتفاعل X",
            "raw_file": "raw/awj_sada_data.json",
            "note": (
                "Real verified data: 6 podcast episodes (3 رهان + 3 SO) and "
                "5 publicly recovered X posts. No fabricated metrics or "
                "reply text - see newData/README_AWJ_Sada.txt for the "
                "collection policy. Far too few records for the "
                "Welch-t-test pipeline in analyze(); feeds "
                "analyze_real_awj_sada instead."
            ),
        },
        "podcasts": podcasts,
        "x_by_relationship": x_by_relationship,
        "audience_signals": raw.get("audience_signals", []),
    }


def main() -> None:
    result = parse()
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    n_podcasts = len(result["podcasts"])
    n_rel = len(result["x_by_relationship"])
    print(f"Wrote {OUT_PATH.name} with {n_podcasts} podcast(s), {n_rel} X relationship group(s).")


if __name__ == "__main__":
    main()
