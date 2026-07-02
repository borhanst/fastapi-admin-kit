"""In-memory sliding window rate limiter — no external dependencies."""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request


class RateLimiter:
    """Sliding-window rate limiter.

    Tracks request timestamps per key and rejects when the count exceeds
    ``max_attempts`` within ``window_seconds``.
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 900,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def _cleanup(self, key: str, now: float) -> None:
        """Remove expired entries for *key*."""
        cutoff = now - self.window_seconds
        attempts = self._attempts[key]
        self._attempts[key] = [t for t in attempts if t > cutoff]

    def is_rate_limited(self, key: str) -> bool:
        """Return True if *key* has exceeded the allowed attempts."""
        now = time.monotonic()
        with self._lock:
            self._cleanup(key, now)
            if len(self._attempts[key]) >= self.max_attempts:
                return True
            return False

    def record_attempt(self, key: str) -> None:
        """Record a request attempt for *key*."""
        now = time.monotonic()
        with self._lock:
            self._cleanup(key, now)
            self._attempts[key].append(now)

    def reset(self, key: str) -> None:
        """Clear all attempts for *key* (e.g. on successful login)."""
        with self._lock:
            self._attempts.pop(key, None)

    def remaining_seconds(self, key: str) -> int:
        """Seconds until the oldest attempt in the window expires."""
        now = time.monotonic()
        with self._lock:
            self._cleanup(key, now)
            attempts = self._attempts[key]
            if not attempts:
                return 0
            return max(0, int(self.window_seconds - (now - attempts[0])) + 1)


def _client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def check_rate_limit(
    limiter: RateLimiter,
    key: str,
) -> None:
    """Raise 429 if *key* is rate-limited."""
    if limiter.is_rate_limited(key):
        retry = limiter.remaining_seconds(key)
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(retry)},
        )
