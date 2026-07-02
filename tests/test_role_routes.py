from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit.admin import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.models import AdminRole, AdminUser
from fastapi_admin_kit.auth.session import SignedCookieSessionBackend
from fastapi_admin_kit.models.base import Base as AdminBase
from fastapi_admin_kit.views.roles import router as roles_router


@pytest.fixture(name="app")
def app_fixture() -> FastAPI:
    app = FastAPI()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    AdminBase.metadata.create_all(bind=engine)
    db_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
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
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    AdminBase.metadata.create_all(bind=engine)
    db_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)()
    yield db_session
    db_session.close()


def test_role_list_view_requires_auth(client: TestClient, db: Session):
    response = client.get("/admin/roles")
    assert response.status_code == 401


def test_role_list_view_lists_roles(client: TestClient, db: Session):
    db.add(AdminRole(name="Admin", description="Admins"))
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
