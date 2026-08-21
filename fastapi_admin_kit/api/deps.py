"""API dependencies — JWT authentication with live DB authorization.

The JWT authenticates *identity* (signature + expiry). Authorization is
always checked against the live database via :class:`PermissionChecker`, so
revoked roles/permissions and demoted or deactivated users take effect
immediately instead of persisting until token expiry.
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


async def _resolve_live_user(request: Request, user: dict[str, Any]) -> Any | None:
    """Resolve the JWT subject to the current DB user.

    Returns ``None`` when the account was deleted or deactivated, so stale
    tokens cannot keep working after the account is removed.
    """
    sub = user.get("sub")
    if sub is None:
        return None
    try:
        user_id: int | str = int(sub)
    except (TypeError, ValueError):
        return None

    from fastapi_admin_kit.auth.identity import resolve_user

    try:
        return await resolve_user(request, user_id)
    except Exception:
        return None


def require_api_permission(table_name: str, action: str):
    """Return a dependency that authorizes *action* on *table_name*.

    Usage::

        @router.get("/")
        async def list_view(user=Depends(require_api_permission("products", "view"))):
            ...

    The JWT authenticates identity; authorization is always evaluated
    against the live database so permission revocations, role changes,
    superuser demotion and account deactivation apply immediately.
    """

    async def _check(request: Request) -> dict[str, Any]:
        user = await get_api_current_user(request)

        from fastapi_admin_kit.auth.permissions import PermissionChecker
        from fastapi_admin_kit.db import get_db_session

        resolved = await _resolve_live_user(request, user)
        if resolved is None:
            raise HTTPException(
                status_code=401,
                detail="Account not found or inactive.",
            )

        session = get_db_session(request)
        if session is None:
            raise HTTPException(status_code=503, detail="Database unavailable.")

        checker = PermissionChecker(
            session=session,
            user=resolved,
            user_snapshot=getattr(request.state, "admin_user_snapshot", None),
        )
        if not await checker.has_permission(table_name, action):
            raise HTTPException(
                status_code=403,
                detail=f"You do not have permission to {action} {table_name}.",
            )
        return user

    return _check


def require_api_superuser():
    """Return a dependency that enforces superuser access from live DB state."""

    async def _check(request: Request) -> dict[str, Any]:
        user = await get_api_current_user(request)

        resolved = await _resolve_live_user(request, user)
        if resolved is None:
            raise HTTPException(
                status_code=401,
                detail="Account not found or inactive.",
            )

        if not getattr(resolved, "is_superuser", False):
            raise HTTPException(status_code=403, detail="Superuser access required.")
        return user

    return _check
