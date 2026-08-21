"""Tests for optional Redis-backed caching and rate-limiting fallback."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from fastapi_admin_kit.config import CacheConfig
from fastapi_admin_kit.exceptions import ConfigError
from fastapi_admin_kit.redis import (
    cache_dependency,
    get_login_guard,
    redis_configured,
    redis_enabled,
    redis_sdk_available,
    setup_redis,
)


class TestCacheConfig:
    def test_defaults(self, monkeypatch):
        monkeypatch.delenv("FASTAPI_ADMIN_KIT_CACHE_ENABLED", raising=False)
        monkeypatch.delenv("FASTAPI_ADMIN_KIT_CACHE_TTL", raising=False)
        cfg = CacheConfig()
        assert cfg.enabled is False
        assert cfg.ttl == 300
        assert cfg.prefix == "fak"

    def test_env_enabled_and_ttl(self, monkeypatch):
        monkeypatch.setenv("FASTAPI_ADMIN_KIT_CACHE_ENABLED", "true")
        monkeypatch.setenv("FASTAPI_ADMIN_KIT_CACHE_TTL", "60")
        cfg = CacheConfig()
        assert cfg.enabled is True
        assert cfg.ttl == 60

    def test_explicit_args_override_env(self, monkeypatch):
        monkeypatch.setenv("FASTAPI_ADMIN_KIT_CACHE_ENABLED", "true")
        monkeypatch.setenv("FASTAPI_ADMIN_KIT_CACHE_TTL", "60")
        cfg = CacheConfig(enabled=False, ttl=120)
        assert cfg.enabled is False
        assert cfg.ttl == 120

    def test_invalid_ttl_env_raises(self, monkeypatch):
        monkeypatch.setenv("FASTAPI_ADMIN_KIT_CACHE_TTL", "not-a-number")
        with pytest.raises(ConfigError):
            CacheConfig()

    def test_negative_ttl_invalid(self):
        cfg = CacheConfig(enabled=True, ttl=-1)
        with pytest.raises(ConfigError):
            cfg.validate_cache_config()


class TestRedisDetection:
    def test_not_configured(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        assert redis_configured() is False
        assert redis_enabled() is False

    def test_configured_without_sdk(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        import fastapi_admin_kit.redis as redis_mod

        monkeypatch.setattr(redis_mod, "redis_sdk_available", lambda: False)
        assert redis_configured() is True
        assert redis_enabled() is False

    @pytest.mark.skipif(not redis_sdk_available(), reason="fastapi-redis-sdk not installed")
    def test_configured_with_sdk(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        assert redis_configured() is True
        assert redis_enabled() is True


class TestSetupRedis:
    def test_noop_without_url(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        app = FastAPI()
        assert setup_redis(app, cache_enabled=True) is False

    def test_returns_false_without_sdk(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        import fastapi_admin_kit.redis as redis_mod

        monkeypatch.setattr(redis_mod, "redis_sdk_available", lambda: False)
        app = FastAPI()
        assert setup_redis(app, cache_enabled=True) is False

    @pytest.mark.skipif(not redis_sdk_available(), reason="fastapi-redis-sdk not installed")
    def test_wires_lifespan(self, monkeypatch):
        pytest.importorskip("fakeredis.aioredis")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        app = FastAPI()
        assert setup_redis(app, cache_enabled=True, rate_limiting=True) is True
        assert getattr(app.router.lifespan_context, "_redis_lifespan", False) is True


class TestCacheDependency:
    def test_none_when_redis_unavailable(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        cfg = CacheConfig(enabled=True, ttl=60)
        assert cache_dependency(cfg, "products") is None

    def test_none_when_disabled(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        cfg = CacheConfig(enabled=False, ttl=60)
        assert cache_dependency(cfg, "products") is None

    @pytest.mark.skipif(not redis_sdk_available(), reason="fastapi-redis-sdk not installed")
    def test_returns_depends_when_active(self, monkeypatch):
        from fastapi.params import Depends as DependsParam

        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        cfg = CacheConfig(enabled=True, ttl=60)
        dep = cache_dependency(cfg, "products")
        assert dep is not None
        assert isinstance(dep, DependsParam)


class TestLoginGuard:
    async def test_in_memory_fallback(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        app = FastAPI()
        app.state.admin = None

        @app.get("/guard-type")
        async def guard_type(guard=Depends(get_login_guard)):
            return {"type": type(guard).__name__}

        with TestClient(app) as client:
            assert client.get("/guard-type").json()["type"] == "InMemoryLoginRateGuard"

    @pytest.mark.skipif(not redis_sdk_available(), reason="fastapi-redis-sdk not installed")
    def test_redis_backed(self, monkeypatch):
        pytest.importorskip("fakeredis.aioredis")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        import fakeredis.aioredis
        from redis_fastapi import FastAPIRedis, get_async_redis

        app = FastAPI()
        FastAPIRedis(app).lifespan()
        fake = fakeredis.aioredis.FakeRedis()
        app.dependency_overrides[get_async_redis] = lambda: fake

        class FakeAdmin:
            redis_enabled = True

        app.state.admin = FakeAdmin()

        @app.get("/guard-type")
        async def guard_type(guard=Depends(get_login_guard)):
            return {"type": type(guard).__name__}

        with TestClient(app) as client:
            assert client.get("/guard-type").json()["type"] == "RedisLoginRateGuard"

    @pytest.mark.skipif(not redis_sdk_available(), reason="fastapi-redis-sdk not installed")
    async def test_redis_guard_enforces_and_resets(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock

        from fastapi import HTTPException

        from fastapi_admin_kit.redis import RedisLoginRateGuard

        backend = AsyncMock()
        backend.peek.side_effect = [
            SimpleNamespace(remaining=2, retry_after=0),  # check -> ok
            SimpleNamespace(remaining=1, retry_after=0),  # check -> ok
            SimpleNamespace(remaining=0, retry_after=55),  # is_rate_limited -> True
            SimpleNamespace(remaining=0, retry_after=55),  # check -> 429
            SimpleNamespace(remaining=55, retry_after=55),  # remaining_seconds
            SimpleNamespace(remaining=2, retry_after=0),  # is_rate_limited -> False
        ]

        guard = RedisLoginRateGuard(backend, limit=2, window=60)
        key = "login:1.2.3.4"
        await guard.check(key)
        await guard.record_failure(key)
        await guard.check(key)
        assert await guard.is_rate_limited(key) is True
        with pytest.raises(HTTPException) as excinfo:
            await guard.check(key)
        assert excinfo.value.status_code == 429
        assert await guard.remaining_seconds(key) > 0
        await guard.reset(key)
        assert await guard.is_rate_limited(key) is False
        assert backend.peek.call_count == 6
        await guard.record_failure(key)
        backend.hit.assert_awaited()
        await guard.reset(key)
        backend.reset.assert_awaited()

    async def test_in_memory_guard_matches_limiter(self):
        from fastapi_admin_kit.auth.ratelimit import RateLimiter
        from fastapi_admin_kit.redis import InMemoryLoginRateGuard

        limiter = RateLimiter(max_attempts=2, window_seconds=60)
        guard = InMemoryLoginRateGuard(limiter)
        key = "login:1.2.3.4"
        await guard.record_failure(key)
        await guard.record_failure(key)
        assert await guard.is_rate_limited(key) is True
        await guard.reset(key)
        assert await guard.is_rate_limited(key) is False


class TestBuildModelRouterCaching:
    @pytest.mark.skipif(not redis_sdk_available(), reason="fastapi-redis-sdk not installed")
    def test_cache_dep_applied_to_list_and_detail(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        from fastapi_admin_kit.registry import build_registered_model
        from fastapi_admin_kit.router import build_model_router
        from fastapi_admin_kit.views import ModelAdmin
        from tests.test_registry import Product

        registered = build_registered_model(Product, ModelAdmin())
        router = build_model_router(registered, cache_config=CacheConfig(enabled=True, ttl=60))
        assert router is not None

        cached_paths = set()
        for route in router.routes:
            path = getattr(route, "path", None)
            methods = getattr(route, "methods", None) or set()
            if path is None or "GET" not in methods:
                continue
            deps = getattr(route, "dependant", None)
            if deps is None:
                continue
            modules = {getattr(d.call, "__module__", "") for d in deps.dependencies}
            if "redis_fastapi.cache" in modules:
                cached_paths.add(path)
        assert cached_paths == {"/products/", "/products/{id}"}

    def test_no_cache_dep_when_redis_unavailable(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        from fastapi_admin_kit.registry import build_registered_model
        from fastapi_admin_kit.router import build_model_router
        from fastapi_admin_kit.views import ModelAdmin
        from tests.test_registry import Product

        registered = build_registered_model(Product, ModelAdmin())
        router = build_model_router(registered, cache_config=CacheConfig(enabled=True, ttl=60))
        assert router is not None
        for route in router.routes:
            deps = getattr(route, "dependant", None)
            if deps is None:
                continue
            modules = {getattr(d.call, "__module__", "") for d in deps.dependencies}
            assert "redis_fastapi.cache" not in modules
