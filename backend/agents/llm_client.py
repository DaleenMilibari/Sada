"""Shared, lazily-initialized LLM client (OpenAI and/or Gemini) for the agents that use one.

Kept out of behavior_analysis_agent.py and live_clip_detection_agent.py
deliberately - those two are pure statistics over the seeded data and
never need an API key.

Gemini is tried first; when OPENAI_API_KEY is set, OPENAI_MODEL (then each
OPENAI_FALLBACK_MODEL) is the fallback once every Gemini key/model is unavailable.
With only one provider's key set, that provider alone serves every request.

GEMINI_API_KEY (and OPENAI_API_KEY) may hold several comma-separated keys. When a key hits its quota
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
# One LLM request may take at most this long; the whole key/model rotation at most
# DEADLINE_S, so an API request never hangs on a slow or stuck model.
REQUEST_TIMEOUT_S = float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "30"))
DEADLINE_S = float(os.environ.get("GEMINI_DEADLINE_SECONDS", "60"))


class MissingApiKeyError(RuntimeError):
    """Raised when an LLM-backed step is invoked without OPENAI_API_KEY or GEMINI_API_KEY set."""


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
        # in README.md and backend/README.md) - point it explicitly.
        load_dotenv(dotenv_path=_ENV_PATH)
    except ImportError:
        pass


def _keys(var: str) -> list[str]:
    return [k.strip() for k in os.environ.get(var, "").split(",") if k.strip()]


def get_keys() -> list[str]:
    """Gemini keys (raises only when neither provider has a key)."""
    _load_env()
    keys = _keys("GEMINI_API_KEY")
    if not keys and not _keys("OPENAI_API_KEY"):
        raise MissingApiKeyError(
            "Neither OPENAI_API_KEY nor GEMINI_API_KEY is set. Copy backend/.env.example to "
            "backend/.env and fill in a key, or export it in your shell."
        )
    return keys


def _client_for(key: str):
    with _lock:
        if key not in _clients:
            from google import genai
            from google.genai import types

            # attempts=1: the SDK's own retries would stretch one call past DEADLINE_S;
            # generate_json() does the retrying (other key/model) itself.
            _clients[key] = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(
                    timeout=int(REQUEST_TIMEOUT_S * 1000), retry_options=types.HttpRetryOptions(attempts=1)
                ),
            )
        return _clients[key]


def _openai_client_for(key: str):
    with _lock:
        if ("openai", key) not in _clients:
            from openai import OpenAI

            # max_retries=0 for the same reason as Gemini's attempts=1.
            _clients[("openai", key)] = OpenAI(api_key=key, timeout=REQUEST_TIMEOUT_S, max_retries=0)
        return _clients[("openai", key)]


def get_client():
    """Client for the first configured key (kept for callers that need the raw SDK)."""
    return _client_for(get_keys()[0])


def _gemini_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")


def get_model() -> str:
    """The model that serves requests when nothing is exhausted (recorded next to saved results)."""
    _load_env()
    if not _keys("GEMINI_API_KEY") and _keys("OPENAI_API_KEY"):
        return os.environ.get("OPENAI_MODEL", "gpt-5-mini")
    return _gemini_model()


DEFAULT_FALLBACKS = "gemini-3.5-flash,gemini-3.5-flash-lite"  # 2.5 models are closed to new keys


def _model_list(primary: str, fallbacks: str) -> list[str]:
    models = [primary]
    for m in fallbacks.split(","):
        if m.strip() and m.strip() not in models:
            models.append(m.strip())
    return models


def get_models() -> list[str]:
    """Gemini models in the order they are tried."""
    return _model_list(_gemini_model(), os.environ.get("GEMINI_FALLBACK_MODEL", DEFAULT_FALLBACKS))


def _candidates() -> list[tuple[str, str, str]]:
    """(provider, model, key) in the order they are tried: Gemini first, then OpenAI when configured."""
    gemini_keys = get_keys()
    openai_keys = _keys("OPENAI_API_KEY")
    out = [("gemini", m, k) for m in get_models() for k in gemini_keys]
    if openai_keys:
        models = _model_list(os.environ.get("OPENAI_MODEL", "gpt-5-mini"), os.environ.get("OPENAI_FALLBACK_MODEL", ""))
        out += [("openai", m, k) for m in models for k in openai_keys]
    return out


def _status(e: Exception):
    """HTTP status of an SDK error: Gemini puts it on .code, OpenAI on .status_code (its .code is a string)."""
    for attr in ("status_code", "code"):
        value = getattr(e, attr, None)
        if isinstance(value, int):
            return value
    return None


OVERLOAD_RETRIES = 2
OVERLOAD_BACKOFF_S = 2.0


def _is_overloaded(e: Exception) -> bool:
    """A temporary capacity spike (500/503/504) or a timed-out request - worth a short retry, then another model."""
    if isinstance(e, TimeoutError) or "timeout" in type(e).__name__.lower():
        return True
    return _status(e) in (500, 502, 503, 504) or "UNAVAILABLE" in str(e) or "DEADLINE_EXCEEDED" in str(e)


def _is_unavailable(e: Exception) -> bool:
    """Out of quota (429), a rejected key (401/403) or a model not offered to it (404) - try the next key/model."""
    return _status(e) in (401, 403, 404, 429) or "RESOURCE_EXHAUSTED" in str(e) or "NOT_FOUND" in str(e)


def _call(provider: str, model: str, key: str, prompt: str) -> str:
    if provider == "openai":
        response = _openai_client_for(key).chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content
    from google.genai import types

    response = _client_for(key).models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return response.text


def generate_json(prompt: str) -> str:
    """Call the LLM constrained to JSON output and return the raw text, rotating providers/keys/models on quota errors."""
    candidates = _candidates()
    now = time.monotonic()
    last: Exception | None = None
    for provider, model, key in candidates:
        ran_out = _exhausted.get((key, model))
        if ran_out is not None and now - ran_out < EXHAUSTED_COOLDOWN_S:
            continue
        for attempt in range(OVERLOAD_RETRIES + 1):
            if time.monotonic() - now > DEADLINE_S:
                raise DeadlineExceededError(f"The LLM did not answer within {DEADLINE_S:.0f}s: {last}")
            try:
                return _call(provider, model, key, prompt)
            except Exception as e:
                last = e
                if _is_overloaded(e) and attempt < OVERLOAD_RETRIES:
                    time.sleep(OVERLOAD_BACKOFF_S * (attempt + 1))  # temporary spike: same key/model again
                    continue
                if not (_is_unavailable(e) or _is_overloaded(e)):
                    raise
                logger.warning("%s key unavailable on %s (%s) - trying the next one", provider, model, _status(e) or "?")
                if _is_unavailable(e):  # quota / not offered: skip for the cooldown; overload: just move on this time
                    _exhausted[(key, model)] = time.monotonic()
                break
    tried = ", ".join(dict.fromkeys(m for _, m, _ in candidates))
    raise QuotaExhaustedError(f"No LLM key/model could serve the request ({tried}): {last}")
