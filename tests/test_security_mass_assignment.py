"""Regression tests for S07 — privilege escalation via mass assignment.

A non-superuser with edit permission on admin_users could previously set
``is_superuser=true`` (or toggle is_active / roles / hashed_password) by
submitting it in the form or JSON body. Privileged fields are now stripped
unless a superuser is acting.
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

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import generate_csrf_token
from fastapi_admin_kit.migrations.models import Permission, Role, User
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


async def _seed_users(engine):
    """Superuser 'admin' + non-superuser 'editor' with edit on admin_users."""
    async with AsyncSession(engine) as session:
        super_role = Role(name="SuperAdmin")
        editor_role = Role(name="Editor")

        perm = Permission(
            name="admin_users_edit",
            table_name="admin_users",
            can_view=True,
            can_create=True,
            can_edit=True,
            can_delete=False,
            can_export=False,
            can_import=False,
        )
        editor_role.permissions.append(perm)
        session.add(perm)

        admin = User(
            email="admin@test.com",
            hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Admin",
            is_superuser=True,
            is_active=True,
        )
        admin.roles.append(super_role)

        editor = User(
            email="editor@test.com",
            hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Editor",
            is_superuser=False,
            is_active=True,
        )
        editor.roles.append(editor_role)

        victim = User(
            email="victim@test.com",
            hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Victim",
            is_superuser=False,
            is_active=True,
        )

        session.add_all([super_role, editor_role, admin, editor, victim])
        await session.commit()
        await session.refresh(admin)
        await session.refresh(editor)
        await session.refresh(victim)
        return admin.id, editor.id, victim.id


@pytest.fixture
def env(engine):
    ids = run_async(_seed_users(engine))
    admin_id, editor_id, victim_id = ids

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

    async def _mint(subject_id):
        from sqlalchemy.orm import selectinload

        async with AsyncSession(engine) as session:
            result = await session.execute(
                select(User).where(User.id == subject_id).options(selectinload(User.roles))
            )
            user = result.scalars().first()
            return create_access_token(user, SECRET_KEY)

    editor_jwt = run_async(_mint(editor_id))
    admin_jwt = run_async(_mint(admin_id))

    client = TestClient(app)
    client.cookies.set("admin_session", create_session_cookie(editor_id, SECRET_KEY))
    token = generate_csrf_token(SECRET_KEY)
    client.cookies.set("admin_csrf_token", token)
    client.headers.update({"X-CSRF-Token": token, "Authorization": f"Bearer {editor_jwt}"})
    return client, engine, admin_id, victim_id, admin_jwt


async def _get_user(engine, user_id):
    async with AsyncSession(engine) as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalars().first()
        await session.refresh(user, ["roles"])
        return user


class TestNonSuperuserCannotEscalate:
    def test_html_edit_cannot_grant_superuser(self, env):
        client, engine, _, victim_id, _jwt = env
        resp = client.post(
            f"/admin/admin_users/{victim_id}",
            data={
                "email": "victim@test.com",
                "full_name": "Victim",
                "is_superuser": "on",
                "is_active": "on",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302, 303)
        victim = run_async(_get_user(engine, victim_id))
        assert victim.is_superuser is False

    def test_json_edit_cannot_grant_superuser(self, env):
        client, engine, _, victim_id, _jwt = env
        resp = client.put(
            f"/api/admin_users/{victim_id}",
            json={"is_superuser": True, "full_name": "Hacked"},
        )
        assert resp.status_code in (200, 204)
        victim = run_async(_get_user(engine, victim_id))
        assert victim.is_superuser is False

    def test_editor_cannot_deactivate_other_users(self, env):
        client, engine, _, victim_id, _jwt = env
        resp = client.post(
            f"/admin/admin_users/{victim_id}",
            data={"email": "victim@test.com", "is_active": ""},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302, 303)
        victim = run_async(_get_user(engine, victim_id))
        assert victim.is_active is True

    def test_create_cannot_set_superuser(self, env):
        client, engine, *_a, _jwt = env
        resp = client.post(
            "/admin/admin_users/create",
            data={
                "email": "new@test.com",
                "password": "Str0ng!Passw0rd#9",
                "is_superuser": "on",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302, 303)

        async def _find():
            async with AsyncSession(engine) as session:
                result = await session.execute(select(User).where(User.email == "new@test.com"))
                return result.scalars().first()

        created = run_async(_find())
        if created is not None:
            assert created.is_superuser is False


class TestSuperuserKeepsControl:
    def test_superuser_can_toggle_is_active(self, env):
        client, engine, admin_id, victim_id, admin_jwt = env
        client.cookies.set("admin_session", create_session_cookie(admin_id, SECRET_KEY))
        resp = client.post(
            f"/admin/admin_users/{victim_id}",
            data={"email": "victim@test.com", "is_active": ""},
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302, 303)
        victim = run_async(_get_user(engine, victim_id))
        assert victim.is_active is False
