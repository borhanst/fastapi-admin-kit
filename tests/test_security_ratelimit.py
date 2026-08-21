"""Regression tests for S11 — rate limiting & network hardening.

Covers:

* Client-IP resolution ignores ``X-Forwarded-For`` unless the direct socket
  peer is a configured trusted proxy (spoofed XFF can no longer rotate
  rate-limit buckets).
* The in-memory limiter is asyncio-safe (``asyncio.Lock``, no thread lock).
* ``POST /api/auth/token`` is limited per (client IP, email) on failed
  attempts; ``/api/auth/refresh`` and ``/api/auth/logout`` are limited per
  client IP.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.proxy import get_client_ip
from fastapi_admin_kit.auth.ratelimit import RateLimiter
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, run_async
from tests.test_registry import Product

# bcrypt hash of "secret"
SECRET_HASH = "$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG"


# ===========================================================================
# Client-IP resolution (trusted-proxy helper)
# ===========================================================================


def _make_request(
    *,
    client: tuple[str, int] | None = ("1.2.3.4", 55555),
    xff: str | None = None,
    trusted: list[str] | None = None,
) -> Request:
    app = FastAPI()
    app.state.admin_config = {"trusted_proxies": trusted}
    headers: list[tuple[bytes, bytes]] = []
    if xff is not None:
        headers.append((b"x-forwarded-for", xff.encode()))
    scope: dict = {
        "type": "http",
        "app": app,
        "headers": headers,
        "method": "GET",
        "path": "/",
        "query_string": b"",
    }
    if client is not None:
        scope["client"] = client
    return Request(scope)


class TestClientIPResolution:
    def test_xff_ignored_without_trusted_proxies(self):
        request = _make_request(client=("1.2.3.4", 100), xff="9.9.9.9")
        assert get_client_ip(request) == "1.2.3.4"

    def test_xff_ignored_when_peer_not_trusted(self):
        # trusted_proxies configured, but the direct peer isn't one of them —
        # the header must still be treated as attacker-controlled.
        request = _make_request(client=("1.2.3.4", 100), xff="9.9.9.9", trusted=["10.0.0.0/8"])
        assert get_client_ip(request) == "1.2.3.4"

    def test_xff_honored_when_peer_trusted(self):
        request = _make_request(client=("10.0.0.5", 100), xff="9.9.9.9", trusted=["10.0.0.0/8"])
        assert get_client_ip(request) == "9.9.9.9"

    def test_chain_walk_skips_trusted_hops(self):
        request = _make_request(
            client=("10.0.0.5", 100),
            xff="9.9.9.9, 10.0.0.1",
            trusted=["10.0.0.0/8"],
        )
        assert get_client_ip(request) == "9.9.9.9"

    def test_all_trusted_chain_falls_back_to_peer(self):
        request = _make_request(
            client=("10.0.0.5", 100),
            xff="10.0.0.1, 10.0.0.2",
            trusted=["10.0.0.0/8"],
        )
        assert get_client_ip(request) == "10.0.0.5"

    def test_exact_ip_trusted_entry(self):
        request = _make_request(client=("172.17.0.1", 100), xff="8.8.4.4", trusted=["172.17.0.1"])
        assert get_client_ip(request) == "8.8.4.4"

    def test_invalid_config_entries_are_ignored(self):
        request = _make_request(client=("1.2.3.4", 100), xff="9.9.9.9", trusted=["not-an-ip"])
        assert get_client_ip(request) == "1.2.3.4"

    def test_missing_client_returns_unknown(self):
        request = _make_request(client=None, xff="9.9.9.9")
        assert get_client_ip(request) == "unknown"


# ===========================================================================
# Async-safe limiter
# ===========================================================================


class TestAsyncSafeLimiter:
    def test_concurrent_attempts_are_counted(self):
        async def scenario():
            limiter = RateLimiter(max_attempts=5, window_seconds=60)
            await asyncio.gather(*(limiter.record_attempt("k") for _ in range(20)))
            return await limiter.is_rate_limited("k")

        assert run_async(scenario()) is True

    def test_reset_clears_bucket(self):
        async def scenario():
            limiter = RateLimiter(max_attempts=1, window_seconds=60)
            await limiter.record_attempt("k")
            limited = await limiter.is_rate_limited("k")
            await limiter.reset("k")
            return limited, await limiter.is_rate_limited("k")

        limited, cleared = run_async(scenario())
        assert limited is True
        assert cleared is False


# ===========================================================================
# API auth endpoint rate limits (integration)
# ===========================================================================


@pytest.fixture(autouse=True)
def _fast_limits(monkeypatch):
    """Shrink limits so tests exercise 429s quickly."""
    from fastapi_admin_kit.api import auth as api_auth

    monkeypatch.setattr(api_auth, "TOKEN_RATE_LIMIT", 3)
    monkeypatch.setattr(api_auth, "REFRESH_RATE_LIMIT", 5)
    monkeypatch.setattr(api_auth, "LOGOUT_RATE_LIMIT", 5)


@pytest.fixture
def engine():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    AdminBase.metadata.create_all(sync_engine)
    Product.metadata.create_all(sync_engine)
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield async_engine
    run_async(async_engine.dispose())
    os.unlink(path)


async def _seed(engine):
    async with AsyncSession(engine) as session:
        role = Role(name="SuperAdmin")
        user = User(
            email="super@test.com",
            hashed_password=SECRET_HASH,
            full_name="Super",
            is_superuser=True,
            is_active=True,
        )
        user.roles.append(role)
        session.add_all([role, user])
        await session.commit()
        await session.refresh(user)
        return user.id


@pytest.fixture
def env(engine):
    run_async(_seed(engine))

    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product)
    asyncio.run(admin.setup(app))
    return TestClient(app), admin


def _bad_token(client: TestClient, email: str = "super@test.com") -> int:
    creds = base64.b64encode(f"{email}:wrongpass".encode()).decode()
    resp = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"})
    return resp.status_code


class TestApiTokenRateLimit:
    def test_failed_attempts_then_429(self, env):
        client, _admin = env
        assert _bad_token(client) == 401
        assert _bad_token(client) == 401
        assert _bad_token(client) == 401
        resp = client.post(
            "/api/auth/token",
            headers={
                "Authorization": "Basic " + base64.b64encode(b"super@test.com:wrongpass").decode()
            },
        )
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_bucket_keyed_by_email(self, env):
        client, _admin = env
        for _ in range(3):
            assert _bad_token(client, "super@test.com") == 401
        # A different email has its own bucket — not locked out.
        assert _bad_token(client, "other@test.com") == 401

    def test_spoofed_xff_does_not_rotate_bucket(self, env):
        client, _admin = env
        for _ in range(3):
            assert _bad_token(client) == 401
        # Same peer, fresh spoofed XFF — must NOT open a new bucket.
        resp = client.post(
            "/api/auth/token",
            headers={
                "Authorization": "Basic " + base64.b64encode(b"super@test.com:wrongpass").decode(),
                "X-Forwarded-For": "8.8.8.8",
            },
        )
        assert resp.status_code == 429

    def test_success_resets_bucket(self, env):
        client, _admin = env
        assert _bad_token(client) == 401
        assert _bad_token(client) == 401
        creds = base64.b64encode(b"super@test.com:secret").decode()
        resp = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"})
        assert resp.status_code == 200
        # Bucket was reset — two more failures are allowed again.
        assert _bad_token(client) == 401
        assert _bad_token(client) == 401


class TestRefreshAndLogoutRateLimit:
    def test_refresh_limited_per_ip(self, env):
        client, _admin = env
        for _ in range(5):
            resp = client.post("/api/auth/refresh", json={"refresh_token": "bogus"})
            assert resp.status_code == 401
        resp = client.post("/api/auth/refresh", json={"refresh_token": "bogus"})
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers

    def test_logout_limited_per_ip(self, env):
        client, _admin = env
        for _ in range(5):
            resp = client.post("/api/auth/logout", json={"refresh_token": "bogus"})
            assert resp.status_code == 200
        resp = client.post("/api/auth/logout", json={"refresh_token": "bogus"})
        assert resp.status_code == 429


class TestTrustedProxiesConfigWiring:
    def test_admin_kwarg_reaches_app_state(self, engine):
        run_async(_seed(engine))
        app = FastAPI()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key=SECRET_KEY,
            auth_backend=BuiltinAuthBackend(),
            auto_discover=False,
            session_secure=False,
            trusted_proxies=["10.0.0.0/8", "172.17.0.1"],
        )
        admin.register(Product)
        asyncio.run(admin.setup(app))

        config = app.state.admin_config
        assert config["trusted_proxies"] == ["10.0.0.0/8", "172.17.0.1"]

    def test_default_is_empty(self, env):
        _client, admin = env
        assert admin.config.auth.trusted_proxies == []


class TestAuditMiddlewareIPExtraction:
    def test_audit_context_records_peer_ip_not_spoofed_xff(self):
        """Without trusted_proxies, the audit context must carry the socket
        peer address — a spoofed X-Forwarded-For must be ignored."""
        from fastapi_admin_kit.audit.context import get_audit_context
        from fastapi_admin_kit.audit.middleware import AuditContextMiddleware

        captured: dict = {}
        app = FastAPI()
        app.state.admin_config = {"trusted_proxies": []}
        app.add_middleware(AuditContextMiddleware)

        @app.get("/capture")
        async def capture():
            captured.update(get_audit_context() or {})
            return {"ok": True}

        client = TestClient(app)
        resp = client.get("/capture", headers={"X-Forwarded-For": "6.6.6.6"})
        assert resp.status_code == 200
        assert captured.get("ip_address") == "testclient"
        assert captured.get("ip_address") != "6.6.6.6"

    def test_audit_context_uses_xff_when_peer_trusted(self):
        from fastapi_admin_kit.audit.context import get_audit_context
        from fastapi_admin_kit.audit.middleware import AuditContextMiddleware

        captured: dict = {}
        app = FastAPI()
        app.state.admin_config = {"trusted_proxies": ["10.0.0.0/8"]}
        app.add_middleware(AuditContextMiddleware)

        @app.get("/capture")
        async def capture():
            captured.update(get_audit_context() or {})
            return {"ok": True}

        client = TestClient(app, client=("10.0.0.9", 12345))
        resp = client.get("/capture", headers={"X-Forwarded-For": "7.7.7.7"})
        assert resp.status_code == 200
        assert captured.get("ip_address") == "7.7.7.7"
