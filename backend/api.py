"""FastAPI layer exposing the four agents from AGENT_SPEC.md over HTTP.

Production concerns handled here: shared-password auth on every /api route
(see backend/auth.py), per-client rate limiting on the Gemini-backed routes
(see backend/rate_limit.py), env-driven CORS, a public /health probe, and
building the pattern store on startup so a fresh deploy serves patterns
immediately. When enabled, the Data Collector agent also runs on an
in-process schedule (single instance only - see DEPLOYMENT.md).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import analytics, auth, config, db, draft_suggest, playbook, repository, topics
from backend.agents import (
    audience_agent,
    behavior_analysis_agent,
    anomaly_agent,
    content_optimizer_agent,
    data_collector_agent,
    diagnostic_recommendation_agent,
    live_clip_detection_agent,
    llm_client,
    trend_prediction_agent,
)
from backend.rate_limit import limit_llm, limit_login
from backend.schemas import (
    DraftSuggestion,
    DraftSuggestRequest,
    Playbook,
    AudienceAccuracy,
    AudienceThemes,
    AudienceSummary,
    ReviewItem,
    ReviewLabel,
    Alert,
    AnalyticsSummary,
    VideoDiagnosisRequest,
    AwjDiagnosisRequest,
    BroadcastSignalPoint,
    BroadcastSnapshot,
    ChannelOut,
    ClipOpportunity,
    CollectorStatus,
    DraftContent,
    OptimizationResult,
    Pattern,
    PublishedItemMetrics,
    DiagnosisResult,
    ModelAccuracy,
    TrendingItem,
    VideoDetail,
    VideoPage,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sada.api")


def _collector_configured() -> bool:
    return bool(config.YOUTUBE_API_KEY or config.INSTAGRAM_ENABLED or config.X_ENABLED)


async def _collector_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(data_collector_agent.run, "scheduled")
        except Exception:
            logger.exception("Scheduled collector run crashed")
        await asyncio.sleep(config.COLLECTOR_INTERVAL_MINUTES * 60)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.validate()
    db.init_db()
    topics.migrate_taxonomy()  # no-op once the stored posts use the current taxonomy
    store = behavior_analysis_agent.load_store()
    # Rebuild when empty, or when written before patterns carried their dashboard fields.
    if not store or any("title" not in p or "computed_at" not in p or ("q_value" in p and "accounts_total" not in p) for p in store):
        patterns = behavior_analysis_agent.run()
        logger.info("Pattern store was empty or outdated - built %d pattern(s) on startup.", len(patterns))
    collector_task = None
    if config.COLLECTOR_SCHEDULE_ENABLED and _collector_configured():
        collector_task = asyncio.create_task(_collector_loop())
    logger.info(
        "Sada API started (env=%s, auth=%s, cors=%s, db=%s, collector schedule=%s)",
        config.ENV,
        "on" if config.AUTH_ENABLED else "OFF",
        config.CORS_ORIGINS,
        db.get_engine().dialect.name,
        f"every {config.COLLECTOR_INTERVAL_MINUTES} min" if collector_task else "off",
    )
    yield
    if collector_task:
        collector_task.cancel()
        with suppress(asyncio.CancelledError):
            await collector_task


app = FastAPI(
    title="Sada Agent API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if config.IS_PRODUCTION else "/docs",
    redoc_url=None,
    openapi_url=None if config.IS_PRODUCTION else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


def _run_llm_step(fn, *args):
    """Map LLM failures to clean HTTP errors instead of a bare 500."""
    try:
        return fn(*args)
    except llm_client.MissingApiKeyError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except llm_client.DeadlineExceededError:
        logger.warning("LLM-backed step %s timed out", getattr(fn, "__qualname__", fn))
        raise HTTPException(status_code=504, detail="The AI model took too long to answer. Please try again.")
    except Exception:
        logger.exception("LLM-backed step %s failed", getattr(fn, "__qualname__", fn))
        raise HTTPException(status_code=502, detail="The AI model request failed. Please try again.")


# ---------------------------------------------------------------------------
# Public routes
# ---------------------------------------------------------------------------


@app.get("/health")
def health():
    return {"status": "ok", "auth": config.AUTH_ENABLED}


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: int


@app.get("/api/auth/status")
def auth_status():
    return {"auth_required": config.AUTH_ENABLED}


@app.post("/api/auth/login", response_model=LoginResponse, dependencies=[Depends(limit_login)])
def login(req: LoginRequest):
    if not config.AUTH_ENABLED:
        token, expires_at = auth.issue_token()
        return LoginResponse(token=token, expires_at=expires_at)
    if not auth.check_password(req.password):
        logger.warning("Failed login attempt")
        raise HTTPException(status_code=401, detail="Incorrect password")
    token, expires_at = auth.issue_token()
    return LoginResponse(token=token, expires_at=expires_at)


# ---------------------------------------------------------------------------
# Authenticated agent routes
# ---------------------------------------------------------------------------

api = APIRouter(prefix="/api", dependencies=[Depends(auth.require_auth)])


@api.post("/patterns/refresh", response_model=list[Pattern])
def refresh_patterns():
    return behavior_analysis_agent.run()


@api.get("/patterns", response_model=list[Pattern])
def get_patterns():
    return behavior_analysis_agent.load_store()


@api.post("/optimize", response_model=OptimizationResult, dependencies=[Depends(limit_llm)])
def optimize_content(draft: DraftContent):
    return _run_llm_step(content_optimizer_agent.run, draft.model_dump())


@api.post("/diagnose", response_model=DiagnosisResult, dependencies=[Depends(limit_llm)])
def diagnose_item(item: PublishedItemMetrics):
    return _run_llm_step(diagnostic_recommendation_agent.run, item.model_dump())


@api.post("/diagnose/awj-sada", response_model=DiagnosisResult, dependencies=[Depends(limit_llm)])
def diagnose_awj_sada(req: AwjDiagnosisRequest):
    return _run_llm_step(diagnostic_recommendation_agent.diagnose_awj_topic, req.topic)


MAX_SIGNAL_POINTS = 20_000  # ~55 hours at a 10 s sampling interval


@api.post("/broadcast/detect-clips", response_model=list[ClipOpportunity])
def detect_clips(signal: list[BroadcastSignalPoint] | None = None):
    if signal is None:
        return live_clip_detection_agent.run()
    if len(signal) > MAX_SIGNAL_POINTS:
        raise HTTPException(status_code=422, detail=f"A signal may have at most {MAX_SIGNAL_POINTS} points.")
    broadcast = live_clip_detection_agent.load_broadcast()
    broadcast["signal"] = [p.model_dump() for p in signal]
    return live_clip_detection_agent.detect_clip_opportunities(broadcast)


@api.get("/broadcast/signal", response_model=BroadcastSnapshot)
def get_broadcast_signal():
    return live_clip_detection_agent.load_broadcast()


# --- Task 5: Data Collector (real SBA YouTube + Instagram data) ---


@api.get("/channels", response_model=list[ChannelOut])
def get_channels(platform: Literal["youtube", "instagram", "x"] | None = None):
    return repository.list_channels(platform)


@api.get("/videos", response_model=VideoPage)
def get_videos(
    platform: Literal["youtube", "instagram", "x"] | None = None,
    channel: str | None = Query(default=None, description="entity_key from backend/sba_channels.py"),
    content_type: Literal["short", "video", "live", "image", "carousel", "text"] | None = None,
    topic: str | None = None,
    days: int | None = Query(default=None, ge=1, le=365),
    sort: Literal["published", "views"] = "published",
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    total, items = repository.list_videos(
        platform=platform, channel=channel, content_type=content_type, topic=topic, days=days, sort=sort, limit=limit, offset=offset
    )
    return VideoPage(total=total, items=items)


@api.get("/videos/{video_id}", response_model=VideoDetail)
def get_video(video_id: str):
    video = repository.get_video(video_id)
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


@api.get("/collector/status", response_model=CollectorStatus)
def get_collector_status():
    return repository.collector_status()


@api.post("/collector/run", status_code=202)
def trigger_collector_run(background_tasks: BackgroundTasks):
    if not _collector_configured():
        raise HTTPException(status_code=503, detail="No data source configured (YOUTUBE_API_KEY / META_ACCESS_TOKEN / X_BEARER_TOKEN).")
    status = repository.collector_status(run_limit=1)
    if status["runs"] and status["runs"][0]["status"] == "running":
        raise HTTPException(status_code=409, detail="A collector run is already in progress.")
    background_tasks.add_task(data_collector_agent.run, "manual")
    return {"status": "started"}



# --- Task 2: Trends & Viral Prediction (YouTube only - needs view counts) ---


@api.get("/trending", response_model=list[TrendingItem])
def get_trending(
    hours: int = Query(default=24, ge=1, le=168, description="Only videos whose views were measured in this window"),
    limit: int = Query(default=10, ge=1, le=50),
):
    return trend_prediction_agent.trending(hours, limit)


@api.get("/model/accuracy", response_model=ModelAccuracy)
def get_model_accuracy():
    return trend_prediction_agent.model_accuracy()


# --- Task 3: Live dashboard & analytics ---


@api.get("/analytics/summary", response_model=AnalyticsSummary)
def get_analytics_summary(
    days: int = Query(default=30, ge=1, le=3650),
    platform: Literal["youtube", "instagram", "x"] | None = None,
):
    return analytics.summary(days, platform)


@api.post("/draft/suggest", response_model=DraftSuggestion, dependencies=[Depends(limit_llm)])
def post_draft_suggest(req: DraftSuggestRequest):
    """A first description for a new post, from SBA's best-performing recent posts on the topic."""
    return draft_suggest.suggest(req.topic, req.content_type, req.channel_options, req.tone)


