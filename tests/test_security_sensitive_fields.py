"""Regression tests for S04 — sensitive columns must never leak via API/export.

GET /api/admin_users previously returned hashed_password (bcrypt) to any
caller with view permission; CSV export included it as well.
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

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.migrations.models import User
from fastapi_admin_kit.models.base import Base as AdminBase
from tests.conftest import SECRET_KEY, create_session_cookie, run_async


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


@pytest.fixture
def env(engine):
    async def _seed():
        async with AsyncSession(engine) as session:
            user = User(
                email="admin@test.com",
                hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
                full_name="Admin",
                is_superuser=True,
                is_active=True,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user.id

    user_id = run_async(_seed())

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

    from fastapi_admin_kit.api.auth import create_access_token

    async def _mint_token():
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        async with AsyncSession(engine) as session:
            result = await session.execute(
                select(User).where(User.id == user_id).options(selectinload(User.roles))
            )
            user = result.scalars().first()
            return create_access_token(user, SECRET_KEY)

    jwt_token = run_async(_mint_token())

    client = TestClient(app)
    client.cookies.set("admin_session", create_session_cookie(user_id, SECRET_KEY))
    token = generate_csrf_token(SECRET_KEY)
    client.cookies.set("admin_csrf_token", token)
    client.headers.update({"X-CSRF-Token": token, "Authorization": f"Bearer {jwt_token}"})
    return client


class TestSensitiveFieldsNotInApi:
    def test_item_api_hides_hashed_password(self, env):
        client = env
        resp = client.get("/api/admin_users/1")
        assert resp.status_code == 200
        assert "hashed_password" not in resp.json()

    def test_list_api_hides_hashed_password(self, env):
        client = env
        resp = client.get("/api/admin_users")
        assert resp.status_code == 200
        data = resp.json()
        items = data["items"] if isinstance(data, dict) else data
        assert items
        for item in items:
            assert "hashed_password" not in item

    def test_openapi_response_schema_hides_hashed_password(self, env):
        client = env
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        schema_text = repr(resp.json()["components"]["schemas"])
        assert "hashed_password" not in schema_text


class TestSensitiveFieldsNotInExport:
    def test_csv_export_hides_hashed_password(self, env):
        client = env
        resp = client.get("/admin/admin_users/export/?format=csv")
        assert resp.status_code == 200
        content = b"".join(resp.stream).decode()
        assert "$2b$" not in content
        assert "hashed_password" not in content
