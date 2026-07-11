"""Token-based authentication for the Admin JSON API."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, Request

from fastapi_admin_kit.api.schemas import (
    RefreshRequest,
    RefreshResponse,
    TokenRequest,
    TokenResponse,
)
from fastapi_admin_kit.auth.ratelimit import RateLimiter, check_rate_limit
from fastapi_admin_kit.db import get_db_session

router = APIRouter(prefix="/auth", tags=["api-auth"])

_api_rate_limiter = RateLimiter(max_attempts=10, window_seconds=900)


def _get_secret_key(request: Request) -> str:
    """Get the JWT signing key from the unified signing-key source.

    Reads ``app.state.admin_secret_key`` (the same key the signed-cookie
    sessions and CSRF use). Fails closed with 500 if unset or too short —
    JWT signing must never silently fall back to a known constant.
    """
    secret_key = getattr(request.app.state, "admin_secret_key", "")
    if not secret_key:
        raise HTTPException(
            status_code=500,
            detail="JWT signing key not configured — admin secret_key not set.",
        )
    if len(secret_key) < 32:
        raise HTTPException(
            status_code=500,
            detail="JWT signing key too short — must be at least 32 characters.",
        )
    return secret_key


def _get_token_ttl(request: Request) -> int:
    """Get access token TTL in seconds from admin config."""
    config = getattr(request.app.state, "admin_config", {})
    return config.get("session_ttl", 1800)


def _get_refresh_ttl() -> int:
    """Refresh token TTL: 7 days."""
    return 7 * 24 * 3600


async def _build_user_permissions(
    user: Any, db_session: Any
) -> dict[str, list[str]]:
    """Build permissions dict from user's roles and direct overrides."""
    permissions: dict[str, list[str]] = {}
    if getattr(user, "is_superuser", False):
        return permissions

    from sqlalchemy import select

    from fastapi_admin_kit.auth.models import Permission, UserPermission, admin_role_permissions

    # Collect permissions from all assigned roles (OR merge)
    role_ids = getattr(user, "role_ids", [])
    if role_ids:
        result = await db_session.execute(
            select(Permission)
            .join(
                admin_role_permissions,
                Permission.id == admin_role_permissions.c.permission_id,
            )
            .where(admin_role_permissions.c.role_id.in_(role_ids))
        )
        for perm in result.scalars():
            actions = []
            if perm.can_view:
                actions.append("view")
            if perm.can_create:
                actions.append("create")
            if perm.can_edit:
                actions.append("edit")
            if perm.can_delete:
                actions.append("delete")
            if actions:
                permissions[perm.table_name] = actions

    # Merge direct user permission overrides (OR on top)
    user_id = getattr(user, "id", None)
    if user_id is not None:
        result = await db_session.execute(
            select(UserPermission).where(
                UserPermission.user_id == user_id
            )
        )
        for perm in result.scalars():
            actions = []
            if perm.can_view:
                actions.append("view")
            if perm.can_create:
                actions.append("create")
            if perm.can_edit:
                actions.append("edit")
            if perm.can_delete:
                actions.append("delete")
            if actions:
                existing = permissions.get(perm.table_name, [])
                permissions[perm.table_name] = list(
                    set(existing) | set(actions)
                )

    return permissions


def create_access_token(
    user: Any,
    secret_key: str,
    permissions: dict[str, list[str]] | None = None,
    expires_delta: timedelta | None = None,
) -> str:
    """Create a JWT access token with embedded roles and permissions."""
    now = datetime.now(UTC)
    expire = now + (expires_delta or timedelta(minutes=30))
    jti = str(uuid.uuid4())

    role_names = []
    roles = getattr(user, "roles", [])
    for r in roles:
        role_name = getattr(r, "name", None)
        if role_name:
            role_names.append(role_name)

    payload = {
        "sub": str(user.id),
        "roles": role_names,
        "permissions": permissions or {},
        "is_superuser": getattr(user, "is_superuser", False),
        "email": getattr(user, "email", ""),
        "full_name": getattr(user, "full_name", ""),
        "exp": expire,
        "iat": now,
        "jti": jti,
    }
    return jwt.encode(payload, secret_key, algorithm="HS256")


