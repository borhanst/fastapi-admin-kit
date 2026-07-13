"""Request-authentication — the single place that resolves "the current user".

The admin framework historically had *three* parallel implementations of
"decode a credential, then SELECT the active user it belongs to":

1. :func:`fastapi_admin_kit.auth.dependencies.get_current_admin_user` (cookie)
2. :func:`fastapi_admin_kit.views.factory._resolve_permission_checker` (cookie,
   with a process-global cache on ``app.state`` that leaked identity across
   requests)
3. :func:`fastapi_admin_kit.api.crud._get_current_user` (bearer JWT, hardcoded to
   the built-in ``User`` model and so bypassing the ``AuthBackend`` seam)

This module is the deep seam they all delegate to. The two credential
transports (signed cookie, bearer JWT) become thin internal adapters; the
"load the active user and remember it for this request" rule lives in
:func:`resolve_user` exactly once.

The only request-scoped side effect is writing ``request.state.admin_user``
once per request, which the audit middleware, sidebar, and templates read.
Nothing is ever cached on ``app.state``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Request

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from fastapi_admin_kit.auth.protocol import AdminUserProtocol


def _get_session_backend(request: Request) -> Any:
    """Return the configured session backend, or ``None`` if not initialised."""
    return getattr(request.app.state, "admin_session_backend", None)


def _get_auth_backend(request: Request) -> Any:
    """Return the configured auth backend, or ``None`` if not initialised."""
    return getattr(request.app.state, "admin_auth_backend", None)


def _get_db_session(request: Request) -> AsyncSession | None:
    """Return the per-request DB session, falling back to app.state."""
    from fastapi_admin_kit.db import get_db_session

    try:
        return get_db_session(request)
    except AttributeError:
        return None


async def resolve_user(request: Request, user_id: int | str | None) -> AdminUserProtocol | None:
    """Resolve *user_id* to an active user and cache it on the request.

    Idempotent for a given request: if ``request.state.admin_user`` is already
    populated, it is returned without another DB hit. Returns ``None`` when the
    user is absent or no longer active — callers decide whether that is an
    error (views raise 401) or a soft miss (list/form views render unauthed).

    Always honours the configured ``AuthBackend.get_user`` seam, so BYO user
    models are supported on every transport (cookie *and* JWT), not just the
    built-in one.
    """
    cached = getattr(request.state, "admin_user", None)
    if cached is not None:
        if not hasattr(request.state, "admin_user_snapshot"):
            try:
                role_ids = list(getattr(cached, "role_ids", []))
            except Exception:
                role_ids = []
            request.state.admin_user_snapshot = {
                "id": getattr(cached, "id", None),
                "email": getattr(cached, "email", None),
                "is_superuser": bool(getattr(cached, "is_superuser", False)),
                "role_ids": role_ids,
            }
        return cached

    if user_id is None:
        return None

    auth_backend = _get_auth_backend(request)
    session = _get_db_session(request)
    if auth_backend is None or session is None:
        return None

    user = await auth_backend.get_user(user_id, session)
    if user is None or not getattr(user, "is_active", False):
        return None

    # Per-request memoisation. This is request-scoped state, never app-scoped:
    # two concurrent requests on the same Admin instance resolve independently.
    request.state.admin_user = user

    # Snapshot scalar fields into a plain dict so sync code can read them
    # without touching the ORM object (which may be expired after a rollback).
    # Use getattr with [] default — role_ids may not be loaded yet for BYO models.
    try:
        role_ids = list(getattr(user, "role_ids", []))
    except Exception:
        role_ids = []
    request.state.admin_user_snapshot = {
        "id": getattr(user, "id", None),
        "email": getattr(user, "email", None),
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        "role_ids": role_ids,
    }

    # Inject user identity into the audit context so audit listeners can
    # record who performed the action.  The middleware already set IP and
    # user-agent; this merges the user fields in.
    from fastapi_admin_kit.audit.context import set_audit_context

    set_audit_context(
        {
            "user_id": request.state.admin_user_snapshot["id"],
            "user_email": request.state.admin_user_snapshot["email"],
        }
    )

    return user


def _decode_cookie_payload(request: Request) -> dict[str, Any] | None:
    """Read and decode the signed admin session cookie. Returns ``None`` if absent/invalid."""
    backend = _get_session_backend(request)
    if backend is None:
        return None
    token = request.cookies.get(getattr(backend, "cookie_name", "admin_session"))
    return backend.decode(token) if token else None


async def get_current_user_from_cookie(
    request: Request,
) -> AdminUserProtocol | None:
    """Resolve the current user from the signed ``admin_session`` cookie.

    Returns ``None`` when there is no valid session. Does not raise — callers
    (dependencies, view factories) decide whether a missing user is a 401.
    """
    payload = _decode_cookie_payload(request)
    if payload is None:
        return None
    return await resolve_user(request, payload.get("user_id"))


async def get_current_user_from_bearer(
    request: Request,
) -> AdminUserProtocol | None:
    """Resolve the current user from an ``Authorization: Bearer <jwt>`` header.

    Returns ``None`` when the header is absent or the token is invalid/expired.
    The DB lookup is delegated to :func:`resolve_user`, so the JWT API now
    honours the ``AuthBackend.get_user`` seam just like the cookie path.
    """
    # Imported lazily to avoid a circular import at module load time.
    from fastapi_admin_kit.api.auth import _get_secret_key, decode_access_token

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[len("Bearer ") :]
    secret_key = _get_secret_key(request)
    payload = decode_access_token(token, secret_key)
    if payload is None:
        return None

    sub = payload.get("sub")
    if sub is None:
        return None
    try:
        user_id: int | str = int(sub)  # type: ignore[assignment]
    except (TypeError, ValueError):
        return None
    return await resolve_user(request, user_id)
