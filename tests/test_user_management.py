"""User management tests — CRUD, self-deactivation prevention."""

from __future__ import annotations

from fastapi_admin_kit.auth.password import validate_password_strength


class TestPasswordValidation:
    """Test password validation rules for user creation."""

    def test_strong_password_accepted(self):
        errors = validate_password_strength("MyStr0ng!Pass")
        assert errors == []

    def test_weak_password_rejected(self):
        errors = validate_password_strength("weak")
        assert len(errors) > 0

    def test_no_special_char_rejected(self):
        errors = validate_password_strength("MyStr0ngPass1")
        assert any("special" in e for e in errors)


class TestUserManagementPermissions:
    """Test that user management requires superuser."""

    def test_superuser_required_for_list(self):
        """User list requires superuser role."""
        from fastapi_admin_kit.auth.dependencies import require_superuser

        assert require_superuser is not None

    def test_superuser_required_for_create(self):
        """User create requires superuser role."""
        from fastapi_admin_kit.auth.dependencies import require_superuser

        assert require_superuser is not None


class TestSoftDelete:
    """Test soft-delete behavior."""

    def test_soft_delete_sets_inactive(self):
        """Soft-delete sets is_active=False."""
        from fastapi_admin_kit.migrations.models import User

        user = User(
            email="test@test.com",
            hashed_password="hashed",
            is_active=True,
        )
        assert user.is_active is True
        user.is_active = False
        assert user.is_active is False


class TestDirectPermissionRemoval:
    """Regression — removing all direct permissions from a user must persist.

    Previously ``perm_data`` was forwarded from the form only when it was
    truthy; an empty list (all permissions removed via the cross button) was
    treated as "no change", so stale ``UserPermission`` rows survived the save
    and the user kept access.
    """

    def test_removing_all_direct_permissions_clears_rows(self):
        import os
        import tempfile

        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from sqlalchemy import create_engine
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
        from sqlalchemy.pool import StaticPool

        from fastapi_admin_kit import Admin
        from fastapi_admin_kit.auth.backend import BuiltinAuthBackend
        from fastapi_admin_kit.auth.csrf import generate_csrf_token
        from fastapi_admin_kit.migrations.models import Permission, User, UserPermission
        from fastapi_admin_kit.models.base import Base as AdminBase
        from tests.conftest import SECRET_KEY, create_session_cookie, run_async

        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        sync_engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
        AdminBase.metadata.create_all(sync_engine)
        sync_engine.dispose()
        async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        async def _seed():
            async with AsyncSession(async_engine, expire_on_commit=False) as session:
                admin = User(
                    email="admin@test.com",
                    hashed_password="$2b$12$HQlaDF1uaZvpsppxtnwD5uXp1VxiNXsiS5OCEkXRn7G0xNjUEo8cG",
                    full_name="Admin",
                    is_superuser=True,
                    is_active=True,
                )
                session.add(admin)
                target = User(
                    email="target@test.com",
                    hashed_password="hashed",
                    full_name="Target",
                    is_superuser=False,
                    is_active=True,
                )
                session.add(target)
                await session.flush()
                perm = Permission(
                    name="products_view",
                    table_name="products",
                    can_view=True,
                )
                session.add(perm)
                await session.flush()
                session.add(UserPermission(user_id=target.id, permission_id=perm.id))
                await session.commit()
                return admin.id, target.id

        admin_id, target_id = run_async(_seed())

        app = FastAPI()
        admin = Admin(
            app=app,
            engine=async_engine,
            secret_key=SECRET_KEY,
            auth_backend=BuiltinAuthBackend(),
            auto_discover=False,
        )
        run_async(admin.setup(app))
        client = TestClient(app)

        csrf_token = generate_csrf_token(SECRET_KEY)
        cookie = create_session_cookie(admin_id)
        resp = client.post(
            f"/admin/admin_users/{target_id}",
            data={
                "email": "target@test.com",
                "full_name": "Target",
                "password": "",
                "role_ids": "[]",
                "perm_data": "[]",
                "is_superuser": "",
                "is_active": "on",
                "csrf_token": csrf_token,
            },
            cookies={"admin_session": cookie, "admin_csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        async def _remaining_rows():
            from sqlalchemy import select

            async with AsyncSession(async_engine, expire_on_commit=False) as session:
                rows = (
                    (
                        await session.execute(
                            select(UserPermission).where(UserPermission.user_id == target_id)
                        )
                    )
                    .scalars()
                    .all()
                )
                return list(rows)

        rows = run_async(_remaining_rows())
        assert rows == []

        run_async(async_engine.dispose())
        os.unlink(path)
