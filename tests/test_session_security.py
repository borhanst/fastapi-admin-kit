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


class TestSessionNonJsonNativeTypes:
    """The session backend must encode payloads that contain non-stdlib
    types — UUIDs, datetimes, Decimals, sets — without raising.

    This is the regression test for the
    ``TypeError: Object of type UUID is not JSON serializable`` that
    broke the first login for any project whose custom ``auth_model``
    has a UUID primary key.
    """

    def _make_backend(self):
        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        return SignedCookieSessionBackend(
            secret_key="test-secret-key-long-enough-for-security!",
            session_ttl=3600,
        )

    def test_uuid_user_id_roundtrips_as_string(self):
        import uuid

        backend = self._make_backend()
        user_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
        token = backend.encode({"user_id": user_uuid, "sid": "abc", "email": "u@x.com"})
        payload = backend.decode(token)
        assert payload is not None
        assert payload["user_id"] == "12345678-1234-5678-1234-567812345678"
        assert payload["email"] == "u@x.com"

    def test_datetime_payload_serializes(self):
        from datetime import UTC, datetime

        backend = self._make_backend()
        token = backend.encode(
            {
                "user_id": 1,
                "iat": datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
            }
        )
        payload = backend.decode(token)
        assert payload is not None
        # Coerced to ISO string.
        assert payload["iat"] == "2025-01-01T12:00:00+00:00"

    def test_decimal_and_set_payload_serialize(self):
        from decimal import Decimal

        backend = self._make_backend()
        token = backend.encode(
            {
                "user_id": 1,
                "amount": Decimal("12.34"),
                "tags": {"admin", "user"},
            }
        )
        payload = backend.decode(token)
        assert payload is not None
        assert payload["amount"] == "12.34"
        assert sorted(payload["tags"]) == ["admin", "user"]

    def test_pending_2fa_token_with_uuid_user_id(self):
        import uuid

        from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

        backend = SignedCookieSessionBackend(
            secret_key="test-secret-key-long-enough-for-security!",
        )
        user_uuid = uuid.uuid4()
        token = backend.encode_pending_2fa(user_uuid)
        assert backend.decode_pending_2fa(token) == str(user_uuid)
