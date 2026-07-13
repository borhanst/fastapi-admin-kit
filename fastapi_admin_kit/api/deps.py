"""API dependencies — JWT-based permission checking without DB hits."""

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


def require_api_permission(table_name: str, action: str):
    """Return a dependency that checks JWT-embedded permissions.

    Usage::

        @router.get("/")
        async def list_view(user=Depends(require_api_permission("products", "view"))):
            ...
    """

    async def _check(
        user: dict[str, Any] = None,
        request: Request = None,
    ) -> dict[str, Any]:
        if user is None:
            user = await get_api_current_user(request)

        if user.get("is_superuser"):
            return user

        permissions = user.get("permissions", {})
        table_perms = permissions.get(table_name, [])
        if action not in table_perms:
            raise HTTPException(
                status_code=403,
                detail=f"You do not have permission to {action} {table_name}.",
            )
        return user

    return _check


def require_api_superuser():
    """Return a dependency that enforces superuser access from JWT."""

    async def _check(
        user: dict[str, Any] = None,
        request: Request = None,
    ) -> dict[str, Any]:
        if user is None:
            user = await get_api_current_user(request)

        if not user.get("is_superuser"):
            raise HTTPException(status_code=403, detail="Superuser access required.")
        return user

    return _check
