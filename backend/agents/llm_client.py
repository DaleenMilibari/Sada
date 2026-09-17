"""Shared, lazily-initialized Anthropic client for the agents that use one.

Kept out of behavior_analysis_agent.py and live_clip_detection_agent.py
deliberately - those two are pure statistics over the seeded data and
never need an API key.
"""

from __future__ import annotations

import os

_client = None


class MissingApiKeyError(RuntimeError):
    """Raised when an LLM-backed step is invoked without ANTHROPIC_API_KEY set."""


def get_client():
    global _client
    if _client is None:
        try:
            from dotenv import load_dotenv

            load_dotenv()
        except ImportError:
            pass

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY is not set. Copy backend/.env.example to backend/.env "
                "and fill in a key, or export it in your shell."
            )
        import anthropic

        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def get_model() -> str:
    return os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
