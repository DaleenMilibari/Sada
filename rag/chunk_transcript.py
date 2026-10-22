#!/usr/bin/env python3
"""
Convert a UniScribe timestamped CSV export into RAG-ready JSON chunks.

Usage:
    python chunk_transcript.py <csv_path> --podcast "اسم البودكاست" --episode "اسم الحلقة" --url "https://www.youtube.com/watch?v=XXXX" --out chunks.json

Each output chunk looks like:
{
  "podcast": "...",
  "episode": "...",
  "youtube_url": "https://www.youtube.com/watch?v=XXXX",
  "start_time": "00:04:12.339",
  "end_time": "00:04:38.120",
  "start_seconds": 252,
  "clip_url": "https://www.youtube.com/watch?v=XXXX&t=252s",
  "text": "..."
}

Notes:
- Drops rows with empty timestamps (UniScribe watermark/footer lines).
- Skips rows whose text is just a UniScribe branding message.
- Converts HH:MM:SS.mmm -> integer seconds for start_seconds (used to build
  a clickable "jump to this moment" YouTube link).
- Does NOT merge overlapping rows (UniScribe's sliding-window overlap is
  left as-is; harmless for embedding, and merging can be added later if
  you want strictly non-overlapping chunks).
"""

import argparse
import csv
import json
import re
import sys


WATERMARK_PATTERNS = [
    "Transcribed by UniScribe",
    "Free users can only transcribe",
]


def parse_timestamp_to_seconds(ts: str) -> int:
    """Convert 'HH:MM:SS.mmm' to integer seconds (floor)."""
    h, m, s = ts.split(":")
    total = int(h) * 3600 + int(m) * 60 + float(s)
    return int(total)


def is_watermark_row(text: str) -> bool:
    return any(pattern in text for pattern in WATERMARK_PATTERNS)


def build_clip_url(base_url: str, start_seconds: int) -> str:
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}t={start_seconds}s"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", help="Path to the UniScribe timestamped CSV export")
    parser.add_argument("--podcast", required=True, help="Podcast name (e.g. 'بودكاست رهان')")
    parser.add_argument("--episode", required=True, help="Episode title (Arabic OK)")
    parser.add_argument("--url", required=True, help="YouTube URL for this episode")
    parser.add_argument("--out", default="chunks.json", help="Output JSON path")
    args = parser.parse_args()

    chunks = []
    skipped_watermark = 0
    skipped_empty_ts = 0

    with open(args.csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        # Normalize header names in case of BOM/whitespace variations
        fieldnames = {name.strip(): name for name in reader.fieldnames or []}
        start_key = fieldnames.get("Start Time")
        end_key = fieldnames.get("End Time")
        text_key = fieldnames.get("Text")

        if not (start_key and end_key and text_key):
            print(f"ERROR: expected columns 'Start Time,End Time,Text', got {reader.fieldnames}", file=sys.stderr)
            sys.exit(1)

        for row in reader:
            start_raw = (row.get(start_key) or "").strip()
            end_raw = (row.get(end_key) or "").strip()
            text = (row.get(text_key) or "").strip()

            if not text:
                continue

            if is_watermark_row(text):
                skipped_watermark += 1
                continue

            if not start_raw or not end_raw:
                skipped_empty_ts += 1
                continue

            try:
                start_seconds = parse_timestamp_to_seconds(start_raw)
            except ValueError:
                skipped_empty_ts += 1
                continue

            chunk = {
                "podcast": args.podcast,
                "episode": args.episode,
                "youtube_url": args.url,
                "start_time": start_raw,
                "end_time": end_raw,
                "start_seconds": start_seconds,
                "clip_url": build_clip_url(args.url, start_seconds),
                "text": text,
            }
            chunks.append(chunk)

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)

    print(f"Wrote {len(chunks)} chunks to {args.out}")
    print(f"Skipped {skipped_watermark} watermark rows, {skipped_empty_ts} rows with missing timestamps")


if __name__ == "__main__":
    main()
