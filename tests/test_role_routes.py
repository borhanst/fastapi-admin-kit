from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit.auth.csrf import require_csrf_token
from fastapi_admin_kit.auth.dependencies import require_superuser
from fastapi_admin_kit.auth.models import (
    Permission,
    Role,
    admin_role_permissions,
)
from fastapi_admin_kit.auth.session import SignedCookieSessionBackend
from fastapi_admin_kit.db import SessionMiddleware
from fastapi_admin_kit.models.base import Base as AdminBase
from fastapi_admin_kit.views.roles import (
    router as roles_router,
)
from tests.conftest import SECRET_KEY, run_async


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    app = FastAPI()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    AdminBase.metadata.create_all(bind=engine)
    db_session = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )()
    app.state.admin_db_session = db_session
    app.state.admin_jinja_env = None
    app.state.admin_registry = None
    app.state.admin_auth_backend = None
    app.state.admin_config = {"admin_path": "/admin"}
    app.state.admin_session_backend = SignedCookieSessionBackend(
        secret_key="test-secret-key-long-enough-for-security!"
    )
    app.include_router(roles_router, prefix="/admin")
    return app


@pytest.fixture(name="client")
def client_fixture(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(name="db")
def db_fixture() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    AdminBase.metadata.create_all(bind=engine)
    db_session = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, expire_on_commit=False
    )()
    yield db_session
    db_session.close()


def test_role_list_view_requires_auth(client: TestClient, db: Session):
    response = client.get("/admin/roles")
    assert response.status_code == 401


def test_role_list_view_lists_roles(client: TestClient, db: Session):
    db.add(Role(name="Admin", description="Admins"))
    db.commit()
    response = client.get("/admin/roles", cookies={"admin_session": "dummy"})
    assert response.status_code == 401


def test_role_create_requires_auth(client: TestClient):
    response = client.get("/admin/roles/create")
    assert response.status_code == 401


def test_role_edit_requires_auth(client: TestClient, db: Session):
    response = client.get("/admin/roles/1")
    assert response.status_code == 401


def test_role_delete_requires_auth(client: TestClient, db: Session):
    response = client.post("/admin/roles/1/delete")
    assert response.status_code == 401


def test_role_save_requires_auth(client: TestClient):
    response = client.post("/admin/roles/1")
    assert response.status_code == 401


async def _init_async_metadata(engine, base):
    async with engine.begin() as conn:
        await conn.run_sync(base.metadata.create_all)


class _DummySuperuser:
    is_superuser = True


def test_role_create_and_save_persist_junction_async():
    """Regression: role save must write admin_role_permissions under AsyncSession.

    Accessing the ORM M2M collection (clear/append) under AsyncSession raises
    MissingGreenlet; the views now write the junction table directly.
    """
    app = FastAPI()
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    run_async(_init_async_metadata(engine, AdminBase))
    factory = async_sessionmaker(bind=engine, expire_on_commit=False)

    app.state.admin_session_factory = factory
    app.state.admin_db_session = None
    app.state.admin_jinja_env = None
    app.state.admin_registry = None
    app.state.admin_config = {"admin_path": "/admin"}
    app.state.admin_auth_backend = SignedCookieSessionBackend(secret_key=SECRET_KEY)
    app.include_router(roles_router, prefix="/admin")
    app.add_middleware(SessionMiddleware)

    app.dependency_overrides[require_superuser] = lambda: _DummySuperuser()
    app.dependency_overrides[require_csrf_token] = lambda: True

    async def _seed():
        async with factory() as s:
            s.add(Permission(name="perm1", table_name="t1"))
            await s.commit()

    run_async(_seed())

    client = TestClient(app, raise_server_exceptions=False, follow_redirects=False)

    # Create role with permission id 1
    resp = client.post("/admin/roles", data={"name": "Editor", "perm_ids": "[1]"})
    assert resp.status_code == 302

    async def _read():
        async with factory() as s:
            role = (await s.execute(select(Role).where(Role.name == "Editor"))).scalar_one()
            rows = (await s.execute(select(admin_role_permissions))).fetchall()
            return role.id, [(r.role_id, r.permission_id) for r in rows]

    role_id, rows = run_async(_read())
    assert (role_id, 1) in rows

    # Save: replace permissions with an empty set -> junction cleared
    resp = client.post(f"/admin/roles/{role_id}", data={"perm_ids": "[]"})
    assert resp.status_code == 302

    async def _read_after():
        async with factory() as s:
            return (await s.execute(select(admin_role_permissions))).fetchall()

    assert run_async(_read_after()) == []
