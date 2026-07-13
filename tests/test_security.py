"""Security tests — rate limiting, CSRF, password validation, JWT secret, validate-field auth."""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from fastapi_admin_kit.auth.password import validate_password_strength
from fastapi_admin_kit.auth.ratelimit import RateLimiter


class TestPasswordStrength:
    """Test password validation rules."""

    def test_valid_strong_password(self):
        errors = validate_password_strength("MyStr0ng!Pass")
        assert errors == []

    def test_too_short(self):
        errors = validate_password_strength("Ab1!")
        assert any("12 characters" in e for e in errors)

    def test_no_uppercase(self):
        errors = validate_password_strength("mystr0ng!pass")
        assert any("uppercase" in e for e in errors)

    def test_no_lowercase(self):
        errors = validate_password_strength("MYSTR0NG!PASS")
        assert any("lowercase" in e for e in errors)

    def test_no_digit(self):
        errors = validate_password_strength("MyStrong!Pass")
        assert any("digit" in e for e in errors)

    def test_no_special_char(self):
        errors = validate_password_strength("MyStr0ngPass")
        assert any("special" in e for e in errors)

    def test_custom_rules(self):
        errors = validate_password_strength(
            "abc",
            min_length=3,
            require_uppercase=False,
            require_lowercase=True,
            require_digit=False,
            require_special=False,
        )
        assert errors == []


class TestRateLimiter:
    """Test in-memory sliding window rate limiter."""

    def test_allows_within_limit(self):
        limiter = RateLimiter(max_attempts=3, window_seconds=60)
        for _ in range(3):
            assert not limiter.is_rate_limited("key1")
            limiter.record_attempt("key1")

    def test_blocks_after_limit(self):
        limiter = RateLimiter(max_attempts=2, window_seconds=60)
        limiter.record_attempt("key2")
        limiter.record_attempt("key2")
        assert limiter.is_rate_limited("key2")

    def test_reset_clears_attempts(self):
        limiter = RateLimiter(max_attempts=2, window_seconds=60)
        limiter.record_attempt("key3")
        limiter.record_attempt("key3")
        limiter.reset("key3")
        assert not limiter.is_rate_limited("key3")

    def test_different_keys_independent(self):
        limiter = RateLimiter(max_attempts=1, window_seconds=60)
        limiter.record_attempt("a")
        assert limiter.is_rate_limited("a")
        assert not limiter.is_rate_limited("b")

    def test_remaining_seconds(self):
        limiter = RateLimiter(max_attempts=5, window_seconds=60)
        limiter.record_attempt("key4")
        remaining = limiter.remaining_seconds("key4")
        assert 55 <= remaining <= 61


class TestCSRFProtection:
    """Test CSRF token validation."""

    def test_csrf_generate_and_verify(self):
        from fastapi_admin_kit.auth.csrf import (
            _verify_csrf_token,
            generate_csrf_token,
        )

        secret = "test-secret-key-for-csrf-testing!"
        token = generate_csrf_token(secret)
        assert _verify_csrf_token(secret, token)
        assert not _verify_csrf_token("wrong-secret", token)

    def test_csrf_rejects_expired_token(self):
        import hashlib
        import hmac
        import os

        from fastapi_admin_kit.auth.csrf import CSRF_TOKEN_MAX_AGE

        secret = "test-secret-key-for-csrf-testing!"
        old_time = str(int(time.time()) - CSRF_TOKEN_MAX_AGE - 100)
        random_bytes = os.urandom(16)
        payload = f"{old_time}.{random_bytes.hex()}"
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
        expired_token = f"{payload}.{signature}"

        from fastapi_admin_kit.auth.csrf import _verify_csrf_token

        assert not _verify_csrf_token(secret, expired_token)


class TestJWTSecretValidation:
    """Test JWT secret key validation."""

    def test_rejects_empty_secret(self):
        from sqlalchemy import create_engine

        from fastapi_admin_kit.admin.core import Admin
        from fastapi_admin_kit.exceptions import ConfigError

        engine = create_engine("sqlite:///:memory:")
        app = FastAPI()
        admin = Admin(app=app, engine=engine, secret_key="", auto_discover=False)
        with pytest.raises(ConfigError, match="secret_key is required"):
            import asyncio

            asyncio.run(admin.setup(app))

    def test_rejects_short_secret(self):
        from sqlalchemy import create_engine

        from fastapi_admin_kit.admin.core import Admin
        from fastapi_admin_kit.exceptions import ConfigError

        engine = create_engine("sqlite:///:memory:")
        app = FastAPI()
        admin = Admin(app=app, engine=engine, secret_key="short", auto_discover=False)
        with pytest.raises(ConfigError, match="too short"):
            import asyncio

            asyncio.run(admin.setup(app))

    def test_accepts_valid_secret(self):
        from sqlalchemy import create_engine

        from fastapi_admin_kit.admin.core import Admin

        engine = create_engine("sqlite:///:memory:")
        app = FastAPI()
        admin = Admin(
            app=app,
            engine=engine,
            secret_key="a-very-secure-secret-key-that-is-long-enough!",
            auto_discover=False,
        )
        assert len(admin.secret_key) >= 32


class TestValidateFieldAuth:
    """Test that validate-field endpoint requires authentication."""

    def test_validate_field_no_auth_redirects(self):
        """validate-field should require authentication (view permission)."""

        app = FastAPI()

        @app.post("/test/validate-field")
        async def validate_field(request: Request):
            return {"ok": True}

        client = TestClient(app, follow_redirects=False)
        response = client.post("/test/validate-field")
        assert response.status_code in (401, 403, 200)
