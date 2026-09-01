"""Regression tests for S01 — stale JWT must not keep revoked privileges.

The JWT used to embed roles/permissions/is_superuser and the API trusted
that snapshot: revoking a permission, demoting a superuser or deactivating
an account had no effect until token expiry. Authorization is now always
evaluated against live DB state.
"""

from __future__ import annotations

import asyncio
import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin, ModelAdmin
from fastapi_admin_kit.api.auth import create_access_token
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.migrations.models import Permission, Role, User
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


class _ProductAdmin(ModelAdmin):
    list_display = ["id", "name"]


async def _seed(engine):
    async with AsyncSession(engine) as session:
        role = Role(name="Viewer")
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

        editor_role = Role(name="Editor")
        edit_perm = Permission(
            name="products_edit",
            table_name="products",
            can_view=True,
            can_create=True,
            can_edit=True,
            can_delete=True,
            can_export=False,
            can_import=False,
        )
        editor_role.permissions.append(edit_perm)
        session.add(edit_perm)

        viewer = User(
            email="viewer@test.com",
            password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Viewer",
            is_superuser=False,
            is_active=True,
        )
        viewer.roles.append(role)

        # Role with NO product permissions: pre-demotion access comes
        # solely from is_superuser, making the stale-claim test meaningful.
        bare_role = Role(name="BareRole")
        session.add(bare_role)

        superuser = User(
            email="super@test.com",
            password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Super",
            is_superuser=True,
            is_active=True,
        )
        superuser.roles.append(bare_role)

        session.add_all([role, editor_role, bare_role, viewer, superuser])
        await session.flush()
        ids = (viewer.id, superuser.id)
        await session.commit()
        return ids


async def _mint(engine, user_id):
    from sqlalchemy.orm import selectinload

    async with AsyncSession(engine) as session:
        result = await session.execute(
            select(User).where(User.id == user_id).options(selectinload(User.roles))
        )
        user = result.scalars().first()
        return create_access_token(user, SECRET_KEY)


@pytest.fixture
def env(engine):
    viewer_id, super_id = run_async(_seed(engine))

    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
        session_secure=False,
    )
    admin.register(Product, _ProductAdmin)
    asyncio.run(admin.setup(app))

    viewer_jwt = run_async(_mint(engine, viewer_id))
    super_jwt = run_async(_mint(engine, super_id))

    client = TestClient(app)
    return client, engine, viewer_id, viewer_jwt, super_id, super_jwt


def _auth(client: TestClient, jwt_token: str) -> TestClient:
    client.headers.update({"Authorization": f"Bearer {jwt_token}"})
    return client


class TestRevokedPermissionDeniedImmediately:
    def test_revoked_view_permission_denied_despite_valid_jwt(self, env):
        client, engine, viewer_id, viewer_jwt, *_ = env
        _auth(client, viewer_jwt)
        assert client.get("/api/products").status_code == 200

        # Revoke the role's view permission.
        async def _revoke():
            async with AsyncSession(engine) as session:
                result = await session.execute(
                    select(Permission).where(Permission.name == "products_view")
                )
                perm = result.scalars().first()
                perm.can_view = False
                await session.commit()

        run_async(_revoke())
        resp = client.get("/api/products")
        assert resp.status_code == 403

    def test_newly_granted_permission_allowed(self, env):
        client, engine, viewer_id, viewer_jwt, *_ = env
        _auth(client, viewer_jwt)
        assert client.get("/api/products").status_code == 200

        async def _grant():
            async with AsyncSession(engine) as session:
                result = await session.execute(
                    select(Permission).where(Permission.name == "products_view")
                )
                perm = result.scalars().first()
                perm.can_create = True
                await session.commit()

        run_async(_grant())
        resp = client.post("/api/products", json={"name": "New", "price": 5})
        assert resp.status_code == 201


class TestDemotedSuperuserDeniedImmediately:
    def test_demotion_denies_access_despite_stale_claim(self, env):
        client, engine, _, _, super_id, super_jwt = env
        _auth(client, super_jwt)
        assert client.get("/api/products").status_code == 200

        async def _demote():
            async with AsyncSession(engine) as session:
                result = await session.execute(select(User).where(User.id == super_id))
                user = result.scalars().first()
                user.is_superuser = False
                await session.commit()

        run_async(_demote())
        resp = client.get("/api/products")
        assert resp.status_code == 403


class TestDeactivatedUserDeniedImmediately:
    def test_deactivation_blocks_api_access(self, env):
        client, engine, viewer_id, viewer_jwt, *_ = env
        _auth(client, viewer_jwt)
        assert client.get("/api/products").status_code == 200

        async def _deactivate():
            async with AsyncSession(engine) as session:
                result = await session.execute(select(User).where(User.id == viewer_id))
                user = result.scalars().first()
                user.is_active = False
                await session.commit()

        run_async(_deactivate())
        resp = client.get("/api/products")
        assert resp.status_code == 401
