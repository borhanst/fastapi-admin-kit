"""Integration tests — /api/auth/token accepts HTTP Basic creds; Swagger
documents both Basic and Bearer security schemes."""

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
from fastapi_admin_kit.models import Base
from tests.conftest import SECRET_KEY, run_async


@pytest.fixture(autouse=True)
def _clear_registry():
    from fastapi_admin_kit.registry import AdminRegistry

    AdminRegistry().clear()
    yield
    AdminRegistry().clear()


@pytest.fixture
def engine():
    fd, path = tempfile.mkstemp()
    os.close(fd)
    sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(sync_engine)
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
                password="$2b$12$DOXzSwSZYp0Y1pTzEvWjO.KOLQg3wA/Ez1RkN4RHMiLqngoLM2lMG",
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
    app = FastAPI()
    run_async(admin.setup(app))
    return TestClient(app)


def test_openapi_exposes_basic_and_bearer_schemes(client):
    schema = client.get("/openapi.json").json()
    schemes = schema["components"]["securitySchemes"]

    assert schemes["BasicAuth"]["type"] == "http"
    assert schemes["BasicAuth"]["scheme"] == "basic"
    assert schemes["BearerAuth"]["type"] == "http"
    assert schemes["BearerAuth"]["scheme"] == "bearer"

    # Token endpoint requires Basic; protected CRUD/roles require Bearer.
    assert schema["paths"]["/api/auth/token"]["post"]["security"] == [{"BasicAuth": []}]
    assert schema["paths"]["/api/roles/"]["get"]["security"] == [{"BearerAuth": []}]


def test_token_endpoint_accepts_basic_auth(client):
    creds = base64.b64encode(b"test@example.com:secret").decode()
    response = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"})
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["token_type"] == "bearer"


def test_token_endpoint_rejects_bad_basic_auth(client):
    creds = base64.b64encode(b"test@example.com:wrong").decode()
    response = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"})
    assert response.status_code == 401


def test_token_endpoint_still_accepts_json_body(client):
    response = client.post(
        "/api/auth/token",
        json={"email": "test@example.com", "password": "secret"},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_token_endpoint_without_credentials_is_422(client):
    response = client.post("/api/auth/token")
    assert response.status_code == 422


def test_protected_route_without_bearer_is_401(client):
    response = client.get("/api/roles/")
    assert response.status_code == 401


def test_bearer_token_grants_access_to_protected_route(client):
    creds = base64.b64encode(b"test@example.com:secret").decode()
    token_resp = client.post("/api/auth/token", headers={"Authorization": f"Basic {creds}"})
    token = token_resp.json()["access_token"]

    response = client.get("/api/roles/", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
