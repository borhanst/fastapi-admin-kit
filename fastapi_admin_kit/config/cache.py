"""Optional Redis-backed response cache and rate-limit configuration.

The Redis integration is opt-in. It is only active when Redis is configured
(``REDIS_URL`` is set) *and* the ``fastapi-redis-sdk`` package is installed.
When those conditions are not met the admin behaves exactly as before — no
Redis connection, no cache middleware, no rate limiting, no extra headers.

Rate limiting is configured here alongside caching so a single
:class:`CacheConfig` controls the whole Redis surface:

- ``rate_limit`` / ``rate_window`` — default per-model list-endpoint limit.
  Every model applies it unless its ``ModelAdmin`` overrides it.
- ``login_rate_limit`` / ``login_rate_window`` — login endpoint limit.
"""

from __future__ import annotations

import os

from fastapi_admin_kit.exceptions import ConfigError

_DEFAULT_CACHE_TTL = 300
_DEFAULT_CACHE_PREFIX = "fak"
_DEFAULT_RATE_LIMIT = 5
_DEFAULT_RATE_WINDOW = 900


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("true", "1", "yes", "on")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be an integer.") from None


class CacheConfig:
    """Configuration for optional Redis-backed caching and rate limiting.

    Global defaults are read from environment variables::

        FASTAPI_ADMIN_KIT_CACHE_ENABLED=false   # opt-in switch
        FASTAPI_ADMIN_KIT_CACHE_TTL=300         # seconds
        FASTAPI_ADMIN_KIT_RATE_LIMIT_LIMIT=5    # default per-model list limit
        FASTAPI_ADMIN_KIT_RATE_LIMIT_WINDOW=900 # window in seconds
        FASTAPI_ADMIN_KIT_LOGIN_RATE_LIMIT=5    # login limit (defaults to RATE_LIMIT_LIMIT)
        FASTAPI_ADMIN_KIT_LOGIN_RATE_WINDOW=900 # login window (defaults to RATE_LIMIT_WINDOW)

    Explicit constructor arguments take precedence over the environment
    defaults, so a per-Admin ``Admin(cache_enabled=True)`` can opt in
    even when the global flag is off.
    """

    def __init__(
        self,
        enabled: bool | None = None,
        ttl: int | None = None,
        prefix: str = _DEFAULT_CACHE_PREFIX,
        rate_limit: int | None = None,
        rate_window: int | None = None,
        login_rate_limit: int | None = None,
        login_rate_window: int | None = None,
    ):
        # Explicit value wins; otherwise fall back to the global env default.
        if enabled is None:
            enabled = _env_bool("FASTAPI_ADMIN_KIT_CACHE_ENABLED", False)
        if ttl is None:
            env_ttl = os.environ.get("FASTAPI_ADMIN_KIT_CACHE_TTL")
            if env_ttl is not None:
                try:
                    ttl = int(env_ttl)
                except (TypeError, ValueError):
                    raise ConfigError(
                        "FASTAPI_ADMIN_KIT_CACHE_TTL must be an integer number of seconds."
                    ) from None
            if ttl is None:
                ttl = _DEFAULT_CACHE_TTL

        self.enabled = bool(enabled)
        self.ttl = ttl
        self.prefix = prefix

        # Per-model list-endpoint rate limit defaults.
        if rate_limit is None:
            rate_limit = _env_int("FASTAPI_ADMIN_KIT_RATE_LIMIT_LIMIT", _DEFAULT_RATE_LIMIT)
        if rate_window is None:
            rate_window = _env_int("FASTAPI_ADMIN_KIT_RATE_LIMIT_WINDOW", _DEFAULT_RATE_WINDOW)
        self.rate_limit = rate_limit
        self.rate_window = rate_window

        # Login rate limit — falls back to the per-model default when unset.
        if login_rate_limit is None:
            login_rate_limit = _env_int("FASTAPI_ADMIN_KIT_LOGIN_RATE_LIMIT", self.rate_limit)
        if login_rate_window is None:
            login_rate_window = _env_int("FASTAPI_ADMIN_KIT_LOGIN_RATE_WINDOW", self.rate_window)
        self.login_rate_limit = login_rate_limit
        self.login_rate_window = login_rate_window

    def validate_cache_config(self) -> None:
        """Validate the cache configuration."""
        if self.ttl < 0:
            raise ConfigError("cache_ttl must be >= 0 (0 disables expiration).")
        for name, value in (
            ("rate_limit", self.rate_limit),
            ("rate_window", self.rate_window),
            ("login_rate_limit", self.login_rate_limit),
            ("login_rate_window", self.login_rate_window),
        ):
            if value < 1:
                raise ConfigError(f"{name} must be >= 1.")

    def to_dict(self) -> dict:
        """Return a plain dict for app.state / template context."""
        return {
            "enabled": self.enabled,
            "ttl": self.ttl,
            "prefix": self.prefix,
            "rate_limit": self.rate_limit,
            "rate_window": self.rate_window,
            "login_rate_limit": self.login_rate_limit,
            "login_rate_window": self.login_rate_window,
        }

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"CacheConfig(enabled={self.enabled}, ttl={self.ttl}, prefix={self.prefix!r}, "
            f"rate_limit={self.rate_limit}, rate_window={self.rate_window}, "
            f"login_rate_limit={self.login_rate_limit}, login_rate_window={self.login_rate_window})"
        )
