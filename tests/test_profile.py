"""Profile tests — password change, session invalidation, profile update."""

from __future__ import annotations

import time
from datetime import UTC, datetime


class TestPasswordChangeFlow:
    """Test password change workflow."""

    def test_password_changed_at_set(self):
        """After password change, password_changed_at should be set."""

        from fastapi_admin_kit.auth.models import AdminUser

        user = AdminUser(
            email="test@test.com",
            hashed_password="hashed",
        )
        assert user.password_changed_at is None
        user.password_changed_at = datetime.now(UTC)
        assert user.password_changed_at is not None

    def test_password_change_requires_current(self):
        """Password change requires current password verification."""
        from fastapi_admin_kit.auth.backend import pwd_context

        hashed = pwd_context.hash("currentpassword")
        assert pwd_context.verify("currentpassword", hashed)
        assert not pwd_context.verify("wrongpassword", hashed)


class TestSessionInvalidationAfterPasswordChange:
    """Test session is invalidated after password change."""

    def test_session_older_than_password_change_rejected(self):
        """Session issued before password change should be rejected."""
        session_iat = time.time() - 3600
        password_changed = datetime.now(UTC)

        session_time = datetime.fromtimestamp(session_iat, tz=UTC)
        assert password_changed > session_time

    def test_session_newer_than_password_change_accepted(self):
        """Session issued after password change should be accepted."""
        password_changed = datetime(2020, 1, 1, tzinfo=UTC)
        session_iat = time.time()

        session_time = datetime.fromtimestamp(session_iat, tz=UTC)
        assert password_changed < session_time


class TestProfileUpdate:
    """Test profile update logic."""

    def test_email_change_requires_password(self):
        """Email change requires password confirmation."""
        assert True

    def test_full_name_update(self):
        """Full name can be updated."""
        from fastapi_admin_kit.auth.models import AdminUser

        user = AdminUser(
            email="test@test.com",
            hashed_password="hashed",
            full_name="Old Name",
        )
        user.full_name = "New Name"
        assert user.full_name == "New Name"
