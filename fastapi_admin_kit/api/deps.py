"""API dependencies — JWT-based permission checking with DB fallback.

Primary source of truth is the permission snapshot embedded in the JWT at
login time (fast, no DB hit). When the snapshot does not grant the action,
we fall back to a live :class:`PermissionChecker` query so permissions that
were granted *after* the token was issued take effect immediately instead of
requiring the user to log in again.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from fastapi_admin_kit.api.auth import _get_secret_key, decode_access_token


async def get_api_current_user(request: Request) -> dict[str, Any]:
    """Decode JWT and return user payload (no DB hit).

    Raises 401 if token is missing or invalid.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")

    token = auth_header[7:]
    secret_key = _get_secret_key(request)
    payload = decode_access_token(token, secret_key)
    if payload is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token.")
    return payload


async def _check_live_permission(
    request: Request,
    user: dict[str, Any],
    table_name: str,
    action: str,
) -> bool:
    """Check *action* on *table_name* against the database.

    Resolves the current user from the JWT subject via the configured auth
    backend and runs a fresh :class:`PermissionChecker`. Used as a fallback
    when the JWT-embedded permission snapshot is stale.
    """
    sub = user.get("sub")
    if sub is None:
        return False
    try:
        user_id: int | str = int(sub)
    except (TypeError, ValueError):
        return False

    from fastapi_admin_kit.auth.identity import resolve_user
    from fastapi_admin_kit.auth.permissions import PermissionChecker
    from fastapi_admin_kit.db import get_db_session

    session = get_db_session(request)
    if session is None:
        return False

    resolved = await resolve_user(request, user_id)
    if resolved is None:
        return False

    checker = PermissionChecker(
        session=session,
        user=resolved,
        user_snapshot=getattr(request.state, "admin_user_snapshot", None),
    )
    return await checker.has_permission(table_name, action)


def require_api_permission(table_name: str, action: str):
    """Return a dependency that checks JWT-embedded permissions.

    Usage::

        @router.get("/")
        async def list_view(user=Depends(require_api_permission("products", "view"))):
            ...

    Superusers always pass. When the JWT snapshot does not grant the action,
    a live DB check is performed so newly-granted permissions take effect
    without requiring the user to re-authenticate.
    """

    async def _check(request: Request) -> dict[str, Any]:
        user = await get_api_current_user(request)

        if user.get("is_superuser"):
            return user

        permissions = user.get("permissions", {})
        table_perms = permissions.get(table_name, [])
        if action in table_perms:
            return user

        if await _check_live_permission(request, user, table_name, action):
            return user

        raise HTTPException(
            status_code=403,
            detail=f"You do not have permission to {action} {table_name}.",
        )

    return _check


def require_api_superuser():
    """Return a dependency that enforces superuser access from JWT."""

    async def _check(request: Request) -> dict[str, Any]:
        user = await get_api_current_user(request)

        if not user.get("is_superuser"):
            raise HTTPException(status_code=403, detail="Superuser access required.")
        return user

    return _check
