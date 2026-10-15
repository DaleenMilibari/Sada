"""In-memory sliding-window rate limiter.

Sufficient for a single Render instance. If the service is ever scaled to
multiple instances, move this to Redis so the budget is shared.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from backend import config
from backend.auth import client_ip


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: float = 60.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = int(self.window - (now - hits[0])) + 1
                raise HTTPException(
                    status_code=429,
                    detail="Too many requests, slow down.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


llm_limiter = SlidingWindowLimiter(config.LLM_RATE_LIMIT_PER_MINUTE)
login_limiter = SlidingWindowLimiter(config.LOGIN_RATE_LIMIT_PER_MINUTE)


def limit_llm(request: Request) -> None:
    """Dependency for Gemini-backed endpoints - keyed per client IP so re-logging in can't reset the budget."""
    llm_limiter.check(client_ip(request))


def limit_login(request: Request) -> None:
    login_limiter.check(client_ip(request))
