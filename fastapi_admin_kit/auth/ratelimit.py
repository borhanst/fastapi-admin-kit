"""Sliding-window rate limiter — no external dependencies.

.. warning::

    **MULTI-WORKER DEPLOYMENTS: the in-memory limiter does NOT work.**
    State lives in this process's memory only. With ``gunicorn -w N``,
    multiple uvicorn workers, or several Kubernetes replicas, every worker
    has its own counters and an attacker gets ``N × max_attempts`` requests
    simply by round-robining across workers.

    For multi-worker production deployments you MUST either:

    - configure Redis (``REDIS_URL``) so the distributed
      :class:`~fastapi_admin_kit.redis.RedisLoginRateGuard` is used, or
    - terminate rate limiting at your gateway / reverse proxy.

    The in-memory implementation is suitable for single-process
    deployments and development only.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from fastapi import HTTPException

from fastapi_admin_kit.auth.proxy import get_client_ip

__all__ = [
    "RateLimiter",
    "check_rate_limit",
    "get_client_ip",
    "_client_ip",  # backward-compatible alias
]

# Backward compatibility: code (and third-party integrations) previously
# imported ``_client_ip`` from this module. It now enforces trusted-proxy
# validation instead of blindly trusting X-Forwarded-For.
_client_ip = get_client_ip


class RateLimiter:
    """Async sliding-window rate limiter.

    Tracks request timestamps per key and rejects when the count exceeds
    ``max_attempts`` within ``window_seconds``. Guarded by an
    :class:`asyncio.Lock` so concurrent coroutines on one event loop can
    never interleave read-modify-write cycles (the previous
    ``threading.Lock`` version could block the loop without protecting
    against interleaved awaits).
    """

    def __init__(
        self,
        max_attempts: int = 5,
        window_seconds: int = 900,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def _cleanup(self, key: str, now: float) -> None:
        """Remove expired entries for *key*."""
        cutoff = now - self.window_seconds
        attempts = self._attempts[key]
        self._attempts[key] = [t for t in attempts if t > cutoff]

    async def is_rate_limited(self, key: str) -> bool:
        """Return True if *key* has exceeded the allowed attempts."""
        now = time.monotonic()
        async with self._lock:
            await self._cleanup(key, now)
            return len(self._attempts[key]) >= self.max_attempts

    async def record_attempt(self, key: str) -> None:
        """Record a request attempt for *key*."""
        now = time.monotonic()
        async with self._lock:
            await self._cleanup(key, now)
            self._attempts[key].append(now)

    async def reset(self, key: str) -> None:
        """Clear all attempts for *key* (e.g. on successful login)."""
        async with self._lock:
            self._attempts.pop(key, None)

    async def remaining_seconds(self, key: str) -> int:
        """Seconds until the oldest attempt in the window expires."""
        now = time.monotonic()
        async with self._lock:
            await self._cleanup(key, now)
            attempts = self._attempts[key]
            if not attempts:
                return 0
            return max(0, int(self.window_seconds - (now - attempts[0])) + 1)


async def check_rate_limit(
    limiter: RateLimiter,
    key: str,
) -> None:
    """Raise 429 if *key* is rate-limited."""
    if await limiter.is_rate_limited(key):
        retry = await limiter.remaining_seconds(key)
        raise HTTPException(
            status_code=429,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(retry)},
        )
