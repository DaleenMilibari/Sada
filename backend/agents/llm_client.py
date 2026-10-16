"""Shared, lazily-initialized Gemini client for the agents that use one.

Kept out of behavior_analysis_agent.py and live_clip_detection_agent.py
deliberately - those two are pure statistics over the seeded data and
never need an API key.

GEMINI_API_KEY may hold several comma-separated keys. When a key hits its quota
(HTTP 429), the next key is tried; when every key is exhausted on GEMINI_MODEL,
the same keys are tried on GEMINI_FALLBACK_MODEL (a separate free-tier quota).
An exhausted key/model pair is skipped for EXHAUSTED_COOLDOWN_S, so a live demo
doesn't pay a failed round-trip on every request.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

logger = logging.getLogger("sada.llm")

_ENV_PATH = Path(__file__).parent.parent / ".env"
_clients: dict[str, object] = {}
_exhausted: dict[tuple[str, str], float] = {}  # (key, model) -> monotonic time it ran out
_lock = threading.Lock()
EXHAUSTED_COOLDOWN_S = 3600


class MissingApiKeyError(RuntimeError):
    """Raised when an LLM-backed step is invoked without GEMINI_API_KEY set."""


class QuotaExhaustedError(RuntimeError):
    """Every configured key is out of quota on every configured model."""


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        # load_dotenv() with no path only searches upward from the
        # current working directory, which never finds backend/.env
        # when the server is started from the repo root (as documented
        # in backend/README.md and NEXT_STEPS.md) - point it explicitly.
        load_dotenv(dotenv_path=_ENV_PATH)
    except ImportError:
        pass


def get_keys() -> list[str]:
    _load_env()
    keys = [k.strip() for k in os.environ.get("GEMINI_API_KEY", "").split(",") if k.strip()]
    if not keys:
        raise MissingApiKeyError(
            "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill in a key, or export it in your shell."
        )
    return keys


def _client_for(key: str):
    with _lock:
        if key not in _clients:
            from google import genai

            _clients[key] = genai.Client(api_key=key)
        return _clients[key]


def get_client():
    """Client for the first configured key (kept for callers that need the raw SDK)."""
    return _client_for(get_keys()[0])


def get_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def get_models() -> list[str]:
    fallback = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite")
    models = [get_model()]
    if fallback and fallback not in models:
        models.append(fallback)
    return models


def _is_quota_error(e: Exception) -> bool:
    return getattr(e, "code", None) == 429 or "RESOURCE_EXHAUSTED" in str(e)


def generate_json(prompt: str) -> str:
    """Call Gemini constrained to JSON output and return the raw text, rotating keys/models on quota errors."""
    from google.genai import types

    keys = get_keys()
    now = time.monotonic()
    last: Exception | None = None
    for model in get_models():
        for key in keys:
            ran_out = _exhausted.get((key, model))
            if ran_out is not None and now - ran_out < EXHAUSTED_COOLDOWN_S:
                continue
            try:
                response = _client_for(key).models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(response_mime_type="application/json"),
                )
                return response.text
            except Exception as e:
                if not _is_quota_error(e):
                    raise
                logger.warning("Gemini quota exhausted for key #%d on %s - trying the next one", keys.index(key) + 1, model)
                _exhausted[(key, model)] = time.monotonic()
                last = e
    raise QuotaExhaustedError(f"All Gemini keys are out of quota on {', '.join(get_models())}: {last}")
