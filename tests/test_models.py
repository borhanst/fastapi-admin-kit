"""Tests for Phase 6 — Database Models (Admin Tables)."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from fastapi_admin_kit.audit.models import AuditLog
from fastapi_admin_kit.auth.models import (
    Permission,
    Role,
    User,
)
from fastapi_admin_kit.auth.protocol import AdminUserProtocol
from fastapi_admin_kit.models import Base


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


# ── Table existence ──────────────────────────────────────────────────────


def test_all_tables_created(engine):
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert "admin_roles" in tables
    assert "admin_users" in tables
    assert "admin_permissions" in tables
    assert "admin_user_roles" in tables
    assert "admin_audit_log" in tables


# ── Role ────────────────────────────────────────────────────────────


def test_admin_role_create(session):
    role = Role(name="Admin", description="Full access")
    session.add(role)
    session.flush()
    assert role.id is not None
    assert role.name == "Admin"


def test_admin_role_unique_name(session):
    session.add(Role(name="Admin"))
    session.flush()
    with pytest.raises(Exception):
        session.add(Role(name="Admin"))
        session.flush()


# ── User ────────────────────────────────────────────────────────────


def test_admin_user_create(session):
    role = Role(name="Editor")
    session.add(role)
    session.flush()

    user = User(
        email="admin@example.com",
        hashed_password="hashed_secret",
        full_name="Test Admin",
        is_superuser=False,
        is_active=True,
    )
    user.roles.append(role)
    session.add(user)
    session.flush()
    assert user.id is not None
    assert user.email == "admin@example.com"
    assert role in user.roles


def test_admin_user_unique_email(session):
    session.add(
        User(email="dup@example.com", hashed_password="h")
    )
    session.flush()
    with pytest.raises(Exception):
        session.add(
            User(email="dup@example.com", hashed_password="h")
        )
        session.flush()


def test_admin_user_role_relationship(session):
    role = Role(name="Viewer")
    session.add(role)
    session.flush()

    user = User(
        email="viewer@example.com",
        hashed_password="h",
    )
    user.roles.append(role)
    session.add(user)
    session.flush()

    assert len(user.roles) == 1
    assert user.roles[0].name == "Viewer"
    assert role.users[0].email == "viewer@example.com"


def test_admin_user_defaults(session):
    user = User(email="def@example.com", hashed_password="h")
    session.add(user)
    session.flush()
    assert user.is_superuser is False
    assert user.is_active is True
    assert user.roles == []
    assert user.last_login is None


# ── Permission ──────────────────────────────────────────────────────


def test_admin_permission_create(session):
    role = Role(name="Editor")
    session.add(role)
    session.flush()

    perm = Permission(
        role_id=role.id,
        table_name="products",
        can_view=True,
        can_create=True,
        can_edit=True,
        can_delete=False,
    )
    session.add(perm)
    session.flush()
    assert perm.id is not None


def test_admin_permission_unique_constraint(session):
    role = Role(name="Editor")
    session.add(role)
    session.flush()

    session.add(
        Permission(role_id=role.id, table_name="products", can_view=True)
    )
    session.flush()
    with pytest.raises(Exception):
        session.add(
            Permission(role_id=role.id, table_name="products", can_view=False)
        )
        session.flush()


def test_admin_permission_cascade_delete(session):
    role = Role(name="Temp")
    session.add(role)
    session.flush()
    perm_id = (
        session.add(
            Permission(role_id=role.id, table_name="t", can_view=True)
        )
        or None
    )
    session.flush()

    session.delete(role)
    session.flush()
    assert session.query(Permission).count() == 0


# ── AuditLog ─────────────────────────────────────────────────────────────


def test_audit_log_create(session):
    log = AuditLog(
        user_id=None,
        user_email="admin@example.com",
        action="CREATE",
        model_name="Product",
        table_name="products",
        object_id="1",
        object_repr="Widget",
        full_snapshot={"name": "Widget", "price": 9.99},
    )
    session.add(log)
    session.flush()
    assert log.id is not None


def test_audit_log_nullable_fields(session):
    log = AuditLog(
        action="DELETE",
        model_name="Tag",
        table_name="tags",
        object_id="42",
    )
    session.add(log)
    session.flush()
    assert log.user_id is None
    assert log.user_email is None
    assert log.changes is None
    assert log.full_snapshot is None
    assert log.ip_address is None
    assert log.user_agent is None


# ── Protocol check ───────────────────────────────────────────────────────


def test_admin_user_satisfies_protocol():
    """User instances must satisfy AdminUserProtocol at runtime."""
    user = User(
        email="test@example.com",
        hashed_password="h",
        is_active=True,
        is_superuser=False,
    )
    assert isinstance(user, AdminUserProtocol)


def test_admin_role_does_not_satisfy_protocol():
    role = Role(name="Admin")
    assert not isinstance(role, AdminUserProtocol)


# ── Re-exports from models package ──────────────────────────────────────


def test_models_package_exports():
    from fastapi_admin_kit.models import Base

    assert Base is not None

    from fastapi_admin_kit.auth.models import (
        Permission,
        Role,
        User,
    )

    assert Role is not None
    assert User is not None
    assert Permission is not None


def test_audit_log_exportable():
    from fastapi_admin_kit.audit.models import AuditLog

    assert AuditLog is not None
