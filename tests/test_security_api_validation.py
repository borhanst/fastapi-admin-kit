"""Regression tests for S08 — API validation bypass via JSON body.

The JSON create/update paths used to skip ``FormValidator.run``,
``admin.validate_create/update`` and ``admin.process_form_data``, so
password-strength rules and business rules could be bypassed by speaking
JSON instead of submitting the HTML form. The JSON parser now runs the
same shared validation pipeline as the HTML path.

Also covers the S15 ``per_page`` DoS cap (``?per_page=1000000``).
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, run_async
from tests.test_registry import Product

# bcrypt hash of "secret" (same fixture hash used across the test suite)
SECRET_HASH = "$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG"


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


class _GuardedProductAdmin(ModelAdmin):
    """Rejects sentinel values to prove admin hooks run on the JSON path."""

    list_display = ["id", "name"]

    def validate_update(self, obj, data, request=None):
        if data.get("price") == 666:
            raise ValueError("Price 666 is forbidden.")
        return data

    def validate_create(self, data, request=None):
        if data.get("name") == "forbidden":
            raise ValueError("Name 'forbidden' is not allowed.")
        return data


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


async def _seed_superuser(engine):
    async with AsyncSession(engine) as session:
        role = Role(name="SuperAdmin")
        user = User(
            email="super@test.com",
            password=SECRET_HASH,
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
    run_async(_seed_superuser(engine))

    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product, _GuardedProductAdmin)
    asyncio.run(admin.setup(app))

    client = TestClient(app)
    creds = base64.b64encode(b"super@test.com:secret").decode()
    token = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"}).json()[
        "access_token"
    ]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client, engine


async def _get_user_by_email(engine, email):
    async with AsyncSession(engine) as session:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalars().first()


async def _create_product(engine, **kwargs):
    async with AsyncSession(engine) as session:
        p = Product(**kwargs)
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return p.id


class TestJsonCreateRunsValidation:
    def test_weak_password_rejected(self, env):
        client, _engine = env
        resp = client.post(
            "/api/admin_users",
            json={"email": "weak@test.com", "password": "weak"},
        )
        assert resp.status_code == 422

    def test_missing_password_rejected(self, env):
        client, _engine = env
        resp = client.post("/api/admin_users", json={"email": "nopass@test.com"})
        assert resp.status_code == 422

    def test_strong_password_accepted_and_hashed(self, env):
        client, engine = env
        resp = client.post(
            "/api/admin_users",
            json={"email": "strong@test.com", "password": "Str0ng!Passw0rd#9"},
        )
        assert resp.status_code == 201, resp.text
        created = run_async(_get_user_by_email(engine, "strong@test.com"))
        assert created is not None
        assert created.password.startswith("$2b$")

    def test_password_not_writable_via_json(self, env):
        client, engine = env
        resp = client.post(
            "/api/admin_users",
            json={
                "email": "inject@test.com",
                "password": "Str0ng!Passw0rd#9",
                "is_active": True,
            },
        )
        assert resp.status_code in (201, 422)
        if resp.status_code == 201:
            created = run_async(_get_user_by_email(engine, "inject@test.com"))
            assert created.password.startswith("$2b$")


class TestJsonUpdateRunsValidation:
    def test_admin_validate_update_enforced(self, env):
        client, engine = env
        product_id = run_async(_create_product(engine, name="Guarded", price=1))
        resp = client.put(f"/api/products/{product_id}", json={"price": 666})
        assert resp.status_code == 422

    def test_admin_validate_create_enforced(self, env):
        client, _engine = env
        resp = client.post("/api/products", json={"name": "forbidden", "price": 5})
        assert resp.status_code == 422

    def test_partial_patch_still_works(self, env):
        client, engine = env
        product_id = run_async(_create_product(engine, name="Partial", price=10, is_active=True))
        resp = client.patch(f"/api/products/{product_id}", json={"price": 99})
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "Partial"
        assert body["price"] == 99


class TestPerPageCap:
    def test_per_page_capped_at_100(self, env):
        client, _engine = env
        resp = client.get("/api/products?per_page=1000000")
        assert resp.status_code == 200
        assert resp.json()["per_page"] <= 100

    def test_negative_per_page_clamped(self, env):
        client, _engine = env
        resp = client.get("/api/products?per_page=-5")
        assert resp.status_code == 200
        assert resp.json()["per_page"] >= 1

    def test_reasonable_per_page_respected(self, env):
        client, _engine = env
        resp = client.get("/api/products?per_page=10")
        assert resp.status_code == 200
        assert resp.json()["per_page"] == 10
