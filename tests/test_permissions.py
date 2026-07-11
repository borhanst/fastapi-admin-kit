"""Tests for RBAC Permission Checker."""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from fastapi_admin_kit.auth.models import (
    Permission,
    Role,
    User,
)
from fastapi_admin_kit.auth.permissions import PermissionChecker
from fastapi_admin_kit.models import Base


# ---------------------------------------------------------------------------
# Async fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest_asyncio.fixture
async def session(engine):
    async with AsyncSession(engine, expire_on_commit=False) as s:
        yield s


@pytest_asyncio.fixture
async def editor_role(session):
    role = Role(name="Editor")
    session.add(role)
    await session.flush()
    return role


@pytest_asyncio.fixture
async def viewer_role(session):
    role = Role(name="Viewer")
    session.add(role)
    await session.flush()
    return role


@pytest_asyncio.fixture
async def superuser(session, editor_role):
    user = User(
        email="super@example.com",
        hashed_password="hash",
        full_name="Super Admin",
        is_superuser=True,
        is_active=True,
    )
    user.roles.append(editor_role)
    session.add(user)
    await session.flush()
    await session.refresh(user, ["roles"])
    return user


@pytest_asyncio.fixture
async def normal_user(session, editor_role):
    user = User(
        email="editor@example.com",
        hashed_password="hash",
        full_name="Editor",
        is_superuser=False,
        is_active=True,
    )
    user.roles.append(editor_role)
    session.add(user)
    await session.flush()
    await session.refresh(user, ["roles"])
    return user


@pytest_asyncio.fixture
async def multi_role_user(session, editor_role, viewer_role):
    user = User(
        email="multi@example.com",
        hashed_password="hash",
        full_name="Multi Role",
        is_superuser=False,
        is_active=True,
    )
    user.roles.append(editor_role)
    user.roles.append(viewer_role)
    session.add(user)
    await session.flush()
    await session.refresh(user, ["roles"])
    return user


@pytest_asyncio.fixture
async def no_role_user(session):
    user = User(
        email="norole@example.com",
        hashed_password="hash",
        full_name="No Role",
        is_superuser=False,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user, ["roles"])
    return user


# ---------------------------------------------------------------------------
# Superuser bypass
# ---------------------------------------------------------------------------


class TestHasPermissionSuperuser:
    @pytest.mark.asyncio
    async def test_superuser_always_allowed(self, session, superuser):
        checker = PermissionChecker(session=session, user=superuser)
        for action in ("view", "create", "edit", "delete"):
            assert await checker.has_permission("any_table", action) is True

    @pytest.mark.asyncio
    async def test_superuser_allowed_even_without_permissions(self, session, superuser):
        checker = PermissionChecker(session=session, user=superuser)
        assert await checker.has_permission("nonexistent_table", "view") is True


# ---------------------------------------------------------------------------
# No role
# ---------------------------------------------------------------------------


class TestHasPermissionNoRole:
    @pytest.mark.asyncio
    async def test_no_role_always_denied(self, session, no_role_user):
        checker = PermissionChecker(session=session, user=no_role_user)
        for action in ("view", "create", "edit", "delete"):
            assert await checker.has_permission("any_table", action) is False


# ---------------------------------------------------------------------------
# Normal user with permissions
# ---------------------------------------------------------------------------


class TestHasPermissionNormalUser:
    @pytest.mark.asyncio
    async def test_with_permission_granted(self, session, editor_role, normal_user):
        perm = Permission(
            table_name="products",
            can_view=True,
            can_create=True,
            can_edit=False,
            can_delete=False,
        )
        session.add(perm)
        await session.flush()
        # Refresh role to load M2M relationship
        await session.refresh(editor_role, ["permissions"])
        # Link permission to role via M2M
        editor_role.permissions.append(perm)
        await session.flush()

        checker = PermissionChecker(session=session, user=normal_user)
        assert await checker.has_permission("products", "view") is True
        assert await checker.has_permission("products", "create") is True
        assert await checker.has_permission("products", "edit") is False
        assert await checker.has_permission("products", "delete") is False

    @pytest.mark.asyncio
    async def test_without_permission_row_denied(self, session, normal_user):
        checker = PermissionChecker(session=session, user=normal_user)
        assert await checker.has_permission("products", "view") is False

    @pytest.mark.asyncio
    async def test_wrong_table_denied(self, session, editor_role, normal_user):
        perm = Permission(
            table_name="products",
            can_view=True,
        )
        session.add(perm)
        await session.flush()
        # Refresh role to load M2M relationship
        await session.refresh(editor_role, ["permissions"])
        # Link permission to role via M2M
        editor_role.permissions.append(perm)
        await session.flush()

        checker = PermissionChecker(session=session, user=normal_user)
        assert await checker.has_permission("orders", "view") is False


