"""Database layer (SQLAlchemy Core) for collected platform data.

One set of tables for every platform: `channels` holds YouTube channels *and*
Instagram accounts, `videos` holds YouTube videos *and* Instagram posts, told
apart by the `platform` column.

Postgres in production (Render's DATABASE_URL), SQLite locally. Tables are
created on startup with create_all - there are no migrations yet, so schema
changes to existing columns need a manual ALTER or a fresh database.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    inspect,
)
from sqlalchemy.engine import Connection, Engine

from backend import config

metadata = MetaData()

# BIGINT primary keys don't auto-increment on SQLite; INTEGER does.
_AutoId = BigInteger().with_variant(Integer, "sqlite")

channels = Table(
    "channels",
    metadata,
    Column("channel_id", String(64), primary_key=True),
    # "youtube" | "instagram" | "x"
    Column("platform", String(16), nullable=False, default="youtube"),
    # Which SBA entity (backend/sba_channels.py) - unique per platform.
    Column("entity_key", String(40), nullable=False),
    Column("handle", String(100), nullable=False),
    Column("name_ar", String(200), nullable=False),
    Column("title", String(300)),
    Column("uploads_playlist_id", String(64)),
    Column("subscriber_count", BigInteger),
    Column("video_count", BigInteger),
    Column("view_count", BigInteger),
    Column("updated_at", DateTime(timezone=True)),
    UniqueConstraint("platform", "entity_key", name="uq_channels_platform_entity"),
)

videos = Table(
    "videos",
    metadata,
    Column("video_id", String(32), primary_key=True),
    Column("platform", String(16), nullable=False, default="youtube", index=True),
    Column("channel_id", String(64), ForeignKey("channels.channel_id"), nullable=False, index=True),
    # YouTube: video title. Instagram: caption.
    Column("title", Text, nullable=False),
    # Permalink. NULL for rows collected before this column existed - repository derives YouTube URLs.
    Column("url", String(300)),
    Column("published_at", DateTime(timezone=True), nullable=False, index=True),
    Column("duration_seconds", Integer),
    # "short" | "video" | "live" | "image" | "carousel" | "text" (X posts without media)
    Column("content_type", String(16), nullable=False),
    Column("topic", String(32), nullable=False),
    # "rule" | "llm"
    Column("topic_source", String(16), nullable=False),
    # NULL for Instagram posts: the API doesn't expose other accounts' views.
    Column("view_count", BigInteger),
    # Null when the channel hides likes / disables comments - never treat as 0.
    Column("like_count", BigInteger),
    Column("comment_count", BigInteger),
    Column("first_seen_at", DateTime(timezone=True), nullable=False),
    Column("stats_updated_at", DateTime(timezone=True), index=True),
)

video_snapshots = Table(
    "video_snapshots",
    metadata,
    Column("id", _AutoId, primary_key=True, autoincrement=True),
    Column("video_id", String(32), ForeignKey("videos.video_id"), nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("view_count", BigInteger),
    Column("like_count", BigInteger),
    Column("comment_count", BigInteger),
    Index("ix_video_snapshots_video_captured", "video_id", "captured_at"),
)

# Audience voice: public comments (YouTube) and replies (X) on SBA posts, for aggregate
# sentiment/intent analysis (backend/agents/audience_agent.py). No author name, handle or id
# is stored - only what was said - so nothing here identifies or profiles a person (PDPL).
audience_comments = Table(
    "audience_comments",
    metadata,
    Column("comment_id", String(64), primary_key=True),
    Column("platform", String(16), nullable=False, index=True),
    Column("video_id", String(32), ForeignKey("videos.video_id"), nullable=False, index=True),
    Column("text", Text, nullable=False),
    Column("published_at", DateTime(timezone=True), nullable=False, index=True),
    Column("like_count", BigInteger),
    Column("collected_at", DateTime(timezone=True), nullable=False),
    # Filled by the audience agent (Gemini). NULL = not classified yet - never treated as neutral.
    # "positive" | "negative" | "neutral"
    Column("sentiment", String(16)),
    # "praise" | "criticism" | "request" | "question" | "reaction" (to the news itself, not SBA) | "other"
    Column("intent", String(16)),
    Column("classified_at", DateTime(timezone=True)),
)

# The LLM wording of a post's diagnosis, kept while the evidence behind it is unchanged
# (diagnostic_recommendation_agent.diagnose_video): re-opening an alert costs no model call.
diagnoses = Table(
    "diagnoses",
    metadata,
    Column("video_id", String(32), ForeignKey("videos.video_id"), primary_key=True),
    Column("evidence_hash", String(40), nullable=False),  # sha1 of the factors the wording was built from
    Column("diagnosis", Text, nullable=False),
    Column("recommendations", Text, nullable=False),  # JSON list of strings
    Column("model", String(60)),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

# Blind human labels for a sample of audience comments - the ground truth that the
# agent's classification accuracy is measured against (audience_agent.accuracy()).
audience_labels = Table(
    "audience_labels",
    metadata,
    Column("comment_id", String(64), ForeignKey("audience_comments.comment_id"), primary_key=True),
    Column("sentiment", String(16), nullable=False),
    Column("intent", String(16), nullable=False),
    Column("labeled_at", DateTime(timezone=True), nullable=False),
)

# Follower/subscriber count per account over time (the channels table keeps only the latest).
follower_snapshots = Table(
    "follower_snapshots",
    metadata,
    Column("id", _AutoId, primary_key=True, autoincrement=True),
    Column("channel_id", String(64), ForeignKey("channels.channel_id"), nullable=False),
    Column("captured_at", DateTime(timezone=True), nullable=False),
    Column("followers", BigInteger, nullable=False),
    Index("ix_follower_snapshots_channel_captured", "channel_id", "captured_at"),
)

collector_runs = Table(
    "collector_runs",
    metadata,
    Column("id", _AutoId, primary_key=True, autoincrement=True),
    # "scheduled" | "manual" | "cli"
    Column("trigger", String(16), nullable=False),
    # "running" | "success" | "partial" | "failed" | "skipped"
    Column("status", String(16), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False, index=True),
    Column("finished_at", DateTime(timezone=True)),
    Column("new_videos", Integer, default=0),
    Column("updated_videos", Integer, default=0),
    Column("snapshots", Integer, default=0),
    Column("llm_classified", Integer, default=0),
    Column("quota_units", Integer, default=0),
    Column("instagram_calls", Integer, default=0),
    Column("error", Text),
)


def _normalize_url(url: str) -> str:
    # Render/Heroku hand out postgres:// or postgresql:// - SQLAlchemy needs the psycopg (v3) driver named.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


_engine: Engine | None = None


def make_engine(url: str) -> Engine:
    url = _normalize_url(url)
    if url.startswith("sqlite"):
        from pathlib import Path

        db_path = url.split("///", 1)[-1]
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = make_engine(config.DATABASE_URL)
    return _engine


def set_engine(engine: Engine) -> None:
    """Swap the process-wide engine (tests)."""
    global _engine
    _engine = engine


class SchemaOutdated(RuntimeError):
    pass


def init_db(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    metadata.create_all(engine)
    # create_all never alters existing tables - fail loudly if one predates a new column.
    inspector = inspect(engine)
    for table in metadata.sorted_tables:
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        missing = [c.name for c in table.columns if c.name not in existing]
        if missing:
            raise SchemaOutdated(
                f"Table '{table.name}' is missing column(s) {missing}. Locally: delete backend/store/sada.db "
                "and re-import the seed (python -m backend.db_tools import backend/data/sba_youtube_seed.json.gz)."
            )


def record_followers(conn: Connection, rows: Iterable[dict[str, Any]], now: datetime) -> None:
    """Append a follower snapshot for each channel row that exposes a count."""
    snaps = [
        {"channel_id": r["channel_id"], "captured_at": now, "followers": r["subscriber_count"]}
        for r in rows
        if r.get("subscriber_count") is not None
    ]
    if snaps:
        from sqlalchemy import insert

        conn.execute(insert(follower_snapshots), snaps)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; everything we store is UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def upsert(conn: Connection, table: Table, rows: Iterable[dict[str, Any]], key: str, update_cols: list[str]) -> None:
    rows = list(rows)
    if not rows:
        return
    if conn.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    stmt = insert(table)
    stmt = stmt.on_conflict_do_update(
        index_elements=[key], set_={c: getattr(stmt.excluded, c) for c in update_cols}
    )
    conn.execute(stmt, rows)
