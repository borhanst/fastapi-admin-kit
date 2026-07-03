"""TOTP-based two-factor authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time


def generate_secret() -> str:
    """Generate a TOTP secret key (base32 encoded)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")


def get_totp_uri(secret: str, email: str, issuer: str = "FastAPI Admin Kit") -> str:
    """Generate an otpauth:// URI for QR code generation."""
    import urllib.parse
    params = urllib.parse.urlencode({
        "secret": secret,
        "issuer": issuer,
        "digits": 6,
        "period": 30,
    })
    return f"otpauth://totp/{urllib.parse.quote(issuer)}:{urllib.parse.quote(email)}?{params}"


def _generate_hotp(secret: str, counter: int) -> str:
    """Generate a HOTP code for a given counter value."""
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    counter_bytes = struct.pack(">Q", counter)
    hmac_digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = hmac_digest[-1] & 0x0F
    code_int = struct.unpack(">I", hmac_digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % 1000000).zfill(6)


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    """Verify a TOTP code with a ±window tolerance.

    Args:
        secret: Base32-encoded TOTP secret
        code: 6-digit code to verify
        window: Number of time steps to check in each direction (default 1 = ±30s)
    """
    if not code or len(code) != 6 or not code.isdigit():
        return False

    current_counter = int(time.time()) // 30
    for offset in range(-window, window + 1):
        expected = _generate_hotp(secret, current_counter + offset)
        if hmac.compare_digest(code, expected):
            return True
    return False


def generate_backup_codes(count: int = 10) -> list[str]:
    """Generate one-time-use backup codes (8 alphanumeric chars each)."""
    codes = []
    for _ in range(count):
        code = secrets.token_urlsafe(6)[:8]
        codes.append(code.upper())
    return codes


def hash_backup_code(code: str) -> str:
    """Hash a backup code for storage."""
    return hashlib.sha256(code.encode()).hexdigest()


def verify_backup_code(code: str, hashed_codes: list[str]) -> bool:
    """Verify a backup code against a list of hashed codes.

    Returns True if the code matches and removes it from the list (in-place).
    """
    code_hash = hash_backup_code(code)
    for i, h in enumerate(hashed_codes):
        if hmac.compare_digest(code_hash, h):
            hashed_codes.pop(i)
            return True
    return False
