"""2FA tests — TOTP setup, verification, backup codes."""

from __future__ import annotations


class TestTOTPSecret:
    """Test TOTP secret generation."""

    def test_generate_secret(self):
        from fastapi_admin_kit.auth.totp import generate_secret

        secret = generate_secret()
        assert len(secret) >= 16
        assert secret == secret.upper()

    def test_secret_is_base32(self):
        import base64

        from fastapi_admin_kit.auth.totp import generate_secret

        secret = generate_secret()
        padded = secret + "=" * ((8 - len(secret) % 8) % 8)
        decoded = base64.b32decode(padded)
        assert len(decoded) == 20


class TestTOTPVerification:
    """Test TOTP code verification."""

    def test_valid_code_accepted(self):
        import time

        from fastapi_admin_kit.auth.totp import _generate_hotp, generate_secret

        secret = generate_secret()
        current_counter = int(time.time()) // 30
        code = _generate_hotp(secret, current_counter)

        from fastapi_admin_kit.auth.totp import verify_totp

        assert verify_totp(secret, code)

    def test_invalid_code_rejected(self):
        from fastapi_admin_kit.auth.totp import generate_secret, verify_totp

        secret = generate_secret()
        assert not verify_totp(secret, "000000")

    def test_wrong_length_rejected(self):
        from fastapi_admin_kit.auth.totp import generate_secret, verify_totp

        secret = generate_secret()
        assert not verify_totp(secret, "123")
        assert not verify_totp(secret, "1234567")


class TestBackupCodes:
    """Test backup code generation and verification."""

    def test_generate_backup_codes(self):
        from fastapi_admin_kit.auth.totp import generate_backup_codes

        codes = generate_backup_codes(10)
        assert len(codes) == 10
        assert all(len(c) == 8 for c in codes)
        assert len(set(codes)) == 10

    def test_hash_backup_code(self):
        from fastapi_admin_kit.auth.totp import hash_backup_code

        code = "TESTCODE"
        hashed = hash_backup_code(code)
        assert len(hashed) == 64

    def test_verify_backup_code(self):
        from fastapi_admin_kit.auth.totp import (
            generate_backup_codes,
            hash_backup_code,
            verify_backup_code,
        )

        codes = generate_backup_codes(5)
        hashed = [hash_backup_code(c) for c in codes]

        assert verify_backup_code(codes[0], hashed)
        assert len(hashed) == 4

    def test_reject_reused_backup_code(self):
        from fastapi_admin_kit.auth.totp import (
            generate_backup_codes,
            hash_backup_code,
            verify_backup_code,
        )

        codes = generate_backup_codes(5)
        hashed = [hash_backup_code(c) for c in codes]

        assert verify_backup_code(codes[0], hashed)
        assert not verify_backup_code(codes[0], hashed)


class TestTOTPURI:
    """Test otpauth URI generation."""

    def test_uri_format(self):
        from fastapi_admin_kit.auth.totp import generate_secret, get_totp_uri

        secret = generate_secret()
        uri = get_totp_uri(secret, "user@example.com")
        assert uri.startswith("otpauth://totp/")
        assert "secret=" in uri
        assert "issuer=" in uri
