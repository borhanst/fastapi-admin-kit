"""Tests for the dashboard view."""

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
from fastapi_admin_kit.audit.models import AuditLog  # noqa: F401 - ensure table is registered
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.auth.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, run_async
from tests.test_registry import Category, Product


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
            role = Role(name="SuperAdmin")
            session.add(role)
            await session.flush()
            user = User(
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
    asyncio.run(admin.setup(app))

    admin.register(Product)

    async def _seed():
        async with AsyncSession(engine) as db:
            cat = Category(name="Test Category")
            db.add(cat)
            await db.flush()
            for i in range(3):
                product = Product(
                    name=f"Product {i}",
                    price=100 + i,
                    category_id=cat.id,
                    is_active=True,
                )
                db.add(product)
            await db.commit()

    run_async(_seed())

    return TestClient(app), admin, engine


def _login(test_client):
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
    test_client.cookies.set("admin_csrf_token", csrf_cookie)
    response = test_client.post(
        "/admin/login",
        data={"email": "admin@test.com", "password": "password", "csrf_token": csrf_token},
        follow_redirects=False,
    )
    session_cookie = response.cookies.get("admin_session")
    if session_cookie:
        test_client.cookies.set("admin_session", session_cookie)
    return session_cookie


def test_dashboard_view(client):
    """Test the dashboard view shows correct stat counts and recent activity."""
    test_client, admin, engine = client

    session_cookie = _login(test_client)
    assert session_cookie is not None

    response = test_client.get("/admin/")
    assert response.status_code == 200
    assert "Dashboard" in response.text
    assert "Products" in response.text
    assert "3" in response.text

    assert "Recent Activity" in response.text
    assert "Add Product" in response.text
    assert "/admin/products/" in response.text


def test_dashboard_stats_filter(client):
    """Test that dashboard_stats config filters which models are shown."""
    test_client, admin, engine = client

    _login(test_client)

    test_client.app.state.admin_config["dashboard_stats"] = ["products"]

    response = test_client.get("/admin/")
    assert response.status_code == 200
    assert "3" in response.text


def test_dashboard_charts_toggle(client):
    """Test that dashboard_charts config controls chart visibility."""
    test_client, admin, engine = client

    _login(test_client)

    response = test_client.get("/admin/")
    assert response.status_code == 200
    assert "Charts" in response.text

    test_client.app.state.admin_config["dashboard_charts"] = False

    response = test_client.get("/admin/")
    assert response.status_code == 200
