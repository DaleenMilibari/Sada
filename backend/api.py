"""FastAPI layer exposing the four agents from AGENT_SPEC.md over HTTP.

Production concerns handled here: shared-password auth on every /api route
(see backend/auth.py), per-client rate limiting on the Gemini-backed routes
(see backend/rate_limit.py), env-driven CORS, a public /health probe, and
building the pattern store on startup so a fresh deploy serves patterns
immediately.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend import auth, config
from backend.agents import (
    behavior_analysis_agent,
    content_optimizer_agent,
    diagnostic_recommendation_agent,
    live_clip_detection_agent,
    llm_client,
)
from backend.rate_limit import limit_llm, limit_login
from backend.schemas import (
    AwjDiagnosisRequest,
    BroadcastSignalPoint,
    BroadcastSnapshot,
    ClipOpportunity,
    DraftContent,
    OptimizationResult,
    Pattern,
    PublishedItemMetrics,
    DiagnosisResult,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("sada.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.validate()
    if not behavior_analysis_agent.load_store():
        patterns = behavior_analysis_agent.run()
        logger.info("Pattern store was empty - built %d pattern(s) on startup.", len(patterns))
    logger.info(
        "Sada API started (env=%s, auth=%s, cors=%s)",
        config.ENV,
        "on" if config.AUTH_ENABLED else "OFF",
        config.CORS_ORIGINS,
    )
    yield


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


@api.post("/broadcast/detect-clips", response_model=list[ClipOpportunity])
def detect_clips(signal: list[BroadcastSignalPoint] | None = None):
    if signal is None:
        return live_clip_detection_agent.run()
    broadcast = live_clip_detection_agent.load_broadcast()
    broadcast["signal"] = [p.model_dump() for p in signal]
    return live_clip_detection_agent.detect_clip_opportunities(broadcast)


@api.get("/broadcast/signal", response_model=BroadcastSnapshot)
def get_broadcast_signal():
    return live_clip_detection_agent.load_broadcast()


app.include_router(api)
