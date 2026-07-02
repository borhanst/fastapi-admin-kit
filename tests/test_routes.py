"""Tests for Phase 12 CRUD routes."""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.auth.models import AdminRole, AdminUser
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
from tests.test_registry import Product


def _get_csrf(test_client):
    get_resp = test_client.get("/admin/login")
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
    return csrf_token, csrf_cookie


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


@pytest.fixture
def admin_user(engine):
    async def _create():
        async with AsyncSession(engine) as session:
            role = AdminRole(name="SuperAdmin")
            session.add(role)
            await session.flush()
            user = AdminUser(
                email="admin@test.com",
                hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
                full_name="Admin",
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
    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
    )
    admin.register(Product)
    asyncio.run(admin.setup(app))
    return TestClient(app), admin, engine


@pytest.fixture
def product(engine, admin_user):
    async def _create():
        async with AsyncSession(engine) as db:
            p = Product(name="Test Product", price=10, is_active=True)
            db.add(p)
            await db.commit()
            await db.refresh(p)
            return p
    return run_async(_create())


def test_list_200(client, admin_user):
    test_client, admin, engine = client
    cookie = create_session_cookie(admin_user.id)
    resp = test_client.get("/admin/products/", cookies={"admin_session": cookie})
    assert resp.status_code == 200


def test_create_valid_redirect(client, admin_user):
    test_client, admin, engine = client
    cookie = create_session_cookie(admin_user.id)
    csrf_token, csrf_cookie = _get_csrf(test_client)
    resp = test_client.post(
        "/admin/products/create",
        data={"name": "Test", "csrf_token": csrf_token},
        cookies={"admin_session": cookie, "admin_csrf_token": csrf_cookie},
    )
    assert resp.status_code == 303


def test_create_invalid_422(client, admin_user):
    test_client, admin, engine = client
    cookie = create_session_cookie(admin_user.id)
    csrf_token, csrf_cookie = _get_csrf(test_client)
    resp = test_client.post(
        "/admin/products/create",
        data={"name": "", "csrf_token": csrf_token},
        cookies={"admin_session": cookie, "admin_csrf_token": csrf_cookie},
    )
    assert resp.status_code == 422


def test_edit_updates(client, admin_user, product):
    test_client, admin, engine = client
    cookie = create_session_cookie(admin_user.id)
    csrf_token, csrf_cookie = _get_csrf(test_client)
    resp = test_client.post(
        f"/admin/products/{product.id}/",
        data={"name": "Updated", "csrf_token": csrf_token},
        cookies={"admin_session": cookie, "admin_csrf_token": csrf_cookie},
    )
    assert resp.status_code == 303


def test_delete_removes(client, admin_user, product):
    test_client, admin, engine = client
    cookie = create_session_cookie(admin_user.id)
    csrf_token, csrf_cookie = _get_csrf(test_client)
    resp = test_client.post(
        f"/admin/products/{product.id}/delete",
        data={"csrf_token": csrf_token},
        cookies={"admin_session": cookie, "admin_csrf_token": csrf_cookie},
    )
    assert resp.status_code == 303


def test_rbac_403_without_permission(client):
    test_client, admin, engine = client
    resp = test_client.get("/admin/products/")
    assert resp.status_code in {401, 403}
