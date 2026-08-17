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


@pytest.fixture
def api_prefix_app(engine, async_session_factory, admin_user):
    """Admin app with notifications mounted under a non-default prefix."""
    app = FastAPI()
    admin = Admin(app=app, engine=engine, secret_key=SECRET_KEY, auto_discover=False)

    service = NotificationService(session_factory=async_session_factory)
    configure_notifications(app, service, prefix="/api/notifications")

    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)
    return app, admin


def test_admin_paths_synced_to_mount_prefix(api_prefix_app, admin_user):
    """The admin template/JS must point at the real mount prefix, not /admin/notifications."""
    app, admin = api_prefix_app
    assert admin.config.notifications_api_path == "/api/notifications"
    assert admin.config.notifications_list_path == "/api/notifications/"

    client = TestClient(app)
    client.cookies.set("admin_session", create_session_cookie(admin_user.id))
    resp = client.get("/admin/")
    assert resp.status_code == 200
    html = resp.text
    assert 'window.__NOTIFICATIONS_API_PATH__ = "/api/notifications"' in html.replace(
        "</script>", ""
    )

    # The frontend endpoints resolve at the synced prefix.
    resp = client.get("/api/notifications/unread-count")
    assert resp.status_code == 200


def test_explicit_admin_path_respected(engine, async_session_factory, admin_user):
    """A user-provided notifications_api_path is never overwritten by configure_notifications."""
    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auto_discover=False,
        notifications_api_path="/custom/notifications",
    )

    service = NotificationService(session_factory=async_session_factory)
    configure_notifications(app, service, prefix="/api/notifications")

    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)

    assert admin.config.notifications_api_path == "/custom/notifications"
    assert admin.config.notifications_list_path == "/custom/notifications/"


# ---------------------------------------------------------------------------
# Admin auto-configuration (enable_notification default True)
# ---------------------------------------------------------------------------


def test_admin_auto_configures_notifications(engine, async_session_factory, admin_user):
    """Admin wires up the notification system without configure_notifications()."""
    app = FastAPI()
    admin = Admin(app=app, engine=engine, secret_key=SECRET_KEY, auto_discover=False)

    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)

    service = getattr(app.state, "notification_service", None)
    assert service is not None
    assert isinstance(service, NotificationService)

    # Router mounted at the default admin notifications path and reachable.
    client = TestClient(app)
    resp = client.get("/admin/notifications/unread-count")
    assert resp.status_code == 401  # route exists, requires auth
    resp = client.get("/api/notifications/unread-count")
    assert resp.status_code == 404  # not mounted outside the admin path


def test_admin_uses_provided_notification_service(engine, async_session_factory, admin_user):
    """Admin(notification_service=...) mounts the user's service, no manual call."""
    app = FastAPI()
    service = NotificationService(session_factory=async_session_factory)
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auto_discover=False,
        notification_service=service,
        notifications_api_path="/custom/notifications",
    )

    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)

    assert app.state.notification_service is service
    assert admin._notification_service is service
    client = TestClient(app)
    resp = client.get("/custom/notifications/unread-count")
    assert resp.status_code == 401


def test_admin_enable_notification_false(engine, async_session_factory, admin_user):
    """enable_notification=False disables the auto-mounted notification router."""
    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auto_discover=False,
        enable_notification=False,
    )

    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)

    assert getattr(app.state, "notification_service", None) is None
    client = TestClient(app)
    resp = client.get("/admin/notifications/unread-count")
    assert resp.status_code == 404


def test_admin_does_not_double_mount(engine, async_session_factory, admin_user):
    """A service already registered via configure_notifications is not re-mounted."""
    app = FastAPI()
    admin = Admin(app=app, engine=engine, secret_key=SECRET_KEY, auto_discover=False)

    service = NotificationService(session_factory=async_session_factory)
    configure_notifications(app, service, prefix="/admin/notifications")

    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)

    assert app.state.notification_service is service


def test_frontend_flag_disabled_hides_bell(engine, async_session_factory, admin_user):
    """enable_notification=False: no bell rendered, frontend flag set to false.

    The dropdown JS reads ``window.__NOTIFICATIONS_ENABLED__`` and never polls
    or opens WebSockets when it is false.
    """
    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auto_discover=False,
        enable_notification=False,
    )
    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)

    client = TestClient(app)
    client.cookies.set("admin_session", create_session_cookie(admin_user.id))
    resp = client.get("/admin/")
    assert resp.status_code == 200, resp.text
    html = resp.text
    assert "window.__NOTIFICATIONS_ENABLED__ = false" in html.replace("</script>", "")
    assert "topbar-notifications" not in html
    assert "notificationDropdown" not in html


def test_frontend_flag_enabled_by_default(engine, async_session_factory, admin_user):
    """Default enable_notification=True: bell rendered and flag set to true."""
    app = FastAPI()
    admin = Admin(app=app, engine=engine, secret_key=SECRET_KEY, auto_discover=False)
    os.environ["SKIP_CREATE_TABLES"] = "true"
    try:
        run_async(admin.setup(app))
    finally:
        os.environ.pop("SKIP_CREATE_TABLES", None)

    client = TestClient(app)
    client.cookies.set("admin_session", create_session_cookie(admin_user.id))
    resp = client.get("/admin/")
    assert resp.status_code == 200, resp.text
    html = resp.text
    assert "window.__NOTIFICATIONS_ENABLED__ = true" in html.replace("</script>", "")
    assert "topbar-notifications" in html
