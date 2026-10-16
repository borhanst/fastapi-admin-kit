"""Tests for the notification API endpoints."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit.models import Base as AdminBase
from fastapi_admin_kit.notifications import (
    NotificationService,
    configure_notifications,
    notifications_router,
)
from tests.test_notifications import FakeEmailProvider, FakeSMSProvider


@pytest.fixture
def app():
    app = FastAPI()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AdminBase.metadata.create_all(engine)
    factory = sessionmaker(engine)

    service = NotificationService(session_factory=factory)
    service.register_sms_provider("twilio", FakeSMSProvider())
    service.register_email_provider("smtp", FakeEmailProvider())
    configure_notifications(app, service, prefix="/api/notifications")
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def test_send_requires_auth(client):
    """The send API is gated: anonymous callers must not trigger outbound sends."""
    resp = client.post(
        "/api/notifications/send",
        json={
            "user_id": "user-1",
            "message": "API test",
            "channels": ["email"],
            "email": "user@example.com",
        },
    )
    assert resp.status_code == 401, resp.text


def test_send_in_app_and_list(client):
    # send is gated behind authentication
    resp = client.post(
        "/api/notifications/send",
        json={
            "user_id": "user-1",
            "message": "In-app hello",
            "channels": ["in_app"],
            "title": "Hi",
        },
    )
    assert resp.status_code == 401, resp.text

    # list requires auth — should 401 without a session
    resp = client.get("/api/notifications/")
    assert resp.status_code in (401,)


def test_send_batch_requires_auth(client):
    resp = client.post(
        "/api/notifications/send/batch",
        json={
            "recipients": [
                {"user_id": "u1", "email": "a@example.com"},
                {"user_id": "u2", "email": "b@example.com"},
            ],
            "message": "batch",
            "channels": ["email"],
        },
    )
    assert resp.status_code == 401, resp.text


def test_sse_stream_requires_auth(client):
    resp = client.get("/api/notifications/stream")
    assert resp.status_code == 401


def test_sse_stream_ignores_user_id_query_param(client):
    """A client-supplied user_id must never authenticate the SSE stream (IDOR)."""
    resp = client.get("/api/notifications/stream?user_id=victim")
    assert resp.status_code == 401


def test_unconfigured_service_returns_500():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from fastapi_admin_kit.notifications.router import _require_send_authorization

    app = FastAPI()
    app.include_router(notifications_router, prefix="/api/notifications")
    # Bypass the auth gate to exercise the "service not configured" path.
    app.dependency_overrides[_require_send_authorization] = lambda: "test-admin"
    client = TestClient(app)

    resp = client.post(
        "/api/notifications/send",
        json={"user_id": "u1", "message": "x", "channels": ["email"]},
    )
    assert resp.status_code == 500
    assert "not configured" in resp.json()["detail"]


def test_preferences_endpoint():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from fastapi_admin_kit.models import Base as AdminBase
    from fastapi_admin_kit.notifications import NotificationService

    app = FastAPI()
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    AdminBase.metadata.create_all(engine)
    service = NotificationService(session_factory=sessionmaker(engine))
    app.state.notification_service = service
    app.include_router(notifications_router, prefix="/api/notifications")
    client = TestClient(app)

    # Auth required for preference endpoints
    resp = client.put(
        "/api/notifications/preferences",
        json={"channel": "sms", "enabled": False},
    )
    assert resp.status_code == 401
