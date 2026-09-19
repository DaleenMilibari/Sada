"""Minimal FastAPI layer exposing the four agents from team.md over HTTP.

This is intentionally thin: no auth, no database, no deployment concerns.
It exists so each agent can be exercised end-to-end (and so the frontend
has something concrete to eventually call) rather than only via direct
Python function calls.
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from backend.agents import (
    behavior_analysis_agent,
    content_optimizer_agent,
    diagnostic_recommendation_agent,
    live_clip_detection_agent,
    llm_client,
)
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

app = FastAPI(title="Sada Agent API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/patterns/refresh", response_model=list[Pattern])
def refresh_patterns():
    return behavior_analysis_agent.run()


@app.get("/api/patterns", response_model=list[Pattern])
def get_patterns():
    return behavior_analysis_agent.load_store()


@app.post("/api/optimize", response_model=OptimizationResult)
def optimize_content(draft: DraftContent):
    try:
        return content_optimizer_agent.run(draft.model_dump())
    except llm_client.MissingApiKeyError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/diagnose", response_model=DiagnosisResult)
def diagnose_item(item: PublishedItemMetrics):
    try:
        return diagnostic_recommendation_agent.run(item.model_dump())
    except llm_client.MissingApiKeyError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/diagnose/awj-sada", response_model=DiagnosisResult)
def diagnose_awj_sada(req: AwjDiagnosisRequest):
    try:
        return diagnostic_recommendation_agent.diagnose_awj_topic(req.topic)
    except llm_client.MissingApiKeyError as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/api/broadcast/detect-clips", response_model=list[ClipOpportunity])
def detect_clips(signal: list[BroadcastSignalPoint] | None = None):
    if signal is None:
        return live_clip_detection_agent.run()
    broadcast = live_clip_detection_agent.load_broadcast()
    broadcast["signal"] = [p.model_dump() for p in signal]
    return live_clip_detection_agent.detect_clip_opportunities(broadcast)


@app.get("/api/broadcast/signal", response_model=BroadcastSnapshot)
def get_broadcast_signal():
    return live_clip_detection_agent.load_broadcast()
