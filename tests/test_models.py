"""Tests for Phase 6 — Database Models (Admin Tables)."""

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from fastapi_admin_kit.audit.models import AuditLog
from fastapi_admin_kit.auth.models import (
    AdminPermission,
    AdminRole,
    AdminUser,
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


# ── AdminRole ────────────────────────────────────────────────────────────


def test_admin_role_create(session):
    role = AdminRole(name="Admin", description="Full access")
    session.add(role)
    session.flush()
    assert role.id is not None
    assert role.name == "Admin"


def test_admin_role_unique_name(session):
    session.add(AdminRole(name="Admin"))
    session.flush()
    with pytest.raises(Exception):
        session.add(AdminRole(name="Admin"))
        session.flush()


# ── AdminUser ────────────────────────────────────────────────────────────


def test_admin_user_create(session):
    role = AdminRole(name="Editor")
    session.add(role)
    session.flush()

    user = AdminUser(
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
        AdminUser(email="dup@example.com", hashed_password="h")
    )
    session.flush()
    with pytest.raises(Exception):
        session.add(
            AdminUser(email="dup@example.com", hashed_password="h")
        )
        session.flush()


def test_admin_user_role_relationship(session):
    role = AdminRole(name="Viewer")
    session.add(role)
    session.flush()

    user = AdminUser(
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
    user = AdminUser(email="def@example.com", hashed_password="h")
    session.add(user)
    session.flush()
    assert user.is_superuser is False
    assert user.is_active is True
    assert user.roles == []
    assert user.last_login is None


# ── AdminPermission ──────────────────────────────────────────────────────


def test_admin_permission_create(session):
    role = AdminRole(name="Editor")
    session.add(role)
    session.flush()

    perm = AdminPermission(
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
    role = AdminRole(name="Editor")
    session.add(role)
    session.flush()

    session.add(
        AdminPermission(role_id=role.id, table_name="products", can_view=True)
    )
    session.flush()
    with pytest.raises(Exception):
        session.add(
            AdminPermission(role_id=role.id, table_name="products", can_view=False)
        )
        session.flush()


def test_admin_permission_cascade_delete(session):
    role = AdminRole(name="Temp")
    session.add(role)
    session.flush()
    perm_id = (
        session.add(
            AdminPermission(role_id=role.id, table_name="t", can_view=True)
        )
        or None
    )
    session.flush()

    session.delete(role)
    session.flush()
    assert session.query(AdminPermission).count() == 0


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
    """AdminUser instances must satisfy AdminUserProtocol at runtime."""
    user = AdminUser(
        email="test@example.com",
        hashed_password="h",
        is_active=True,
        is_superuser=False,
    )
    assert isinstance(user, AdminUserProtocol)


def test_admin_role_does_not_satisfy_protocol():
    role = AdminRole(name="Admin")
    assert not isinstance(role, AdminUserProtocol)


# ── Re-exports from models package ──────────────────────────────────────


def test_models_package_exports():
    from fastapi_admin_kit.models import Base

    assert Base is not None

    from fastapi_admin_kit.auth.models import (
        AdminPermission,
        AdminRole,
        AdminUser,
    )

    assert AdminRole is not None
    assert AdminUser is not None
    assert AdminPermission is not None


def test_audit_log_exportable():
    from fastapi_admin_kit.audit.models import AuditLog

    assert AuditLog is not None
