"""Shared, lazily-initialized Gemini client for the agents that use one.

Kept out of behavior_analysis_agent.py and live_clip_detection_agent.py
deliberately - those two are pure statistics over the seeded data and
never need an API key.

GEMINI_API_KEY may hold several comma-separated keys. When a key hits its quota
(HTTP 429) - or a model isn't offered to that key's project (HTTP 404, e.g. older
models are closed to new accounts) - the next key is tried; when every key is
exhausted on GEMINI_MODEL, the keys are tried on each GEMINI_FALLBACK_MODEL in order
(comma-separated; each has its own free-tier quota).
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
# One Gemini request may take at most this long; the whole key/model rotation at most
# DEADLINE_S, so an API request never hangs on a slow or stuck model.
REQUEST_TIMEOUT_S = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "30"))
DEADLINE_S = float(os.environ.get("GEMINI_DEADLINE_SECONDS", "60"))


class MissingApiKeyError(RuntimeError):
    """Raised when an LLM-backed step is invoked without GEMINI_API_KEY set."""


class QuotaExhaustedError(RuntimeError):
    """Every configured key is out of quota on every configured model."""


class DeadlineExceededError(RuntimeError):
    """The key/model rotation ran past DEADLINE_S without an answer."""


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
            from google.genai import types

            _clients[key] = genai.Client(
                api_key=key, http_options=types.HttpOptions(timeout=int(REQUEST_TIMEOUT_S * 1000))
            )
        return _clients[key]


def get_client():
    """Client for the first configured key (kept for callers that need the raw SDK)."""
    return _client_for(get_keys()[0])


def get_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")


DEFAULT_FALLBACKS = "gemini-3.5-flash,gemini-3.5-flash-lite"  # 2.5 models are closed to new keys


def get_models() -> list[str]:
    models = [get_model()]
    for m in os.environ.get("GEMINI_FALLBACK_MODEL", DEFAULT_FALLBACKS).split(","):
        if m.strip() and m.strip() not in models:
            models.append(m.strip())
    return models


OVERLOAD_RETRIES = 2
OVERLOAD_BACKOFF_S = 2.0


def _is_overloaded(e: Exception) -> bool:
    """A temporary capacity spike (500/503/504) or a timed-out request - worth a short retry, then another model."""
    if isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower():
        return True
    return getattr(e, "code", None) in (500, 503, 504) or "UNAVAILABLE" in str(e) or "DEADLINE_EXCEEDED" in str(e)


def _is_unavailable(e: Exception) -> bool:
    """Out of quota (429) or the model isn't offered to this key (404) - try the next key/model."""
    code = getattr(e, "code", None)
    return code in (404, 429) or "RESOURCE_EXHAUSTED" in str(e) or "NOT_FOUND" in str(e)


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
            for attempt in range(OVERLOAD_RETRIES + 1):
                if time.monotonic() - now > DEADLINE_S:
                    raise DeadlineExceededError(f"Gemini did not answer within {DEADLINE_S:.0f}s: {last}")
                try:
                    response = _client_for(key).models.generate_content(
                        model=model,
                        contents=prompt,
                        config=types.GenerateContentConfig(response_mime_type="application/json"),
                    )
                    return response.text
                except Exception as e:
                    last = e
                    if _is_overloaded(e) and attempt < OVERLOAD_RETRIES:
                        time.sleep(OVERLOAD_BACKOFF_S * (attempt + 1))  # temporary spike: same key/model again
                        continue
                    if not (_is_unavailable(e) or _is_overloaded(e)):
                        raise
                    logger.warning("Gemini key #%d unavailable on %s (%s) - trying the next one", keys.index(key) + 1, model, getattr(e, "code", "?"))
                    if _is_unavailable(e):  # quota / not offered: skip for the cooldown; overload: just move on this time
                        _exhausted[(key, model)] = time.monotonic()
                    break
    raise QuotaExhaustedError(f"No Gemini key/model could serve the request ({', '.join(get_models())}): {last}")
