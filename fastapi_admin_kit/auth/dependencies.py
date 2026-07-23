"""FastAPI dependencies — session, current user, permission checker."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_admin_kit.auth.csrf import require_csrf_token  # noqa: F401
from fastapi_admin_kit.auth.protocol import AdminUserProtocol
from fastapi_admin_kit.auth.session import SignedCookieSessionBackend

# ---------------------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------------------


def _get_session_backend(request: Request) -> SignedCookieSessionBackend:
    """Resolve the session backend from app state (set during admin setup)."""
    backend: SignedCookieSessionBackend | None = getattr(
        request.app.state, "admin_session_backend", None
    )
    if backend is None:
        raise HTTPException(
            status_code=500,
            detail="Admin session backend not initialised.",
        )
    return backend


async def _get_db_session(request: Request) -> AsyncSession:
    """Yield the async SQLAlchemy session from app.state."""
    from fastapi_admin_kit.db import get_db_session

    session: AsyncSession = get_db_session(request)
    yield session


# ---------------------------------------------------------------------------
# Per-request dependencies
# ---------------------------------------------------------------------------


def get_session(request: Request) -> dict[str, Any] | None:
    """Read and decode the admin session cookie from the current request."""
    session_backend = _get_session_backend(request)
    token = request.cookies.get(session_backend.cookie_name)
    return session_backend.decode(token)


async def get_current_admin_user(
    request: Request,
    session_payload: dict[str, Any] | None = Depends(get_session),
) -> AdminUserProtocol:
    """Resolve the logged-in admin user from the session cookie.

    Raises ``401`` if the session is missing, invalid, the user is
    no longer active, or the password was changed after the session was issued.
    """
    if session_payload is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated. Please log in.",
        )

    user_id = session_payload.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid session payload.")

    # request.state.admin_user is populated as a side effect.
    from fastapi_admin_kit.auth.identity import resolve_user

    user = await resolve_user(request, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found or inactive.")

    # Check session invalidation: reject if password changed after session iat
    password_changed_at = getattr(user, "password_changed_at", None)
    session_iat = session_payload.get("iat")
    if password_changed_at is not None and session_iat is not None:
        from datetime import UTC, datetime

        if isinstance(password_changed_at, datetime):
            if password_changed_at.tzinfo is None:
                password_changed_at = password_changed_at.replace(tzinfo=UTC)
            if isinstance(session_iat, int | float):
                session_time = datetime.fromtimestamp(session_iat, tz=UTC)
                if password_changed_at > session_time:
                    raise HTTPException(
                        status_code=401,
                        detail="Session invalidated. Password was changed. Please log in again.",
                    )

    return user


async def get_permission_checker(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
    session: AsyncSession = Depends(_get_db_session),
) -> Any:
    """Build a ``PermissionChecker`` for the current user.

    The concrete ``PermissionChecker`` class is imported here to avoid
    circular imports.
    """
    from fastapi_admin_kit.auth.permissions import PermissionChecker

    snapshot = getattr(request.state, "admin_user_snapshot", None)
    return PermissionChecker(session=session, user=user, user_snapshot=snapshot)


def require_permission(table_name: str, action: str):  # type: ignore[no-untyped-def]
    """Return a FastAPI dependency that enforces a permission check.

    Usage::

        @router.get("/")
        async def list_view(_=Depends(require_permission("products", "view"))):
            ...
    """

    async def _check(
        checker: Any = Depends(get_permission_checker),
    ) -> None:
        if not await checker.has_permission(table_name, action):
            raise HTTPException(
                status_code=403,
                detail=f"You do not have permission to {action} {table_name}.",
            )

    return _check


async def require_superuser(
    user: AdminUserProtocol = Depends(get_current_admin_user),
) -> AdminUserProtocol:
    """FastAPI dependency that enforces superuser access.

    The single source of the "must be superuser" rule, shared by the roles
    and audit views (previously copy-pasted in each).
    """
    if not getattr(user, "is_superuser", False):
        raise HTTPException(status_code=403, detail="Superuser access required.")
    return user


# ---------------------------------------------------------------------------
# Permission checker resolver (single source — deduplicated from renderers/factory)
# ---------------------------------------------------------------------------


async def resolve_permission_checker(request: Request) -> Any:
    """Resolve a ``PermissionChecker`` for the current request.

    Returns ``None`` if the user is not authenticated or the checker cannot be built.
    This is the canonical implementation — import from here, not from renderers/factory.
    """
    from fastapi_admin_kit.auth.identity import get_current_user_from_cookie
    from fastapi_admin_kit.auth.permissions import PermissionChecker

    user = await get_current_user_from_cookie(request)
    if user is None:
        return None

    from fastapi_admin_kit.db import get_db_session

    async_session = get_db_session(request)
    if async_session is None:
        return None

    snapshot = getattr(request.state, "admin_user_snapshot", None)
    return PermissionChecker(session=async_session, user=user, user_snapshot=snapshot)
