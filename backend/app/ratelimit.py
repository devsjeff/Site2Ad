"""Small in-memory sliding-window rate limiter keyed by client id (usually the IP)."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    """Allow at most `limit` calls per `window` seconds for each key."""

    def __init__(self, limit: int, window: float = 60.0):
        """A limit of 0 or less disables limiting."""
        self.limit = limit
        self.window = window
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Record a hit and return False when the key is over its limit."""
        if self.limit <= 0:
            return True
        now = time.monotonic()
        hits = self._hits[key]
        while hits and hits[0] <= now - self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        if len(self._hits) > 10_000:
            self._prune(now)
        return True

    def _prune(self, now: float) -> None:
        """Drop keys with no recent hits so memory stays bounded."""
        for key in [k for k, v in self._hits.items() if not v or v[-1] <= now - self.window]:
            self._hits.pop(key, None)
