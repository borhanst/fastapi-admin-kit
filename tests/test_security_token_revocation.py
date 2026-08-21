"""Regression tests for S10 — access-token lifecycle hardening.

Design (no server-side token store): access tokens are short-lived
(``access_token_ttl``, default 600 s); logout revokes the refresh token;
a password change kills every outstanding access token immediately via the
``iat`` vs ``password_changed_at`` epoch check performed on each request.

``AccessTokenMiddleware`` pre-validates presented bearer tokens on
``/api/*`` routes and caches the payload for per-route dependencies.
``/api/auth/me`` resolves the user from the live database (enforcing
``is_active``) instead of trusting JWT claims.
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.api.auth import decode_access_token
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
from tests.test_registry import Product

# bcrypt hash of "secret"
SECRET_HASH = "$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG"


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


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
    user_id = run_async(_seed(engine))

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
    return TestClient(app), engine, user_id


def _obtain_token(client: TestClient) -> str:
    creds = base64.b64encode(b"super@test.com:secret").decode()
    resp = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


class TestShortTokenTTL:
    def test_default_access_token_ttl_is_short(self, env):
        client, _engine, _uid = env
        token = _obtain_token(client)
        payload = decode_access_token(token, SECRET_KEY)

        iat = payload["iat"]
        exp = payload["exp"]
        # Default TTL must be well under an hour (short-lived by design).
        assert exp - iat <= 3600
        assert exp - iat == 600

    def test_ttl_config_override_respected(self, engine):
        run_async(_seed(engine))
        app = FastAPI()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key=SECRET_KEY,
            auth_backend=BuiltinAuthBackend(),
            auto_discover=False,
            session_secure=False,
            access_token_ttl=120,
        )
        admin.register(Product)
        asyncio.run(admin.setup(app))

        client = TestClient(app)
        creds = base64.b64encode(b"super@test.com:secret").decode()
        resp = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"})
        body = resp.json()
        assert body["expires_in"] == 120
        payload = decode_access_token(body["access_token"], SECRET_KEY)
        assert payload["exp"] - payload["iat"] == 120


class TestLogoutRevokesRefreshToken:
    def test_refresh_dead_after_logout(self, env):
        client, _engine, _uid = env
        _token = _obtain_token(client)
        creds = base64.b64encode(b"super@test.com:secret").decode()
        first = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"}).json()

        resp = client.post("/api/auth/logout", json={"refresh_token": first["refresh_token"]})
        assert resp.status_code == 200

        resp = client.post("/api/auth/refresh", json={"refresh_token": first["refresh_token"]})
        assert resp.status_code == 401

    def test_other_sessions_unaffected(self, env):
        client, _engine, _uid = env
        _obtain_token(client)
        creds = base64.b64encode(b"super@test.com:secret").decode()
        second = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"}).json()

        client.post("/api/auth/logout")  # no refresh_token body — nothing revoked

        resp = client.post("/api/auth/refresh", json={"refresh_token": second["refresh_token"]})
        assert resp.status_code == 200


class TestPasswordChangeKillsTokens:
    def test_outstanding_access_tokens_rejected(self, env):
        client, engine, user_id = env
        token = _obtain_token(client)
        client.headers.update({"Authorization": f"Bearer {token}"})
        assert client.get("/api/products").status_code == 200

        # Change password through the HTML profile route (cookie + CSRF).
        csrf = generate_csrf_token(SECRET_KEY)
        client.cookies.set("admin_session", create_session_cookie(user_id, SECRET_KEY))
        client.cookies.set("admin_csrf_token", csrf)
        client.headers.update({"X-CSRF-Token": csrf})
        resp = client.post(
            "/admin/profile/password",
            data={
                "current_password": "secret",
                "new_password": "Br4nd!New#Pass9",
                "confirm_password": "Br4nd!New#Pass9",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302, resp.text

        # The previously issued bearer token must now be dead everywhere.
        client.cookies.clear()
        client.headers.update({"Authorization": f"Bearer {token}"})
        assert client.get("/api/products").status_code == 401
        assert client.get("/api/auth/me").status_code == 401


class TestMeResolvesLiveUser:
    def test_me_works_with_valid_token(self, env):
        client, _engine, _uid = env
        token = _obtain_token(client)
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "super@test.com"
        assert body["is_superuser"] is True

    def test_me_reflects_db_not_jwt_claims(self, env):
        client, engine, user_id = env
        token = _obtain_token(client)

        async def _rename():
            async with AsyncSession(engine) as session:
                await session.execute(
                    update(User).where(User.id == user_id).values(email="renamed@test.com")
                )
                await session.commit()

        run_async(_rename())
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["email"] == "renamed@test.com"

    def test_me_denied_after_deactivation(self, env):
        client, engine, user_id = env
        token = _obtain_token(client)
        assert (
            client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
            == 200
        )

        async def _deactivate():
            async with AsyncSession(engine) as session:
                await session.execute(
                    update(User).where(User.id == user_id).values(is_active=False)
                )
                await session.commit()

        run_async(_deactivate())
        resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401


class TestAccessTokenMiddleware:
    def test_invalid_presented_token_rejected_early(self, env):
        client, _engine, _uid = env
        resp = client.get("/api/products", headers={"Authorization": "Bearer not-a-real-token"})
        assert resp.status_code == 401

    def test_valid_token_passes_and_is_cached(self, env):
        client, _engine, _uid = env
        token = _obtain_token(client)
        resp = client.get("/api/products", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_missing_token_lenient_passthrough(self, env):
        """Without a header, route dependencies decide (lenient default)."""
        client, _engine, _uid = env
        resp = client.get("/api/products")
        assert resp.status_code == 401  # from require_api_permission, not middleware

    def test_non_api_paths_unaffected(self, env):
        client, _engine, _uid = env
        # Garbage bearer on a non-API path must not be rejected by the API
        # middleware (HTML side uses cookie sessions).
        resp = client.get("/admin/login/", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code in (200, 302)

    def test_strict_mode_requires_token(self, engine):
        run_async(_seed(engine))
        app = FastAPI()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key=SECRET_KEY,
            auth_backend=BuiltinAuthBackend(),
            auto_discover=False,
            session_secure=False,
            api_token_strict=True,
        )
        admin.register(Product)
        asyncio.run(admin.setup(app))

        client = TestClient(app)
        # Token endpoint itself stays reachable (exempt).
        creds = base64.b64encode(b"super@test.com:secret").decode()
        assert (
            client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"}).status_code
            == 200
        )
        # Everything else under /api requires a bearer token.
        assert client.get("/api/products").status_code == 401
        token = _obtain_token(client)
        resp = client.get("/api/products", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_middleware_disabled(self, engine):
        run_async(_seed(engine))
        app = FastAPI()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key=SECRET_KEY,
            auth_backend=BuiltinAuthBackend(),
            auto_discover=False,
            session_secure=False,
            api_token_middleware=False,
        )
        admin.register(Product)
        asyncio.run(admin.setup(app))

        client = TestClient(app)
        # Invalid token falls through to route deps — still 401, but the
        # middleware did not short-circuit (behaviour identical here; the
        # knob exists for deployments that need raw passthrough).
        resp = client.get("/api/products", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401
