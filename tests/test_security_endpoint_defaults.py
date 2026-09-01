"""Regression tests for S17 — custom ``@endpoint`` secure-by-default.

A custom endpoint registered without an explicit ``permission`` must NOT be
public: it requires an authenticated user with ``view`` permission on the
model. Genuinely public endpoints must opt out explicitly with
``allow_anonymous=True``.
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

from fastapi_admin_kit import Admin, ModelAdmin, endpoint
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
from tests.test_registry import Product

# bcrypt hash of "secret"
SECRET_HASH = "$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG"


class ProductEndpointAdmin(ModelAdmin):
    @endpoint(path="/no-permission")
    async def no_permission(self, request):
        return {"data": "default-protected"}

    @endpoint(path="/anon-stats", allow_anonymous=True)
    async def anon_stats(self, request):
        return {"stats": "public"}

    @endpoint(path="/manage", permission="edit")
    async def manage(self, request):
        return {"managed": True}


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
        super_role = Role(name="SuperAdmin")
        viewer_role = Role(name="Viewer")  # no Permission rows → view denied
        super_user = User(
            email="super@test.com",
            password=SECRET_HASH,
            full_name="Super",
            is_superuser=True,
            is_active=True,
        )
        super_user.roles.append(super_role)
        viewer = User(
            email="viewer@test.com",
            password=SECRET_HASH,
            full_name="Viewer",
            is_superuser=False,
            is_active=True,
        )
        viewer.roles.append(viewer_role)
        session.add_all([super_role, viewer_role, super_user, viewer])
        await session.commit()
        await session.refresh(super_user)
        await session.refresh(viewer)
        return super_user.id, viewer.id


@pytest.fixture
def env(engine):
    super_id, viewer_id = run_async(_seed(engine))

    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product, ProductEndpointAdmin)
    asyncio.run(admin.setup(app))
    return TestClient(app), super_id, viewer_id


def _cookie(user_id: int) -> dict[str, str]:
    return {"admin_session": create_session_cookie(user_id)}


class TestSecureByDefault:
    def test_unauthenticated_gets_401(self, env):
        client, _super_id, _viewer_id = env
        resp = client.get("/admin/products/no-permission")
        assert resp.status_code == 401

    def test_superuser_gets_200(self, env):
        client, super_id, _viewer_id = env
        resp = client.get("/admin/products/no-permission", cookies=_cookie(super_id))
        assert resp.status_code == 200
        assert resp.json() == {"data": "default-protected"}

    def test_viewer_without_permission_gets_403(self, env):
        client, _super_id, viewer_id = env
        resp = client.get("/admin/products/no-permission", cookies=_cookie(viewer_id))
        assert resp.status_code == 403


class TestAllowAnonymousOptOut:
    def test_anonymous_allowed(self, env):
        client, _super_id, _viewer_id = env
        resp = client.get("/admin/products/anon-stats")
        assert resp.status_code == 200
        assert resp.json() == {"stats": "public"}

    def test_authenticated_still_allowed(self, env):
        client, super_id, _viewer_id = env
        resp = client.get("/admin/products/anon-stats", cookies=_cookie(super_id))
        assert resp.status_code == 200


class TestExplicitPermissionStillEnforced:
    def test_edit_permission_blocks_viewer(self, env):
        client, super_id, viewer_id = env
        assert client.get("/admin/products/manage", cookies=_cookie(super_id)).status_code == 200
        assert client.get("/admin/products/manage", cookies=_cookie(viewer_id)).status_code == 403
        assert client.get("/admin/products/manage").status_code == 401


class TestDecoratorMetadata:
    def test_allow_anonymous_defaults_false(self):
        from fastapi_admin_kit.admin.decorators import EndpointOptions

        opts = ProductEndpointAdmin.__dict__["no_permission"]._admin_endpoint
        assert isinstance(opts, EndpointOptions)
        assert opts.allow_anonymous is False
        assert opts.permission is None

    def test_allow_anonymous_flag_recorded(self):
        opts = ProductEndpointAdmin.__dict__["anon_stats"]._admin_endpoint
        assert opts.allow_anonymous is True
