"""Rate Limiter — Simple in-memory rate limiting for action executions."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Optional

from fastapi import HTTPException


class RateLimiter:
    """Token bucket rate limiter for action execution.

    Limits the number of executions per action per time window
    to prevent accidental DDoS of target backends.
    """

    def __init__(
        self,
        max_requests: int = 60,
        window_seconds: int = 60,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def check(self, app_id: str, action_id: str) -> None:
        """Check rate limit. Raises HTTPException(429) if exceeded."""
        key = f"{app_id}:{action_id}"
        now = time.time()
        cutoff = now - self.window_seconds

        # Clean old entries
        self._buckets[key] = [t for t in self._buckets[key] if t > cutoff]

        if len(self._buckets[key]) >= self.max_requests:
            raise HTTPException(
                429,
                f"Rate limit exceeded: {self.max_requests} requests per {self.window_seconds}s"
            )

        self._buckets[key].append(now)

    def reset(self, app_id: Optional[str] = None) -> None:
        """Reset rate limit counters."""
        if app_id:
            keys = [k for k in self._buckets if k.startswith(f"{app_id}:")]
            for k in keys:
                del self._buckets[k]
        else:
            self._buckets.clear()
