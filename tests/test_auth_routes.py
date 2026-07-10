"""Tests for Phase 10 — Auth Routes (Login / Logout)."""

from __future__ import annotations

import asyncio
import tempfile
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.auth.models import Role, User
from fastapi_admin_kit.models import Base
from tests.conftest import SECRET_KEY, create_session_cookie, run_async


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry
    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


@pytest.fixture
def engine():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    async_engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    yield async_engine
    run_async(async_engine.dispose())
    os.unlink(path)


@pytest.fixture
def admin_user(engine):
    async def _create():
        async with AsyncSession(engine) as session:
            role = Role(name="SuperAdmin", description="Super admin")
            session.add(role)
            await session.flush()

            user = User(
                email="test@example.com",
                hashed_password="$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG",
                full_name="Test User",
                is_superuser=True,
                is_active=True,
            )
            user.roles.append(role)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user
    return run_async(_create())


@pytest.fixture
def client(engine, admin_user):
    admin = Admin(
        engine=engine,
        auth_model=User,
        auth_backend=BuiltinAuthBackend(),
        secret_key=SECRET_KEY,
        auto_discover=False,
    )
    app = FastAPI()
    asyncio.run(admin.setup(app))
    return TestClient(app)


def _login_with_csrf(client, email="test@example.com", password="secret", **extra_data):
    get_resp = client.get("/admin/login")
    csrf_token = ""
    csrf_cookie = ""
    for part in get_resp.headers.get_list("set-cookie"):
        if part.startswith("admin_csrf_token="):
            csrf_token = part.split(";", 1)[0].split("=", 1)[1]
            csrf_cookie = csrf_token
            break
    if not csrf_token:
        csrf_token = generate_csrf_token(SECRET_KEY)
        csrf_cookie = csrf_token
    client.cookies.set("admin_csrf_token", csrf_cookie)
    data = {"username": email, "password": password, "csrf_token": csrf_token}
    data.update(extra_data)
    return client.post(
        "/admin/login",
        data=data,
        follow_redirects=False,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_login_get_redirects_when_authenticated(client):
    """GET /admin/login redirects if already authenticated."""
    response = _login_with_csrf(client)
    assert response.status_code == 302
    response = client.get(
        "/admin/login",
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/"


def test_login_get_shows_form_when_not_authenticated(client):
    """GET /admin/login shows the login form when not authenticated."""
    response = client.get("/admin/login")
    assert response.status_code == 200
    assert "Sign in" in response.text
    assert '<form method="post"' in response.text


def test_login_post_successful(client):
    """POST /admin/login with valid credentials sets session cookie."""
    response = _login_with_csrf(client)
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/"
    assert "admin_session=" in response.headers["set-cookie"]


def test_login_post_failed(client):
    """POST /admin/login with invalid credentials re-renders with error."""
    response = _login_with_csrf(client, password="wrong")
    assert response.status_code == 200
    assert "Invalid credentials" in response.text


def test_login_post_next_redirect(client):
    """POST /admin/login respects safe next URL."""
    response = _login_with_csrf(client, next="/admin/some/model/")
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/some/model/"


def test_login_post_next_open_redirect_blocked(client):
    """POST /admin/login blocks open redirect via next param."""
    response = _login_with_csrf(client, next="http://evil.com")
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/"


def test_logout_post_clears_cookie(client):
    """POST /admin/logout clears the session cookie."""
    response = _login_with_csrf(client)
    assert response.status_code == 302

    get_resp = client.get("/admin/login")
    csrf_token = ""
    csrf_cookie = ""
    for part in get_resp.headers.get_list("set-cookie"):
        if part.startswith("admin_csrf_token="):
            csrf_token = part.split(";", 1)[0].split("=", 1)[1]
            csrf_cookie = csrf_token
            break
    if not csrf_token:
        csrf_token = generate_csrf_token(SECRET_KEY)
        csrf_cookie = csrf_token

    client.cookies.set("admin_csrf_token", csrf_cookie)
    response = client.post(
        "/admin/logout",
        data={"csrf_token": csrf_token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/admin/login"
    set_cookie = response.headers["set-cookie"]
    assert "Max-Age=0" in set_cookie or "Expires=" in set_cookie


def test_logout_post_when_not_logged_in(client):
    """POST /admin/logout when not logged in redirects to login."""
    response = client.post("/admin/logout", follow_redirects=False)
    assert response.status_code in {302, 403}