@api.get("/playbook", response_model=Playbook)
def get_playbook(days: int = Query(default=60, ge=7, le=365)):
    """One complete publishing decision per topic: platform, account, content type, time."""
    return playbook.playbook(days)


# --- Task 4: Spikes, drops & root-cause diagnosis ---


@api.get("/alerts", response_model=list[Alert])
def get_alerts(days: int = Query(default=7, ge=1, le=60)):
    return anomaly_agent.alerts(days)


@api.post("/diagnose/video", response_model=DiagnosisResult, dependencies=[Depends(limit_llm)])
def diagnose_video(req: VideoDiagnosisRequest):
    result = diagnostic_recommendation_agent.diagnose_video(req.video_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return result



# --- Audience analysis ---


@api.get("/audience/summary", response_model=AudienceSummary)
def get_audience_summary(
    days: int = Query(default=30, ge=1, le=3650),
    platform: Literal["youtube", "instagram", "x"] | None = None,
):
    return audience_agent.summary(days, platform)


@api.get("/audience/themes", response_model=AudienceThemes, dependencies=[Depends(limit_llm)])
def get_audience_themes(
    days: int = Query(default=30, ge=1, le=3650),
    platform: Literal["youtube", "instagram", "x"] | None = None,
):
    return audience_agent.themes(days, platform)


@api.get("/audience/accuracy", response_model=AudienceAccuracy)
def get_audience_accuracy():
    return audience_agent.accuracy()


@api.get("/audience/review/next", response_model=list[ReviewItem])
def get_review_queue(limit: int = Query(default=1, ge=1, le=20)):
    return audience_agent.review_queue(limit)


@api.post("/audience/review")
def post_review_label(label: ReviewLabel):
    if not audience_agent.save_label(label.comment_id, label.sentiment, label.intent):
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"saved": True}


app.include_router(api)
