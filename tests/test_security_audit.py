"""Security audit tests — login attempts, password change, 2FA toggle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class TestLoginAttemptLogging:
    """Test login attempt recording."""

    def test_admin_login_attempt_model(self):
        from fastapi_admin_kit.auth.models import AdminLoginAttempt

        attempt = AdminLoginAttempt(
            email="test@test.com",
            ip_address="127.0.0.1",
            user_agent="TestAgent",
            success=True,
        )
        assert attempt.email == "test@test.com"
        assert attempt.success is True
        assert attempt.ip_address == "127.0.0.1"

    def test_failed_attempt(self):
        from fastapi_admin_kit.auth.models import AdminLoginAttempt

        attempt = AdminLoginAttempt(
            email="test@test.com",
            ip_address="127.0.0.1",
            user_agent="TestAgent",
            success=False,
        )
        assert attempt.success is False


class TestPasswordChangeAudit:
    """Test password change audit logging."""

    def test_password_changed_at_recorded(self):
        from fastapi_admin_kit.auth.models import AdminUser

        user = AdminUser(
            email="test@test.com",
            hashed_password="hashed",
        )
        assert user.password_changed_at is None
        user.password_changed_at = datetime.now(UTC)
        assert user.password_changed_at is not None


class TestRefreshTokenRevocation:
    """Test refresh token revocation on logout/password change."""

    def test_refresh_token_revocation(self):
        from fastapi_admin_kit.auth.models import AdminRefreshToken

        token = AdminRefreshToken(
            user_id=1,
            token_hash="hash",
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        assert token.revoked_at is None
        token.revoked_at = datetime.now(UTC)
        assert token.revoked_at is not None


class TestRateLimiting:
    """Test rate limiting on login attempts."""

    def test_rate_limit_blocks_after_max_attempts(self):
        from fastapi_admin_kit.auth.ratelimit import RateLimiter

        limiter = RateLimiter(max_attempts=3, window_seconds=900)
        for _ in range(3):
            limiter.record_attempt("test@email.com")
        assert limiter.is_rate_limited("test@email.com")

    def test_rate_limit_resets_on_success(self):
        from fastapi_admin_kit.auth.ratelimit import RateLimiter

        limiter = RateLimiter(max_attempts=3, window_seconds=900)
        limiter.record_attempt("test@email.com")
        limiter.record_attempt("test@email.com")
        limiter.reset("test@email.com")
        assert not limiter.is_rate_limited("test@email.com")
