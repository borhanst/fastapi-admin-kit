"""Regression tests for S02 — TOTP 2FA must be enforced on login.

Previously ``login_post`` issued a full session cookie without ever
checking ``UserTOTP.enabled``, making 2FA opt-in theatre. Now:
- login with TOTP enabled → redirect to /verify-2fa with a pending token,
  no session cookie;
- POST /verify-2fa with a valid code issues the real session;
- invalid code → no session;
- a pending-2FA token cannot be replayed as a session cookie.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.auth.totp import _generate_hotp, generate_secret
from fastapi_admin_kit.migrations.models import Role, User, UserTOTP
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, run_async

PASSWORD_HASH = "$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG"
LOGIN_PASSWORD = "secret"


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
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield async_engine
    run_async(async_engine.dispose())
    os.unlink(path)


async def _seed(engine, *, totp_enabled: bool):
    async with AsyncSession(engine) as session:
        role = Role(name="SuperAdmin")
        user = User(
            email="totp@test.com",
            password=PASSWORD_HASH,
            full_name="TOTP User",
            is_superuser=True,
            is_active=True,
        )
        user.roles.append(role)
        session.add(user)
        await session.flush()

        secret = generate_secret()
        session.add(
            UserTOTP(
                user_id=user.id,
                secret_key=secret,
                enabled=totp_enabled,
                backup_codes=None,
            )
        )
        new_user_id = user.id
        await session.commit()
        return new_user_id, secret


def _current_code(secret: str) -> str:
    return _generate_hotp(secret, int(time.time()) // 30)


@pytest.fixture
def client_factory(engine):
    def _build():
        app = FastAPI()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key=SECRET_KEY,
            auth_backend=BuiltinAuthBackend(),
            auto_discover=False,
            session_secure=False,
        )
        asyncio.run(admin.setup(app))
        return TestClient(app)

    return _build


def _login(client: TestClient, email: str = "totp@test.com"):
    """Log in and return (response, csrf_token_used).

    The token is returned so callers can reuse the exact same double-submit
    pair — the login response also sets its own csrf cookie under the
    testserver domain, so issuing a fresh token afterwards creates a
    duplicate-cookie mismatch that real browsers would not hit.
    """
    token = generate_csrf_token(SECRET_KEY)
    client.cookies.set("admin_csrf_token", token)
    resp = client.post(
        "/admin/login",
        data={"username": email, "password": LOGIN_PASSWORD, "csrf_token": token},
        follow_redirects=False,
    )
    return resp, token


class TestTotpEnforcedOnLogin:
    def test_login_redirects_to_verify_2fa_without_session(self, engine, client_factory):
        run_async(_seed(engine, totp_enabled=True))
        client = client_factory()
        resp, _token = _login(client)
        assert resp.status_code == 302
        assert "/verify-2fa" in resp.headers["location"]
        assert "temp_token=" in resp.headers["location"]
        # No admin session cookie may be set.
        set_cookies = resp.headers.get_list("set-cookie")
        assert not any(c.startswith("admin_session=") for c in set_cookies)

    def test_valid_code_issues_session(self, engine, client_factory):
        user_id, secret = run_async(_seed(engine, totp_enabled=True))
        client = client_factory()
        resp, csrf = _login(client)
        temp_token = resp.headers["location"].split("temp_token=")[1]

        resp2 = client.post(
            "/admin/verify-2fa",
            data={"temp_token": temp_token, "code": _current_code(secret), "csrf_token": csrf},
            follow_redirects=False,
        )
        assert resp2.status_code == 302
        set_cookies = resp2.headers.get_list("set-cookie")
        assert any(c.startswith("admin_session=") for c in set_cookies)

        # The issued session must actually authenticate: any admin page
        # renders (or internally redirects) instead of bouncing to /login.
        client.cookies.set("admin_session", resp2.cookies["admin_session"])
        me = client.get("/admin/", follow_redirects=False)
        assert me.status_code in (200, 307)
        if "location" in me.headers:
            assert "/login" not in me.headers["location"]

    def test_invalid_code_does_not_issue_session(self, engine, client_factory):
        run_async(_seed(engine, totp_enabled=True))
        client = client_factory()
        resp, csrf = _login(client)
        temp_token = resp.headers["location"].split("temp_token=")[1]

        resp2 = client.post(
            "/admin/verify-2fa",
            data={"temp_token": temp_token, "code": "000000", "csrf_token": csrf},
            follow_redirects=False,
        )
        assert resp2.status_code == 200
        set_cookies = resp2.headers.get_list("set-cookie")
        assert not any(c.startswith("admin_session=") for c in set_cookies)

    def test_pending_token_cannot_be_used_as_session(self, engine, client_factory):
        run_async(_seed(engine, totp_enabled=True))
        client = client_factory()
        resp, _token = _login(client)
        temp_token = resp.headers["location"].split("temp_token=")[1]

        # Replay the pending token as if it were a session cookie.
        client.cookies.set("admin_session", temp_token)
        page = client.get("/admin/", follow_redirects=False)
        assert page.status_code in (301, 302, 303, 307, 308, 401)

    def test_totp_disabled_user_logs_in_directly(self, engine, client_factory):
        run_async(_seed(engine, totp_enabled=False))
        client = client_factory()
        resp, _token = _login(client)
        assert resp.status_code == 302
        assert "/verify-2fa" not in resp.headers["location"]
