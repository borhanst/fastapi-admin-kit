"""Integration tests for the JSON API CRUD endpoints (PATCH partial updates)."""

from __future__ import annotations

import base64
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
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, run_async
from tests.test_registry import Product


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
def client(engine):
    async def _seed():
        async with AsyncSession(engine) as session:
            role = Role(name="SuperAdmin")
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

    run_async(_seed())

    admin = Admin(
        engine=engine,
        auth_model=User,
        auth_backend=BuiltinAuthBackend(),
        secret_key=SECRET_KEY,
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product)
    app = FastAPI()
    run_async(admin.setup(app))
    return TestClient(app)


@pytest.fixture
def product(engine):
    async def _create():
        async with AsyncSession(engine) as session:
            p = Product(name="Initial", price=10, is_active=True)
            session.add(p)
            await session.commit()
            await session.refresh(p)
            return p

    return run_async(_create())


@pytest.fixture
def auth_headers(client):
    creds = base64.b64encode(b"test@example.com:secret").decode()
    token = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def test_patch_endpoint_registered(client):
    schema = client.get("/openapi.json").json()
    methods = set(schema["paths"]["/api/products/{item_id}"])
    assert "patch" in methods
    assert "put" in methods


def test_patch_partially_updates_only_provided_fields(client, product, auth_headers):
    resp = client.patch(f"/api/products/{product.id}", headers=auth_headers, json={"price": 99})
    assert resp.status_code == 200
    body = resp.json()
    assert body["price"] == 99
    assert body["name"] == "Initial"

    get_resp = client.get(f"/api/products/{product.id}", headers=auth_headers)
    assert get_resp.json()["price"] == 99
    assert get_resp.json()["name"] == "Initial"


def test_patch_missing_item_404(client, auth_headers):
    resp = client.patch("/api/products/99999", headers=auth_headers, json={"price": 1})
    assert resp.status_code == 404
