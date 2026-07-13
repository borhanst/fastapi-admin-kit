"""JWT tests — payload structure, refresh tokens, permissions, /me endpoint."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import jwt as pyjwt


class TestJWTPayload:
    """Test JWT payload contains roles, permissions, and metadata."""

    def _make_user(self, **kwargs):
        class FakeRole:
            name = kwargs.pop("role_name", "Admin")

        class FakeUser:
            id = kwargs.pop("id", 1)
            email = kwargs.pop("email", "test@example.com")
            full_name = kwargs.pop("full_name", "Test User")
            is_superuser = kwargs.pop("is_superuser", False)
            roles = [FakeRole()]
            role_id = kwargs.pop("role_id", 1)

        return FakeUser()

    def test_payload_structure(self):
        from fastapi_admin_kit.api.auth import create_access_token

        user = self._make_user()
        secret = "test-secret-key-long-enough-for-security!"
        permissions = {"products": ["view", "create"], "orders": ["view"]}

        token = create_access_token(user, secret, permissions=permissions)
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])

        assert payload["sub"] == "1"
        assert payload["roles"] == ["Admin"]
        assert payload["permissions"] == permissions
        assert payload["is_superuser"] is False
        assert payload["email"] == "test@example.com"
        assert "jti" in payload
        assert "exp" in payload
        assert "iat" in payload

    def test_superuser_in_payload(self):
        from fastapi_admin_kit.api.auth import create_access_token

        user = self._make_user(is_superuser=True)
        secret = "test-secret-key-long-enough-for-security!"

        token = create_access_token(user, secret)
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])

        assert payload["is_superuser"] is True

    def test_access_token_expiry(self):
        from fastapi_admin_kit.api.auth import create_access_token

        user = self._make_user()
        secret = "test-secret-key-long-enough-for-security!"

        token = create_access_token(user, secret, expires_delta=timedelta(seconds=1))
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])

        assert payload["exp"] - payload["iat"] <= 2


class TestRefreshTokenFlow:
    """Test refresh token lifecycle."""

    def test_hash_token(self):
        from fastapi_admin_kit.api.auth import _hash_token

        token = "test-refresh-token"
        hashed = _hash_token(token)
        assert hashed == hashlib.sha256(token.encode()).hexdigest()
        assert len(hashed) == 64


class TestDecodeAccessToken:
    """Test JWT decode and validation."""

    def test_valid_token_decodes(self):
        from fastapi_admin_kit.api.auth import decode_access_token

        secret = "test-secret-key-long-enough-for-security!"
        payload = {
            "sub": "1",
            "roles": ["Admin"],
            "permissions": {},
            "is_superuser": False,
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
            "jti": "test-uuid",
        }
        token = pyjwt.encode(payload, secret, algorithm="HS256")
        result = decode_access_token(token, secret)
        assert result is not None
        assert result["sub"] == "1"

    def test_invalid_token_returns_none(self):
        from fastapi_admin_kit.api.auth import decode_access_token

        secret = "test-secret-key-long-enough-for-security!"
        result = decode_access_token("invalid-token", secret)
        assert result is None

    def test_wrong_secret_returns_none(self):
        from fastapi_admin_kit.api.auth import decode_access_token

        secret = "test-secret-key-long-enough-for-security!"
        payload = {
            "sub": "1",
            "exp": datetime.now(UTC) + timedelta(hours=1),
            "iat": datetime.now(UTC),
            "jti": "test-uuid",
        }
        token = pyjwt.encode(payload, secret, algorithm="HS256")
        result = decode_access_token(token, "wrong-secret")
        assert result is None
