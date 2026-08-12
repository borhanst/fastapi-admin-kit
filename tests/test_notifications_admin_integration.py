"""Integration tests — notification endpoints inside a full admin app."""

from __future__ import annotations

import os
import tempfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.migrations.models import Role, User
from fastapi_admin_kit.models import Base as AdminBase
from fastapi_admin_kit.notifications import NotificationService, configure_notifications
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
from tests.test_notifications import FakeEmailProvider, FakeSMSProvider


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
def async_session_factory(engine):
    return sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def admin_user(engine, async_session_factory):
    async def _create():
        async with async_session_factory() as session:
            role = Role(name="SuperAdmin")
            session.add(role)
            await session.flush()
            user = User(
                email="admin@test.com",
                hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
                full_name="Admin",
                is_superuser=True,
                is_active=True,
            )
            user.roles.append(role)
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return user

    return run_async(_create())


@pytest.fixture
def app(engine, async_session_factory, admin_user):
    app = FastAPI()
    admin = Admin(app=app, engine=engine, secret_key=SECRET_KEY, auto_discover=False)

    service = NotificationService(session_factory=async_session_factory)
    service.register_sms_provider("twilio", FakeSMSProvider())
    service.register_email_provider("smtp", FakeEmailProvider())
    configure_notifications(app, service, prefix="/admin/notifications")

    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)
    return app


@pytest.fixture
def client(app, admin_user):
    client = TestClient(app)
    client.cookies.set("admin_session", create_session_cookie(admin_user.id))
    return client


def _admin_user_id(client) -> str:
    from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

    backend = SignedCookieSessionBackend(secret_key=SECRET_KEY)
    payload = backend.decode(client.cookies.get("admin_session"))
    return str(payload["user_id"])


def test_send_and_list_in_app(client):
    resp = client.post(
        "/admin/notifications/send",
        json={
            "user_id": _admin_user_id(client),
            "message": "Hello in-app",
            "channels": ["in_app"],
            "title": "Welcome",
        },
    )
    assert resp.status_code == 200, resp.text
    notification_id = resp.json()["notification_id"]
    assert notification_id is not None

    resp = client.get("/admin/notifications/")
    assert resp.status_code == 200, resp.text
    items = resp.json()
    assert any(n["id"] == notification_id for n in items)

    resp = client.get("/admin/notifications/unread-count")
    assert resp.status_code == 200
    assert resp.json()["count"] >= 1


def test_mark_read(client):
    resp = client.post(
        "/admin/notifications/send",
        json={
            "user_id": _admin_user_id(client),
            "message": "read me",
            "channels": ["in_app"],
        },
    )
    notification_id = resp.json()["notification_id"]

    resp = client.put(f"/admin/notifications/{notification_id}/read")
    assert resp.status_code == 200, resp.text

    resp = client.get("/admin/notifications/", params={"unread_only": True})
    assert resp.status_code == 200, resp.text
    assert all(not n["is_read"] for n in resp.json())


def test_mark_read_other_users_404(client):
    resp = client.put("/admin/notifications/999999/read")
    assert resp.status_code == 404


def test_preferences_authenticated(client):
    resp = client.put(
        "/admin/notifications/preferences",
        json={"channel": "sms", "enabled": False},
    )
    assert resp.status_code == 200, resp.text

    resp = client.get("/admin/notifications/preferences")
    assert resp.status_code == 200, resp.text
    assert resp.json()["sms"] is False


def test_unauthenticated_list_401(app):
    client = TestClient(app)
    resp = client.get("/admin/notifications/")
    assert resp.status_code == 401
