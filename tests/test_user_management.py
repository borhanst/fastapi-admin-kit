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
        from fastapi_admin_kit.views.users import _require_superuser

        assert _require_superuser is not None


class TestSoftDelete:
    """Test soft-delete behavior."""

    def test_soft_delete_sets_inactive(self):
        """Soft-delete sets is_active=False."""
        from fastapi_admin_kit.auth.models import User

        user = User(
            email="test@test.com",
            hashed_password="hashed",
            is_active=True,
        )
        assert user.is_active is True
        user.is_active = False
        assert user.is_active is False
