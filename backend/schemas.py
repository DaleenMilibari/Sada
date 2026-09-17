"""Pydantic models for the JSON shapes documented in team.md.

Field names here are load-bearing: the "Shared rules" section of team.md
requires every agent to use the exact field names it documents so the four
tasks stay independent of each other's in-progress code. Do not rename.
"""

from __future__ import annotations

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
    # Additive metadata (not in team.md's minimal shape) so Tasks 2/3 can
    # match a pattern programmatically instead of parsing the Arabic text.
    dimension: Literal["content_type", "timing", "topic_platform"]
    slice_key: str
    lift_pct: float


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


class RankedAlternative(BaseModel):
    variant: str
    platform: str
    time_window: str
    predicted_engagement: float
    evidence: list[str]


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
