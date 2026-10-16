"""Pydantic models for the JSON shapes documented in AGENT_SPEC.md.

Field names here are load-bearing: the "Shared rules" section of AGENT_SPEC.md
requires every agent to use the exact field names it documents so the four
tasks stay independent of each other's in-progress code. Do not rename.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Task 1 — Behavior Analysis Agent
# ---------------------------------------------------------------------------


class Pattern(BaseModel):
    pattern_id: str
    pattern: str
    supporting_metric: str
    confidence: float
    affected_content_types: list[str]
    # Additive metadata (not in AGENT_SPEC.md's minimal shape) so Tasks 2/3 can
    # match a pattern programmatically instead of parsing the Arabic text.
    # "platform_reach_real" patterns come from real SBA Hajj 1445H season
    # totals (see analyze_real_hajj_platforms), and "awj_sada_real" patterns
    # come from the real AWJ | Sada podcast/X dataset (see
    # analyze_real_awj_sada), rather than the synthetic per-post seed data.
    # Both are descriptive-only - Tasks 2/3 never match against them since
    # drafts/items don't carry the attributes these dimensions describe,
    # they just ride along in the same store.
    # "content_type_real" / "timing_real" / "topic_real" / "channel_topic_real" /
    # "platform_content_real" come from real SBA YouTube + Instagram posts
    # (backend.repository.analysis_records(), see analyze_real_data) scored on
    # performance_index - the per-post-record counterpart to the dimensions
    # above, usable by the optimizer the same way the synthetic ones are.
    dimension: Literal[
        "content_type", "timing", "topic_platform", "platform_reach_real", "awj_sada_real",
        "content_type_real", "timing_real", "topic_real", "channel_topic_real", "platform_content_real",
    ]
    slice_key: str
    lift_pct: float
    source: str = "synthetic_seed_engagement_records"


class EngagementRecord(BaseModel):
    platform: str
    content_type: str
    topic: str
    format: str
    publish_hour: int
    day_of_week: str
    views: int
    likes: int
    shares: int
    watch_time_seconds: float
    drop_off_point_seconds: float | None = None


# ---------------------------------------------------------------------------
# Task 2 — Content & Publishing Optimizer Agent
# ---------------------------------------------------------------------------


class DraftContent(BaseModel):
    content_type: str
    topic: str
    variants: list[str] | None = None
    platform_options: list[str] = Field(default_factory=list)
    # Seed text for LLM variant generation when `variants` is omitted; read by
    # content_optimizer_agent._generate_variants_via_llm via draft.get("original_text").
    original_text: str | None = Field(default=None, max_length=2000)
    # Optional writing tone (e.g. "تفاعلي" / "رسمي" / "إخباري") passed to the
    # LLM variant-generation prompt; ignored when `variants` is supplied.
    tone: str | None = Field(default=None, max_length=40)
    # team.md Task 1 "on real data": optional SBA account entity_keys (see
    # backend/sba_channels.py, GET /api/channels) to recommend a specific
    # account from, additive only - when omitted, behavior is unchanged.
    channel_options: list[str] = Field(default_factory=list)


class RankedAlternative(BaseModel):
    variant: str
    platform: str
    time_window: str
    predicted_engagement: float
    evidence: list[str]
    # Set only when the draft supplied channel_options.
    channel: str | None = None


class OptimizerEvidence(BaseModel):
    pattern_id: str
    pattern: str
    note: str | None = None


class OptimizationResult(BaseModel):
    recommended_variant: str
    predicted_engagement: float
    recommended_platform: str
    recommended_time: str
    ranked_alternatives: list[RankedAlternative]
    evidence: list[OptimizerEvidence]
    low_confidence: bool = False
    # Set only when the draft supplied channel_options (team.md Task 1 "on real data").
    recommended_channel: str | None = None


# ---------------------------------------------------------------------------
# Task 3 — Diagnostic & Recommendation Agent (RAG-grounded)
# ---------------------------------------------------------------------------


class HistoricalContentItem(BaseModel):
    content_id: str
    title: str
    platform: str
    content_type: str
    topic: str
    format: str
    publish_hour: int
    views: int
    likes: int
    shares: int
    watch_time_seconds: float
    url_or_ref: str


class PublishedItemMetrics(BaseModel):
    content_id: str
    title: str
    platform: str
    content_type: str
    topic: str
    format: str
    publish_hour: int
    day_of_week: str = "mon"
    views: int
    likes: int
    shares: int
    watch_time_seconds: float
    predicted_engagement: float | None = None


class ContributingFactor(BaseModel):
    reason: str
    supporting_metric: str
    evidence_source_title: str
    evidence_url_or_ref: str
    confidence: float


class DiagnosisResult(BaseModel):
    diagnosis: str
    contributing_factors: list[ContributingFactor]
    recommendations: list[str]
    low_confidence: bool = False


# Diagnoses grounded in the real AWJ | Sada dataset (backend/data/raw/awj_sada_data.json)
# rather than a PublishedItemMetrics item matched against the synthetic history -
# see diagnostic_recommendation_agent.diagnose_awj_topic.
class AwjDiagnosisRequest(BaseModel):
    topic: Literal["podcast_reach", "x_relationship"]


# ---------------------------------------------------------------------------
# Task 4 — Live Clip Detection Agent
# ---------------------------------------------------------------------------


class BroadcastSignalPoint(BaseModel):
    timestamp_seconds: int
    engagement_level: float


class BroadcastSegment(BaseModel):
    start_seconds: int
    end_seconds: int
    label: str


class ClipOpportunityDetail(BaseModel):
    start_time: int
    end_time: int
    segment_label: str
    spike_magnitude: float
    confidence: float


class ClipOpportunity(BaseModel):
    clip_opportunity: ClipOpportunityDetail


class BroadcastSnapshot(BaseModel):
    signal: list[BroadcastSignalPoint]
    segments: list[BroadcastSegment]


# ---------------------------------------------------------------------------
# Task 5 — Data Collector Agent (real SBA YouTube data, see backend/db.py)
# ---------------------------------------------------------------------------


class ChannelOut(BaseModel):
    channel_id: str
    platform: Literal["youtube", "instagram", "x"]
    entity_key: str
    handle: str
    name_ar: str
    title: str | None = None
    subscriber_count: int | None = None
    video_count: int | None = None
    view_count: int | None = None
    updated_at: datetime | None = None
    tracked_videos: int = 0


class VideoOut(BaseModel):
    """A YouTube video or an Instagram post (see `platform`). `title` is the caption on Instagram."""

    video_id: str
    platform: Literal["youtube", "instagram", "x"]
    channel_id: str
    entity_key: str
    channel_name_ar: str
    title: str
    url: str
    published_at: datetime
    duration_seconds: int | None = None
    content_type: Literal["short", "video", "live", "image", "carousel", "text"]
    topic: str
    topic_source: Literal["rule", "llm"]
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None
    stats_updated_at: datetime | None = None


class VideoPage(BaseModel):
    total: int
    items: list[VideoOut]


class VideoSnapshotOut(BaseModel):
    captured_at: datetime
    view_count: int | None = None
    like_count: int | None = None
    comment_count: int | None = None


class VideoDetail(VideoOut):
    snapshots: list[VideoSnapshotOut]


class CollectorRunOut(BaseModel):
    id: int
    trigger: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    new_videos: int | None = 0
    updated_videos: int | None = 0
    snapshots: int | None = 0
    llm_classified: int | None = 0
    quota_units: int | None = 0
    instagram_calls: int | None = 0
    error: str | None = None


class CollectorStatus(BaseModel):
    enabled: bool
    youtube_enabled: bool
    instagram_enabled: bool
    x_enabled: bool = False
    instagram_calls_last_24h: int
    schedule_enabled: bool
    interval_minutes: int
    lookback_days: int
    total_channels: int
    total_videos: int
    total_snapshots: int
    quota_units_last_24h: int
    runs: list[CollectorRunOut]


# --- Task 2 (team.md): Trends & Viral Prediction ---


class TrendingItem(BaseModel):
    video: VideoOut
    views_per_hour: float
    # views_per_hour / the channel's median for videos of the same age bucket.
    velocity_index: float
    viral_score: float = Field(ge=0, le=1)
    # Null when there isn't enough snapshot history to know the channel's growth curve - never guessed.
    predicted_views_7d: int | None = None
    reason: str


class ModelAccuracy(BaseModel):
    method: str
    # Additive: "insufficient_history" until enough videos have both day-1 and day-7
    # snapshots - the score fields below are then null rather than invented.
    status: Literal["ok", "insufficient_history"] = "ok"
    train_window: str | None = None
    test_window: str | None = None
    n_test: int
    n_eligible: int = 0  # videos with both day-1 and day-7 views measured
    mape: float | None = None  # percent
    baseline_mape: float | None = None  # percent, naive "channel median" baseline
    top10_hit_rate: float | None = None  # 0-1
    beats_baseline: bool | None = None
    computed_at: datetime


# --- Task 3 (team.md): Live dashboard & analytics ---


class AnalyticsTotals(BaseModel):
    posts: int
    views: int  # YouTube views; X impressions when filtered to X. Instagram exposes no views
    likes: int
    comments: int
    engagement_rate: float | None = None  # (likes + comments) / views (YouTube; X impressions when filtered to X)


class PlatformStats(BaseModel):
    platform: Literal["youtube", "instagram", "x"]
    accounts: int
    posts: int
    followers: int
    likes: int
    comments: int


class ChannelStats(BaseModel):
    platform: Literal["youtube", "instagram", "x"]
    entity_key: str
    name_ar: str
    subscriber_count: int | None = None
    posts: int
    views: int | None = None  # YouTube views, X impressions, null on Instagram
    median_performance_index: float
    engagement_rate: float | None = None  # null on Instagram (no views); per impression on X


class ContentTypeStats(BaseModel):
    platform: Literal["youtube", "instagram", "x"]
    content_type: str
    posts: int
    median_performance_index: float


class TopicStats(BaseModel):
    topic: str
    label_ar: str
    posts: int
    median_performance_index: float


class BestTimeCell(BaseModel):
    platform: Literal["youtube", "instagram", "x"]
    day_of_week: Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    hour: int  # Riyadh time, 0-23
    median_performance_index: float
    n: int


class AnalyticsSummary(BaseModel):
    generated_at: datetime
    data_as_of: datetime | None = None  # finish time of the last successful collector run
    days: int
    platform: Literal["youtube", "instagram", "x"] | None = None
    # Posts younger than this are left out (not enough time to accumulate engagement).
    min_post_age_days: float
    totals: AnalyticsTotals
    by_platform: list[PlatformStats]
    by_channel: list[ChannelStats]
    by_content_type: list[ContentTypeStats]
    by_topic: list[TopicStats]
    best_times: list[BestTimeCell]


# --- Task 4 (team.md): Spikes, drops & root-cause diagnosis ---


class Alert(BaseModel):
    alert_id: str
    kind: Literal["spike", "drop"]
    video: VideoOut
    metric: Literal["views", "interactions"]
    # For detection "level": cumulative metric at the post's current age vs the account's typical value
    # at the same age. For "velocity": metric per hour between the latest snapshots vs the previous ones.
    observed: int
    expected: int
    ratio: float
    severity: Literal["high", "medium"]
    detected_at: datetime
    # Additive fields:
    detection: Literal["level", "velocity"] = "level"
    # level: "same_age" (peers' snapshots at this age) | "plateau" (posts >= 7 days old vs peers' current value)
    basis: Literal["same_age", "plateau", "snapshots"] = "same_age"
    peers: int = 0  # comparable posts behind `expected`
    explanation: str = ""


class VideoDiagnosisRequest(BaseModel):
    video_id: str


# --- Audience analysis (backend/agents/audience_agent.py) ---


class SentimentStats(BaseModel):
    comments: int
    classified: int  # classified by the agent; the rest are unclassified, never counted as neutral
    positive: int
    negative: int
    neutral: int
    # Shares over classified comments; null when fewer than 10 are classified.
    positive_share: float | None = None
    negative_share: float | None = None
    net_sentiment: float | None = None  # (positive - negative) / classified, -1..1


class AudienceChannel(SentimentStats):
    platform: Literal["youtube", "instagram", "x"]
    entity_key: str
    name_ar: str


class AudienceExample(BaseModel):
    text: str
    url: str
    platform: Literal["youtube", "instagram", "x"]
    channel_name_ar: str
    like_count: int | None = None
    sentiment: Literal["positive", "negative", "neutral"] | None = None


class AudienceIntent(BaseModel):
    intent: Literal["praise", "criticism", "request", "question", "reaction", "other"]
    label_ar: str
    count: int
    share: float | None = None
    examples: list[AudienceExample]


class DiscussedPost(SentimentStats):
    video: VideoOut


class FollowerPoint(BaseModel):
    at: datetime
    followers: int


class FollowerGrowth(BaseModel):
    platform: Literal["youtube", "instagram", "x"]
    entity_key: str
    name_ar: str
    first_at: datetime
    last_at: datetime
    first: int
    last: int
    change: int | None = None  # null until two measurements at least half a day apart
    change_pct: float | None = None
    points: list[FollowerPoint]


class AudienceSummary(BaseModel):
    generated_at: datetime
    days: int
    platform: Literal["youtube", "instagram", "x"] | None = None
    totals: SentimentStats
    by_channel: list[AudienceChannel]
    intents: list[AudienceIntent]
    discussed_posts: list[DiscussedPost]
    follower_growth: list[FollowerGrowth]
