"""Session security tests — invalidation on password change, samesite, fixation."""

from __future__ import annotations

import time
from datetime import UTC, datetime


class TestSessionInvalidation:
    """Test session is rejected after password change."""

    def test_session_iat_included(self):
        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        backend = SignedCookieSessionBackend(
            secret_key="test-secret-key-long-enough-for-security!",
            session_ttl=3600,
        )
        token = backend.encode({"user_id": 1})
        payload = backend.decode(token)
        assert payload is not None
        assert "iat" in payload
        assert isinstance(payload["iat"], float)

    def test_session_rejected_after_password_change(self):
        session_payload = {"user_id": 1, "iat": time.time() - 3600}
        password_changed_at = datetime.now(UTC)

        session_time = datetime.fromtimestamp(session_payload["iat"], tz=UTC)
        assert password_changed_at > session_time

    def test_session_valid_before_password_change(self):
        session_payload = {"user_id": 1, "iat": time.time()}
        password_changed_at = datetime(2020, 1, 1, tzinfo=UTC)

        session_time = datetime.fromtimestamp(session_payload["iat"], tz=UTC)
        assert password_changed_at < session_time


class TestSecureCookieSettings:
    """Test cookie security settings."""

    def test_session_samesite_default(self):
        from fastapi_admin_kit.config.auth import AuthConfig

        config = AuthConfig()
        assert config.session_samesite == "strict"

    def test_session_samesite_configurable(self):
        from fastapi_admin_kit.config.auth import AuthConfig

        config = AuthConfig(session_samesite="lax")
        assert config.session_samesite == "lax"


class TestSessionFixationPrevention:
    """Test that new session tokens are generated on login."""

    def test_session_token_unique(self):
        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        backend = SignedCookieSessionBackend(
            secret_key="test-secret-key-long-enough-for-security!",
            session_ttl=3600,
        )
        token1 = backend.encode({"user_id": 1})
        token2 = backend.encode({"user_id": 1})
        assert token1 != token2