# ---------------------------------------------------------------------------
# Multi-role user — permissions merged with OR
# ---------------------------------------------------------------------------


class TestHasPermissionMultiRole:
    @pytest.mark.asyncio
    async def test_permissions_merged_from_all_roles(
        self, session, editor_role, viewer_role, multi_role_user
    ):
        # Create permissions for different tables (M2M means one permission per table)
        editor_perm = Permission(
            table_name="products",
            can_view=True,
            can_create=True,
            can_edit=False,
            can_delete=False,
        )
        viewer_perm = Permission(
            table_name="orders",
            can_view=True,
            can_create=False,
            can_edit=True,
            can_delete=False,
        )
        session.add_all([editor_perm, viewer_perm])
        await session.flush()
        # Refresh roles to load M2M relationships
        await session.refresh(editor_role, ["permissions"])
        await session.refresh(viewer_role, ["permissions"])
        # Link permissions to roles via M2M
        editor_role.permissions.append(editor_perm)
        viewer_role.permissions.append(viewer_perm)
        await session.flush()

        checker = PermissionChecker(session=session, user=multi_role_user)
        assert await checker.has_permission("products", "view") is True
        assert await checker.has_permission("products", "create") is True
        assert await checker.has_permission("orders", "view") is True
        assert await checker.has_permission("orders", "edit") is True
        assert await checker.has_permission("orders", "delete") is False

    @pytest.mark.asyncio
    async def test_different_tables_per_role(
        self, session, editor_role, viewer_role, multi_role_user
    ):
        editor_perm = Permission(
            table_name="products",
            can_view=True,
        )
        viewer_perm = Permission(
            table_name="orders",
            can_view=True,
        )
        session.add_all([editor_perm, viewer_perm])
        await session.flush()
        # Refresh roles to load M2M relationships
        await session.refresh(editor_role, ["permissions"])
        await session.refresh(viewer_role, ["permissions"])
        # Link permissions to roles via M2M
        editor_role.permissions.append(editor_perm)
        viewer_role.permissions.append(viewer_perm)
        await session.flush()

        checker = PermissionChecker(session=session, user=multi_role_user)
        assert await checker.has_permission("products", "view") is True
        assert await checker.has_permission("orders", "view") is True
        assert await checker.has_permission("orders", "edit") is False


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------


class TestHasPermissionCaching:
    @pytest.mark.asyncio
    async def test_result_is_cached(self, session, editor_role, normal_user):
        perm = Permission(
            table_name="products",
            can_view=True,
        )
        session.add(perm)
        await session.flush()
        # Refresh role to load M2M relationship
        await session.refresh(editor_role, ["permissions"])
        # Link permission to role via M2M
        editor_role.permissions.append(perm)
        await session.flush()

        checker = PermissionChecker(session=session, user=normal_user)
        first = await checker.has_permission("products", "view")
        second = await checker.has_permission("products", "view")
        assert first is True
        assert second is True
        assert ("products", "view") in checker._cache

    @pytest.mark.asyncio
    async def test_different_actions_not_shared(self, session, editor_role, normal_user):
        perm = Permission(
            table_name="products",
            can_view=True,
            can_delete=False,
        )
        session.add(perm)
        await session.flush()
        # Refresh role to load M2M relationship
        await session.refresh(editor_role, ["permissions"])
        # Link permission to role via M2M
        editor_role.permissions.append(perm)
        await session.flush()

        checker = PermissionChecker(session=session, user=normal_user)
        assert await checker.has_permission("products", "view") is True
        assert await checker.has_permission("products", "delete") is False


# ---------------------------------------------------------------------------
# permission_set (sync convenience)
# ---------------------------------------------------------------------------


class TestPermissionSet:
    @pytest.mark.asyncio
    async def test_no_permission_returns_all_false(self, session, normal_user):
        checker = PermissionChecker(session=session, user=normal_user)
        ps = checker.permission_set("products")
        assert ps.can_view is False
        assert ps.can_create is False
        assert ps.can_edit is False
        assert ps.can_delete is False

    @pytest.mark.asyncio
    async def test_superuser_returns_all_true(self, session, superuser):
        checker = PermissionChecker(session=session, user=superuser)
        ps = checker.permission_set("products")
        assert ps.can_view is True
        assert ps.can_create is True
        assert ps.can_edit is True
        assert ps.can_delete is True
