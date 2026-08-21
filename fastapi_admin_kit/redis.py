"""Optional Redis integration helpers built on ``fastapi-redis-sdk``.

Everything in this module is safe to import even when ``fastapi-redis-sdk``
is not installed or Redis is not configured. The public functions degrade
gracefully:

- :func:`redis_enabled` reports whether Redis is actually usable.
- :func:`setup_redis` wires the SDK's lifespan/caching/rate-limiting into a
  FastAPI app (a no-op when Redis is unavailable).
- :func:`get_login_guard` returns an async login rate-limit guard that uses
  the distributed Redis backend when available and the existing in-memory
  limiter otherwise.
- :func:`resolve_rate_guard` is the generic form used for any rate-limit
  purpose (login, API token, refresh, ...) with a per-purpose storage slot.

Backward compatibility is preserved: without ``REDIS_URL`` the admin falls
back to the in-memory :class:`~fastapi_admin_kit.auth.ratelimit.RateLimiter`
exactly as before.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any, Protocol

from fastapi import HTTPException, Request

from fastapi_admin_kit.auth.ratelimit import RateLimiter, check_rate_limit

if TYPE_CHECKING:
    from fastapi_admin_kit.config.cache import CacheConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Redis detection
# ---------------------------------------------------------------------------


def redis_url() -> str | None:
    """Return the configured ``REDIS_URL`` or ``None``."""
    url = os.environ.get("REDIS_URL")
    return url or None


def redis_configured() -> bool:
    """Return True when ``REDIS_URL`` is set (regardless of SDK availability)."""
    return redis_url() is not None


def redis_sdk_available() -> bool:
    """Return True when the ``fastapi-redis-sdk`` package is importable."""
    try:
        import redis_fastapi  # noqa: F401

        return True
    except ImportError:
        return False


def redis_enabled() -> bool:
    """Return True when Redis is configured *and* the SDK is installed.

    This is the single source of truth for "should we use Redis?" — every
    feature (rate limiting, caching) consults it before reaching for the SDK.
    """
    return redis_configured() and redis_sdk_available()


# ---------------------------------------------------------------------------
# App wiring
# ---------------------------------------------------------------------------


def setup_redis(
    app: Any,
    *,
    cache_enabled: bool = False,
    cache_ttl: int = 300,
    rate_limiting: bool = True,
) -> bool:
    """Wire the Redis connection pool plus caching/rate-limiting into *app*.

    Wraps the app's existing lifespan (via the SDK builder) so the shared
    async connection pool lives for the whole application lifetime. Idempotent.

    Returns ``True`` when Redis was wired, ``False`` when it was skipped
    (no ``REDIS_URL``, or the SDK is not installed).
    """
    if not redis_configured():
        logger.info("REDIS_URL not set — Redis-backed caching/rate limiting disabled")
        return False
    if not redis_sdk_available():
        logger.warning(
            "REDIS_URL is set but 'fastapi-redis-sdk' is not installed. "
            "Install it with `pip install fastapi-admin-kit[redis]` to enable "
            "Redis-backed caching and rate limiting."
        )
        return False

    from redis_fastapi import FastAPIRedis

    builder = FastAPIRedis(app).lifespan()
    if cache_enabled:
        builder = builder.caching()
    if rate_limiting:
        builder = builder.rate_limiting()
    setattr(app.router.lifespan_context, "_redis_lifespan", True)
    logger.info("Redis-backed caching/rate limiting enabled (REDIS_URL set).")
    return True


def cache_dependency(
    cache_config: CacheConfig | None,
    eviction_group: str,
) -> Any | None:
    """Return a ``Depends(cache(...))`` when caching is active, else ``None``.

    Caching requires three things: an enabled :class:`CacheConfig`, a
    configured ``REDIS_URL`` and the SDK being installed. When any of those
    is missing the returned dependency is ``None`` so callers simply skip
    applying it.
    """
    if cache_config is None or not cache_config.enabled:
        return None
    if not redis_enabled():
        return None

    from fastapi import Depends
    from redis_fastapi import cache

    return Depends(
        cache(
            ttl=cache_config.ttl,
            eviction_group=eviction_group,
            cache_prefix=cache_config.prefix,
            private=True,
        )
    )


def rate_limit_dependency(
    cache_config: CacheConfig | None,
    limit: int | None = None,
    window: int | None = None,
    *,
    scope: str = "",
) -> Any | None:
    """Return a ``Depends(rate_limit(...))`` when Redis rate limiting is active.

    Rate limiting needs only a configured ``REDIS_URL`` and the SDK installed
    (unlike caching it does *not* require ``cache_config.enabled``). The
    ``limit``/``window`` fall back to the global ``CacheConfig`` defaults when
    ``None``. Returns ``None`` when Redis is unavailable so callers simply
    skip applying it.
    """
    if not redis_enabled():
        return None
    resolved_limit = limit if limit is not None else getattr(cache_config, "rate_limit", None)
    resolved_window = window if window is not None else getattr(cache_config, "rate_window", None)
    if (
        resolved_limit is None
        or resolved_window is None
        or resolved_limit < 1
        or resolved_window < 1
    ):
        return None

    from fastapi import Depends
    from redis_fastapi import rate_limit

    return Depends(rate_limit(limit=resolved_limit, window=resolved_window, scope=scope))


# ---------------------------------------------------------------------------
# Login rate limiting (Redis-backed with in-memory fallback)
# ---------------------------------------------------------------------------

LOGIN_RATE_LIMIT_DEFAULT = 5
LOGIN_RATE_WINDOW_DEFAULT = 900


class LoginRateGuard(Protocol):
    """Async interface shared by the in-memory and Redis login guards."""

    async def check(self, key: str) -> None: ...
    async def is_rate_limited(self, key: str) -> bool: ...
    async def record_failure(self, key: str) -> None: ...
    async def reset(self, key: str) -> None: ...
    async def remaining_seconds(self, key: str) -> int: ...


class InMemoryLoginRateGuard:
    """Async adapter over the existing in-memory :class:`RateLimiter`."""

    def __init__(self, limiter: RateLimiter) -> None:
        self._limiter = limiter

    async def check(self, key: str) -> None:
        await check_rate_limit(self._limiter, key)

    async def is_rate_limited(self, key: str) -> bool:
        return await self._limiter.is_rate_limited(key)

    async def record_failure(self, key: str) -> None:
        await self._limiter.record_attempt(key)

    async def reset(self, key: str) -> None:
        await self._limiter.reset(key)

    async def remaining_seconds(self, key: str) -> int:
        return await self._limiter.remaining_seconds(key)


class RedisLoginRateGuard:
    """Async guard backed by the distributed Redis ``RateLimitBackend``.

    Counters live in Redis so the limit holds across every worker/pod. The
    backend fails open when Redis is unreachable — a Redis outage degrades to
    "allow and log" rather than taking the admin login down.
    """

    def __init__(
        self,
        backend: Any,
        *,
        limit: int = LOGIN_RATE_LIMIT_DEFAULT,
        window: int = LOGIN_RATE_WINDOW_DEFAULT,
    ) -> None:
        self._backend = backend
        self.limit = limit
        self.window = window

    async def check(self, key: str) -> None:
        state = await self._backend.peek(key, limit=self.limit, window=self.window)
        if state.remaining == 0:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please try again later.",
                headers={"Retry-After": str(state.retry_after)},
            )

    async def is_rate_limited(self, key: str) -> bool:
        state = await self._backend.peek(key, limit=self.limit, window=self.window)
        return state.remaining == 0

    async def record_failure(self, key: str) -> None:
        await self._backend.hit(key, limit=self.limit, window=self.window)

    async def reset(self, key: str) -> None:
        await self._backend.reset(key)

    async def remaining_seconds(self, key: str) -> int:
        state = await self._backend.peek(key, limit=self.limit, window=self.window)
        return state.retry_after


# Per-process fallback limiters used when no Admin instance is mounted.
# See the auth.ratelimit module docstring for multi-worker implications.
_fallback_limiters: dict[str, RateLimiter] = {}


async def resolve_rate_guard(
    request: Request,
    *,
    limit: int,
    window: int,
    slot: str,
) -> LoginRateGuard:
    """Resolve a rate-limit guard for *request*.

    Uses the distributed Redis guard when Redis is enabled; otherwise falls
    back to the in-memory limiter. In-memory state is stored on the admin
    instance under *slot* (one limiter per purpose — login, API token,
    refresh, ...). When no admin instance is mounted, a module-level
    fallback keeps limiting functional for the process lifetime.

    .. warning::

        The in-memory fallback is per-process. See the ``auth.ratelimit``
        module docstring for the multi-worker implications.
    """
    admin = getattr(request.app.state, "admin", None)
    redis_active = bool(getattr(admin, "redis_enabled", False)) if admin else redis_enabled()
    if redis_active:
        from redis_fastapi import get_rate_limit_backend

        backend = await get_rate_limit_backend(request)
        return RedisLoginRateGuard(backend, limit=limit, window=window)

    limiter = getattr(admin, slot, None) if admin is not None else None
    if limiter is None:
        limiter = _fallback_limiters.get(slot)
        if limiter is None:
            limiter = RateLimiter(max_attempts=limit, window_seconds=window)
        if admin is not None:
            setattr(admin, slot, limiter)
        else:
            _fallback_limiters[slot] = limiter
    return InMemoryLoginRateGuard(limiter)


async def get_login_guard(request: Request) -> LoginRateGuard:
    """FastAPI dependency resolving the login rate-limit guard for a request.

    Uses the Redis-backed distributed guard when Redis is enabled, otherwise
    falls back to the existing in-memory limiter — preserving the current
    auth/rate-limiting behaviour for deployments without Redis.

    Limits come from the admin's :class:`CacheConfig`
    (``login_rate_limit`` / ``login_rate_window``), which in turn read the
    ``FASTAPI_ADMIN_KIT_LOGIN_RATE_LIMIT`` / ``_WINDOW`` env vars.
    """
    admin = getattr(request.app.state, "admin", None)
    cache_config = getattr(admin, "cache_config", None)
    login_limit = getattr(cache_config, "login_rate_limit", LOGIN_RATE_LIMIT_DEFAULT)
    login_window = getattr(cache_config, "login_rate_window", LOGIN_RATE_WINDOW_DEFAULT)
    return await resolve_rate_guard(
        request,
        limit=login_limit,
        window=login_window,
        slot="_login_rate_limiter",
    )
