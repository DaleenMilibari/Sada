"""Task 4 - Live Clip Detection Agent.

Flags real-time engagement spikes during a live broadcast that correspond
to specific broadcast segments, as social-clip opportunities. See team.md
for the full spec.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path
from typing import Any

DATA_PATH = Path(__file__).parent.parent / "data" / "broadcast_mock.json"

ROLLING_WINDOW = 12  # ~2 minutes of history at a 10s sampling interval
Z_SCORE_THRESHOLD = 4.5  # how many robust-std-devs above the rolling baseline counts as a spike
MIN_STD_DEV = 1e-6  # guards against flagging a perfectly flat/noise-free signal
MAD_TO_STD = 1.4826  # scales median absolute deviation to be comparable to a std-dev


def load_broadcast(path: Path = DATA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _segment_label(segments: list[dict[str, Any]], timestamp: int) -> str:
    for seg in segments:
        if seg["start_seconds"] <= timestamp < seg["end_seconds"]:
            return seg["label"]
    return "غير محدد"


def _rolling_baseline(signal: list[dict[str, Any]], index: int) -> tuple[float, float] | None:
    """Median/MAD baseline over the trailing window.

    A plain mean/std would get dragged upward the moment a real spike
    starts (since the spike's own early points enter the window), which
    truncates detection of the spike's later points. Median and median
    absolute deviation are robust to the handful of outlier points a
    genuine spike contributes to an otherwise-normal window.
    """
    window_start = max(0, index - ROLLING_WINDOW)
    history = [p["engagement_level"] for p in signal[window_start:index]]
    if len(history) < ROLLING_WINDOW // 2:
        return None  # not enough history yet to trust a baseline
    median = statistics.median(history)
    mad = statistics.median([abs(v - median) for v in history])
    robust_std = mad * MAD_TO_STD or MIN_STD_DEV
    return median, robust_std


def detect_clip_opportunities(broadcast: dict[str, Any]) -> list[dict[str, Any]]:
    signal = broadcast["signal"]
    segments = broadcast["segments"]

    flagged_points: list[dict[str, Any]] = []
    for i, point in enumerate(signal):
        baseline = _rolling_baseline(signal, i)
        if baseline is None:
            continue
        mean, stdev = baseline
        z_score = (point["engagement_level"] - mean) / stdev
        if z_score >= Z_SCORE_THRESHOLD:
            flagged_points.append({**point, "z_score": z_score, "baseline_mean": mean})

    if not flagged_points:
        return []

    # Merge consecutive flagged points (same sampling step apart) into single clip windows.
    groups: list[list[dict[str, Any]]] = []
    step = signal[1]["timestamp_seconds"] - signal[0]["timestamp_seconds"] if len(signal) > 1 else 10
    for point in flagged_points:
        if groups and point["timestamp_seconds"] - groups[-1][-1]["timestamp_seconds"] <= step:
            groups[-1].append(point)
        else:
            groups.append([point])

    opportunities = []
    for group in groups:
        peak = max(group, key=lambda p: p["z_score"])
        start_time = group[0]["timestamp_seconds"]
        end_time = group[-1]["timestamp_seconds"] + step
        magnitude_pct = (peak["engagement_level"] - peak["baseline_mean"]) / peak["baseline_mean"] * 100
        opportunities.append(
            {
                "clip_opportunity": {
                    "start_time": start_time,
                    "end_time": end_time,
                    "segment_label": _segment_label(segments, peak["timestamp_seconds"]),
                    "spike_magnitude": round(magnitude_pct, 1),
                    "confidence": round(min(0.99, 0.5 + min(peak["z_score"], 12) / 20), 2),
                }
            }
        )

    opportunities.sort(key=lambda o: o["clip_opportunity"]["spike_magnitude"], reverse=True)
    return opportunities


def run(data_path: Path = DATA_PATH) -> list[dict[str, Any]]:
    broadcast = load_broadcast(data_path)
    return detect_clip_opportunities(broadcast)


if __name__ == "__main__":
    result = run()
    print(f"Detected {len(result)} clip opportunity(ies).")
    for o in result:
        c = o["clip_opportunity"]
        print(
            f"- [{c['confidence']}] {c['start_time']}s-{c['end_time']}s "
            f"'{c['segment_label']}' (+{c['spike_magnitude']}%)"
        )
