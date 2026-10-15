"""Export / import the collected dataset as a gzipped JSON file.

Lets teammates work on the same real data without each spending YouTube quota:

    python -m backend.db_tools export backend/data/sba_youtube_seed.json.gz
    python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz

Import upserts, so it is safe to run against a database that already has data.
"""

from __future__ import annotations

import argparse
import gzip
import json
from datetime import datetime
from pathlib import Path

from sqlalchemy import DateTime, insert, select

from backend import db

TABLES = [db.channels, db.videos, db.video_snapshots]
KEYS = {"channels": "channel_id", "videos": "video_id"}


def _encode(value):
    return value.isoformat() if isinstance(value, datetime) else value


def export(path: Path) -> dict[str, int]:
    db.init_db()
    payload: dict[str, list[dict]] = {}
    with db.get_engine().connect() as conn:
        for table in TABLES:
            rows = conn.execute(select(table)).mappings()
            payload[table.name] = [
                {k: _encode(db.as_utc(v) if isinstance(v, datetime) else v) for k, v in r.items() if k != "id"}
                for r in rows
            ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return {name: len(rows) for name, rows in payload.items()}


def import_(path: Path) -> dict[str, int]:
    db.init_db()
    with gzip.open(path, "rt", encoding="utf-8") as f:
        payload = json.load(f)
    counts = {}
    with db.get_engine().begin() as conn:
        for table in TABLES:
            date_cols = {c.name for c in table.columns if isinstance(c.type, DateTime)}
            rows = [
                {k: datetime.fromisoformat(v) if k in date_cols and v else v for k, v in r.items()}
                for r in payload.get(table.name, [])
            ]
            if table.name in KEYS:
                key = KEYS[table.name]
                db.upsert(conn, table, rows, key, [c.name for c in table.columns if c.name != key])
            elif rows:
                # Snapshots have no natural key: skip ones already present for the same (video, time).
                existing = {(v, db.as_utc(t)) for v, t in conn.execute(select(table.c.video_id, table.c.captured_at))}
                rows = [r for r in rows if (r["video_id"], r["captured_at"]) not in existing]
                if rows:
                    for i in range(0, len(rows), 5000):
                        conn.execute(insert(table), rows[i : i + 5000])
            counts[table.name] = len(rows)
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["export", "import"])
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    result = export(args.path) if args.action == "export" else import_(args.path)
    print(json.dumps(result))
