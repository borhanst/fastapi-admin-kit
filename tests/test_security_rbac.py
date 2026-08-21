"""Regression tests for S03 — state-changing routes must require edit permission.

PATCH /{id}/field, POST /sort, POST /action/{name}, POST /action/{name}/{id}
previously only checked CSRF, letting view-only users mutate data.
"""

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

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.migrations.models import Permission, Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
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


async def _make_user(engine, email: str, is_superuser: bool, with_view_perm: bool):
    async with AsyncSession(engine) as session:
        role = Role(name="SuperAdmin" if is_superuser else "Viewer")

        if with_view_perm:
            perm = Permission(
                name="products_view",
                table_name="products",
                can_view=True,
                can_create=False,
                can_edit=False,
                can_delete=False,
                can_export=False,
                can_import=False,
            )
            role.permissions.append(perm)
            session.add(perm)

        user = User(
            email=email,
            hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name=email,
            is_superuser=is_superuser,
            is_active=True,
        )
        user.roles.append(role)
        session.add_all([role, user])
        await session.commit()
        await session.refresh(user)
        return user.id


def _csrf_headers():
    token = generate_csrf_token(SECRET_KEY)
    return {"X-CSRF-Token": token}, {"admin_csrf_token": token}


class ProductAdmin(ModelAdmin):
    list_display = ["name", "price", "is_active"]


@pytest.fixture
def env(engine):
    super_id = run_async(_make_user(engine, "admin@test.com", True, False))
    viewer_id = run_async(_make_user(engine, "viewer@test.com", False, True))

    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product, ProductAdmin)
    asyncio.run(admin.setup(app))

    async def _seed_product():
        from sqlalchemy import select

        async with AsyncSession(engine) as session:
            product = Product(name="Widget", price=10, is_active=True)
            session.add(product)
            await session.commit()
            result = await session.execute(select(Product).order_by(Product.id))
            return result.scalars().first().id

    product_id = run_async(_seed_product())
    return TestClient(app), super_id, viewer_id, product_id


def _auth_client(client: TestClient, user_id: int) -> TestClient:
    client.cookies.set("admin_session", create_session_cookie(user_id, SECRET_KEY))
    headers, cookies = _csrf_headers()
    client.cookies.update(cookies)
    client.headers.update(headers)
    return client


class TestPatchFieldRequiresEdit:
    def test_viewer_cannot_toggle_field(self, env):
        client, _, viewer_id, product_id = env
        _auth_client(client, viewer_id)
        resp = client.patch(
            f"/admin/products/{product_id}/field",
            json={"field": "is_active", "value": "false"},
        )
        assert resp.status_code == 403

    def test_superuser_can_toggle_field(self, env):
        client, super_id, _, product_id = env
        _auth_client(client, super_id)
        resp = client.patch(
            f"/admin/products/{product_id}/field",
            json={"field": "is_active", "value": "false"},
        )
        assert resp.status_code == 200


class TestSortRequiresEdit:
    def test_viewer_cannot_sort(self, env):
        client, _, viewer_id, product_id = env
        _auth_client(client, viewer_id)
        resp = client.post("/admin/products/sort", json={"items": [product_id]})
        assert resp.status_code == 403

    def test_superuser_can_sort(self, env):
        client, super_id, _, product_id = env
        _auth_client(client, super_id)
        # ProductAdmin has no ordering_field → handler rejects with 400,
        # proving the request passed the permission gate (403 would mean blocked).
        resp = client.post("/admin/products/sort", json={"items": [product_id]})
        assert resp.status_code == 400
        assert "Sorting not configured" in resp.json()["detail"]


class TestActionsRequireEdit:
    def test_viewer_cannot_execute_list_action(self, env):
        client, _, viewer_id, product_id = env
        _auth_client(client, viewer_id)
        resp = client.post(
            "/admin/products/action/unknown_action",
            data={"ids[]": str(product_id)},
        )
        assert resp.status_code == 403

    def test_superuser_reaches_action_handler(self, env):
        client, super_id, _, product_id = env
        _auth_client(client, super_id)
        resp = client.post(
            "/admin/products/action/unknown_action",
            data={"ids[]": str(product_id)},
        )
        assert resp.status_code == 404

    def test_viewer_cannot_execute_row_action(self, env):
        client, _, viewer_id, product_id = env
        _auth_client(client, viewer_id)
        resp = client.post("/admin/products/action/unknown_action/1")
        assert resp.status_code == 403

    def test_superuser_reaches_row_action_handler(self, env):
        client, super_id, _, product_id = env
        _auth_client(client, super_id)
        resp = client.post(f"/admin/products/action/unknown_action/{product_id}")
        assert resp.status_code == 404