def decode_access_token(token: str, secret_key: str) -> dict[str, Any] | None:
    """Decode and validate a JWT access token. Returns payload or None."""
    try:
        return jwt.decode(token, secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _hash_token(token: str) -> str:
    """SHA256 hash of a token for storage."""
    return hashlib.sha256(token.encode()).hexdigest()


@router.post("/token", response_model=TokenResponse)
async def obtain_token(
    request: Request,
    body: TokenRequest,
) -> TokenResponse:
    """POST /api/auth/token — obtain JWT access + refresh tokens."""
    check_rate_limit(_api_rate_limiter, body.email)

    auth_backend = getattr(request.app.state, "admin_auth_backend", None)
    if auth_backend is None:
        raise HTTPException(
            status_code=500, detail="Auth backend not configured."
        )

    db_session = get_db_session(request)
    if db_session is None:
        raise HTTPException(
            status_code=500, detail="Database session not available."
        )

    user = await auth_backend.authenticate(
        body.email, body.password, db_session
    )
    if user is None:
        _api_rate_limiter.record_attempt(body.email)
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    _api_rate_limiter.reset(body.email)

    secret_key = _get_secret_key(request)
    ttl = _get_token_ttl(request)
    permissions = await _build_user_permissions(user, db_session)
    access_token = create_access_token(
        user, secret_key, permissions, expires_delta=timedelta(seconds=ttl)
    )

    # Create refresh token
    from fastapi_admin_kit.auth.models import RefreshToken

    refresh_jti = str(uuid.uuid4())
    refresh_hash = _hash_token(refresh_jti)
    refresh_expires = datetime.now(UTC) + timedelta(seconds=_get_refresh_ttl())

    refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=refresh_hash,
        expires_at=refresh_expires,
    )
    db_session.add(refresh_record)
    await db_session.flush()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_jti,
        expires_in=ttl,
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_token(
    request: Request,
    body: RefreshRequest,
) -> RefreshResponse:
    """POST /api/auth/refresh — exchange refresh token for new access token."""
    db_session = get_db_session(request)
    if db_session is None:
        raise HTTPException(
            status_code=500, detail="Database session not available."
        )

    from sqlalchemy import select

    from fastapi_admin_kit.auth.models import RefreshToken, User

    refresh_hash = _hash_token(body.refresh_token)
    result = await db_session.execute(
        select(RefreshToken).where(
            RefreshToken.token_hash == refresh_hash,
            RefreshToken.revoked_at.is_(None),
        )
    )
    refresh_record = result.scalar_one_or_none()

    if refresh_record is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token.")

    if refresh_record.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Refresh token expired.")

    # Load user
    user_result = await db_session.execute(
        select(User).where(
            User.id == refresh_record.user_id,
            User.is_active,
        )
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=401, detail="User not found or inactive."
        )

    # Rotate refresh token
    refresh_record.revoked_at = datetime.now(UTC)

    secret_key = _get_secret_key(request)
    ttl = _get_token_ttl(request)
    permissions = await _build_user_permissions(user, db_session)
    new_access_token = create_access_token(
        user, secret_key, permissions, expires_delta=timedelta(seconds=ttl)
    )

    new_refresh_jti = str(uuid.uuid4())
    new_refresh_hash = _hash_token(new_refresh_jti)
    new_refresh_record = RefreshToken(
        user_id=user.id,
        token_hash=new_refresh_hash,
        expires_at=datetime.now(UTC) + timedelta(seconds=_get_refresh_ttl()),
    )
    db_session.add(new_refresh_record)
    await db_session.flush()

    return RefreshResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_jti,
        expires_in=ttl,
    )


@router.post("/logout")
async def api_logout(
    request: Request,
    body: RefreshRequest | None = None,
) -> dict[str, str]:
    """POST /api/auth/logout — revoke refresh token."""
    if body and body.refresh_token:
        db_session = get_db_session(request)
        if db_session:
            from sqlalchemy import select

            from fastapi_admin_kit.auth.models import RefreshToken

            refresh_hash = _hash_token(body.refresh_token)
            result = await db_session.execute(
                select(RefreshToken).where(
                    RefreshToken.token_hash == refresh_hash,
                    RefreshToken.revoked_at.is_(None),
                )
            )
            refresh_record = result.scalar_one_or_none()
            if refresh_record:
                refresh_record.revoked_at = datetime.now(UTC)
                await db_session.flush()

    return {"detail": "Logged out successfully."}


@router.get("/me")
async def get_current_user_info(
    request: Request,
) -> dict[str, Any]:
    """GET /api/auth/me — return current user info from JWT (no DB hit)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header."
        )

    token = auth_header[7:]
    secret_key = _get_secret_key(request)
    payload = decode_access_token(token, secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")

    return {
        "user_id": payload.get("sub"),
        "email": payload.get("email"),
        "full_name": payload.get("full_name"),
        "roles": payload.get("roles", []),
        "is_superuser": payload.get("is_superuser", False),
    }
