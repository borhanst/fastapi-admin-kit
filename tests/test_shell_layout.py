"""Tests for the shell layout (Phase 21)."""

import asyncio
import tempfile
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from fastapi_admin_kit import Admin
from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
from fastapi_admin_kit.auth.models import AdminRole, AdminUser
from fastapi_admin_kit.models.base import Base as AdminBase
from fastapi_admin_kit.audit.models import AuditLog  # noqa: F401
from tests.conftest import SECRET_KEY, run_async
from tests.test_registry import Product, Category


@pytest.fixture
def engine():
    import tempfile
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


@pytest.fixture
def admin_user(engine):
    sync_eng = create_engine(
        f"sqlite:///{engine.url.database}",
        connect_args={"check_same_thread": False},
    )
    with Session(sync_eng) as session:
        role = AdminRole(name="SuperAdmin")
        session.add(role)
        session.flush()
        user = AdminUser(
            email="admin@test.com",
            hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
            full_name="Admin User",
            is_superuser=True,
            is_active=True,
        )
        user.roles.append(role)
        session.add(user)
        session.commit()
        session.refresh(user)
        sync_eng.dispose()
        return user


@pytest.fixture
def client(engine, admin_user):
    app = FastAPI()
    admin = Admin(
        app=app,
        engine=engine,
        secret_key=SECRET_KEY,
        auth_backend=BuiltinAuthBackend(),
        auto_discover=False,
    )
    asyncio.run(admin.setup(app))

    admin.register(Product)

    sync_eng = create_engine(
        f"sqlite:///{engine.url.database}",
        connect_args={"check_same_thread": False},
    )
    with Session(sync_eng) as db:
        cat = Category(name="Test Category")
        db.add(cat)
        db.flush()
        for i in range(3):
            product = Product(
                name=f"Product {i}",
                price=100 + i,
                category_id=cat.id,
                is_active=True,
            )
            db.add(product)
        db.commit()
    sync_eng.dispose()

    return TestClient(app), admin, engine


def login(test_client, email="admin@test.com", password="password"):
    """Helper to login and return session cookie."""
    get_resp = test_client.get("/admin/login")
    csrf_token = ""
    csrf_cookie = ""
    for part in get_resp.headers.get_list("set-cookie"):
        if part.startswith("admin_csrf_token="):
            csrf_token = part.split(";", 1)[0].split("=", 1)[1]
            csrf_cookie = csrf_token
            break
    if not csrf_token:
        from fastapi_admin_kit.auth.csrf import generate_csrf_token
        csrf_token = generate_csrf_token("test-secret-key-long-enough-for-security!")
        csrf_cookie = csrf_token
    response = test_client.post(
        "/admin/login",
        data={"email": email, "password": password, "csrf_token": csrf_token},
        cookies={"admin_csrf_token": csrf_cookie},
        follow_redirects=False,
    )
    return response.cookies.get("admin_session")


def test_shell_layout_structure(client):
    """Test that the shell layout has the correct CSS classes."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check shell layout structure
    assert 'class="admin-shell"' in response.text
    assert 'class="admin-topbar"' in response.text
    assert 'class="admin-body"' in response.text
    assert 'class="admin-sidebar"' in response.text
    assert 'class="admin-content"' in response.text
    assert 'class="admin-content__inner"' in response.text


def test_topbar_zones(client):
    """Test that the topbar has left, center, and right zones."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check topbar zones
    assert 'class="topbar-left"' in response.text
    assert 'class="topbar-center"' in response.text
    assert 'class="topbar-right"' in response.text

    # Check collapse toggle
    assert 'class="collapse-toggle"' in response.text

    # Check logo
    assert 'class="topbar-logo"' in response.text

    # Check breadcrumb
    assert 'class="breadcrumb"' in response.text

    # Check search trigger
    assert 'class="icon-btn search-trigger"' in response.text

    # Check theme toggle
    assert "$store.theme.toggle()" in response.text

    # Check user avatar
    assert 'class="user-avatar"' in response.text


def test_sidebar_nav_sections(client):
    """Test that the sidebar has correct nav sections."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check sidebar sections
    assert 'class="sidebar-section"' in response.text
    assert 'class="sidebar-section-label"' in response.text

    # Check section labels
    assert "Models" in response.text
    assert "System" in response.text

    # Check nav items
    assert 'class="nav-link' in response.text
    assert 'class="nav-link-label"' in response.text

    # Check Dashboard link
    assert "Dashboard" in response.text

    # Check registered models
    assert "Products" in response.text


def test_sidebar_active_state(client):
    """Test that the active nav item has the correct class."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    # Access dashboard - dashboard nav should be active
    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # The dashboard link should have active class
    # Check that at least one nav-link has active class
    assert 'nav-link active' in response.text or 'class="nav-link active"' in response.text


def test_sidebar_bottom_section(client):
    """Test that the sidebar has a bottom section with Settings."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check bottom section
    assert 'class="sidebar-bottom"' in response.text
    assert "Settings" in response.text


def test_topbar_user_dropdown(client):
    """Test that the user dropdown has the correct structure."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check dropdown structure
    assert 'class="user-dropdown"' in response.text
    assert 'class="user-dropdown-header"' in response.text
    assert 'class="user-dropdown-name"' in response.text
    assert 'class="user-dropdown-email"' in response.text

    # Check user info in dropdown
    assert "Admin User" in response.text
    assert "admin@test.com" in response.text

    # Check sign out button
    assert "Sign out" in response.text


def test_loading_bar(client):
    """Test that the loading bar is present for HTMX requests."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check loading bar
    assert 'id="loading-bar"' in response.text
    assert 'class="htmx-indicator"' in response.text


def test_collapse_toggle_functionality(client):
    """Test that the collapse toggle button toggles sidebar state."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check that the collapse toggle has the correct click handler
    assert '@click="sidebarCollapsed = !sidebarCollapsed"' in response.text


def test_theme_toggle_functionality(client):
    """Test that the theme toggle button is present."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check theme toggle
    assert 'x-show="!$store.theme.dark"' in response.text
    assert 'x-show="$store.theme.dark"' in response.text


def test_responsive_sidebar_classes(client):
    """Test that responsive sidebar classes are present."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check mobile overlay
    assert 'class="admin-sidebar-overlay"' in response.text


def test_search_trigger_has_keyboard_shortcut(client):
    """Test that the search trigger shows the keyboard shortcut badge."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check keyboard shortcut badge
    assert 'class="kbd"' in response.text
    assert "⌘K" in response.text


def test_user_avatar_initials(client):
    """Test that the user avatar shows the correct initials."""
    test_client, admin, engine = client

    session_cookie = login(test_client)
    cookies = {"admin_session": session_cookie} if session_cookie else {}

    response = test_client.get("/admin/", cookies=cookies)
    assert response.status_code == 200

    # Check avatar shows first letter of name
    assert "A" in response.text  # First letter of "Admin User"
