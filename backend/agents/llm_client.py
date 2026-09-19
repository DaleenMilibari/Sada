"""Shared, lazily-initialized Gemini client for the agents that use one.

Kept out of behavior_analysis_agent.py and live_clip_detection_agent.py
deliberately - those two are pure statistics over the seeded data and
never need an API key.
"""

from __future__ import annotations

import os
from pathlib import Path

_client = None
_ENV_PATH = Path(__file__).parent.parent / ".env"


class MissingApiKeyError(RuntimeError):
    """Raised when an LLM-backed step is invoked without GEMINI_API_KEY set."""


def get_client():
    global _client
    if _client is None:
        try:
            from dotenv import load_dotenv

            # load_dotenv() with no path only searches upward from the
            # current working directory, which never finds backend/.env
            # when the server is started from the repo root (as documented
            # in backend/README.md and NEXT_STEPS.md) - point it explicitly.
            load_dotenv(dotenv_path=_ENV_PATH)
        except ImportError:
            pass

        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise MissingApiKeyError(
                "GEMINI_API_KEY is not set. Copy backend/.env.example to backend/.env "
                "and fill in a key, or export it in your shell."
            )
        from google import genai

        _client = genai.Client(api_key=api_key)
    return _client


def get_model() -> str:
    return os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def generate_json(prompt: str) -> str:
    """Call the configured Gemini model, constrained to JSON output, and return the raw text."""
    from google.genai import types

    response = get_client().models.generate_content(
        model=get_model(),
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return response.text
