"""TOTP-based two-factor authentication."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Any


def generate_secret() -> str:
    """Generate a TOTP secret key (base32 encoded)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")


def get_totp_uri(secret: str, email: str, issuer: str = "FastAPI Admin Kit") -> str:
    """Generate an otpauth:// URI for QR code generation."""
    import urllib.parse

    params = urllib.parse.urlencode(
        {
            "secret": secret,
            "issuer": issuer,
            "digits": 6,
            "period": 30,
        }
    )
    return f"otpauth://totp/{urllib.parse.quote(issuer)}:{urllib.parse.quote(email)}?{params}"


def _generate_hotp(secret: str, counter: int) -> str:
    """Generate a HOTP code for a given counter value."""
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8))
    counter_bytes = struct.pack(">Q", counter)
    hmac_digest = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = hmac_digest[-1] & 0x0F
    code_int = struct.unpack(">I", hmac_digest[offset : offset + 4])[0] & 0x7FFFFFFF
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
    """Hash a backup code for storage with bcrypt (S12).

    Backup codes were previously stored as unsalted SHA256 — fast to
    brute-force if the DB leaks. New codes are bcrypt-hashed like
    passwords; :func:`verify_backup_code` still accepts legacy SHA256
    hashes so existing records keep working until regenerated.
    """
    import bcrypt

    return bcrypt.hashpw(code.encode(), bcrypt.gensalt()).decode()


def _is_bcrypt_hash(value: str) -> bool:
    return value.startswith(("$2a$", "$2b$", "$2y$"))


def verify_backup_code(code: str, hashed_codes: list[str]) -> bool:
    """Verify a backup code against a list of hashed codes.

    Accepts both modern bcrypt hashes and legacy unsalted-SHA256 hex
    hashes (migration path). Returns True if the code matches and removes
    it from the list (in-place) so it cannot be reused.
    """
    import bcrypt

    for i, h in enumerate(hashed_codes):
        if _is_bcrypt_hash(h):
            try:
                if bcrypt.checkpw(code.encode(), h.encode()):
                    hashed_codes.pop(i)
                    return True
            except ValueError:
                continue
        else:
            # Legacy unsalted SHA256 (pre-S12 records)
            legacy_hash = hashlib.sha256(code.encode()).hexdigest()
            if hmac.compare_digest(legacy_hash, h):
                hashed_codes.pop(i)
                return True
    return False


# ---------------------------------------------------------------------------
# Data access — the only place that queries TOTP records.
#
# Views must call these helpers instead of building queries themselves.
# Queries are built through the ``QueryBackend`` adapter (``select``/``where``)
# and executed through the backend-agnostic ``SessionBackend`` wrapper, so
# storage stays swappable (SQLAlchemy, memory, …).
# ---------------------------------------------------------------------------


async def get_totp_record(
    session: Any,
    user_id: int | str,
    query_adapter: Any = None,
) -> Any | None:
    """Return the ``UserTOTP`` row for *user_id*, or ``None``.

    *session* may be a raw ORM session or a ``SessionBackend`` — it is
    coerced through :func:`fastapi_admin_kit.backends.as_session_backend`.
    *query_adapter* is the ``QueryBackend`` from ``app.state.admin_query_adapter``;
    when omitted, the default SQLAlchemy adapter is used (CLI / no-app contexts).
    """
    from fastapi_admin_kit.auth.models import UserTOTP
    from fastapi_admin_kit.backends import as_session_backend

    session = as_session_backend(session)
    if query_adapter is None:
        from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyQueryAdapter

        query_adapter = SqlAlchemyQueryAdapter()

    query = query_adapter.select(UserTOTP)
    query = query_adapter.where(query, UserTOTP.user_id == user_id)
    return await session.scalar_one_or_none(query)


async def has_totp_enabled(
    session: Any,
    user_id: int | str,
    query_adapter: Any = None,
) -> bool:
    """Return True when *user_id* has an enabled TOTP record."""
    record = await get_totp_record(session, user_id, query_adapter)
    return record is not None and bool(record.enabled)
