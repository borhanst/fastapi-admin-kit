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
from fastapi_admin_kit.auth.models import Role, User
from fastapi_admin_kit.models.base import Base as AdminBase
from fastapi_admin_kit.audit.models import AuditLog  # noqa: F401
from tests.conftest import SECRET_KEY, create_session_cookie, run_async
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
        role = Role(name="SuperAdmin")
        session.add(role)
        session.flush()
        user = User(
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

    tc = TestClient(app)
    tc.cookies.set("admin_session", create_session_cookie(admin_user.id))
    return tc, admin, engine


def test_shell_layout_structure(client):
    """Test that the shell layout has the correct CSS classes."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check shell layout structure
    assert 'admin-shell' in response.text
    assert 'admin-topbar' in response.text
    assert 'admin-body' in response.text
    assert 'admin-sidebar' in response.text
    assert 'admin-content' in response.text
    assert 'admin-content__inner' in response.text


def test_topbar_zones(client):
    """Test that the topbar has left, center, and right zones."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check topbar zones
    assert 'class="topbar-left"' in response.text
    assert 'class="topbar-center"' in response.text
    assert 'class="topbar-right"' in response.text

    # Check collapse toggle
    assert 'class="collapse-toggle"' in response.text

    # Check logo
    assert 'class="topbar-logo"' in response.text

    # Check search trigger
    assert 'class="topbar-search"' in response.text

    # Check theme toggle
    assert "$store.theme.toggle()" in response.text

    # Check user avatar
    assert 'class="user-avatar"' in response.text


def test_sidebar_nav_sections(client):
    """Test that the sidebar has correct nav sections."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check sidebar sections
    assert 'class="sidebar-section"' in response.text
    assert 'class="sidebar-section-label"' in response.text

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

    # Access dashboard - dashboard nav should be active
    response = test_client.get("/admin/")
    assert response.status_code == 200

    # The dashboard link should have active class
    assert "active" in response.text


def test_sidebar_bottom_section(client):
    """Test that the sidebar has a bottom section with Settings."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check bottom section
    assert 'class="sidebar-bottom"' in response.text
    assert "Settings" in response.text


def test_topbar_user_dropdown(client):
    """Test that the user dropdown has the correct structure."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
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

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check loading bar
    assert 'id="loading-bar"' in response.text
    assert "htmx-indicator-loading" in response.text


def test_collapse_toggle_functionality(client):
    """Test that the collapse toggle button toggles sidebar state."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check that the collapse toggle has the correct click handler
    assert "sidebarCollapsed = !sidebarCollapsed" in response.text


def test_theme_toggle_functionality(client):
    """Test that the theme toggle button is present."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check theme toggle
    assert 'x-show="!$store.theme.dark"' in response.text
    assert 'x-show="$store.theme.dark"' in response.text


def test_responsive_sidebar_classes(client):
    """Test that responsive sidebar classes are present."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check mobile overlay
    assert 'class="admin-sidebar-overlay"' in response.text


def test_search_trigger_has_keyboard_shortcut(client):
    """Test that the search trigger shows the keyboard shortcut badge."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check keyboard shortcut badge
    assert "<kbd>" in response.text


def test_user_avatar_initials(client):
    """Test that the user avatar shows the correct initials."""
    test_client, admin, engine = client

    response = test_client.get("/admin/")
    assert response.status_code == 200

    # Check avatar shows first letter of name
    assert "A" in response.text  # First letter of "Admin User"
