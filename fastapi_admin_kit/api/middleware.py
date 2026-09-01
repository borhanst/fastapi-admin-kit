"""Access-token middleware — pre-validate bearer JWTs on API routes.

Authenticates (never authorizes) ``Authorization: Bearer`` tokens for
configured path prefixes before the request reaches any route handler:

- an invalid, expired, deactivated-user, or password-stale token is
  rejected with 401 immediately;
- the decoded payload is cached on ``request.state.admin_jwt_payload``
  and the live user on ``request.state.admin_user`` so per-route
  dependencies (:func:`api.deps.require_api_permission`) don't repeat
  the work.

Modes
-----

- **lenient** (default, ``api_token_strict=False``): only tokens that are
  *presented* are validated; requests without the header pass through and
  route dependencies decide. Backwards compatible — public/custom API
  routes keep working.
- **strict** (``api_token_strict=True``): every scoped path requires a
  valid bearer token except the exempt paths (token/refresh/logout by
  default). Use when the whole ``/api`` surface is first-party.

The middleware reads its knobs from ``app.state.admin_config`` at request
time (``api_token_strict``, ``api_token_middleware``), so it can be added
before ``setup()`` populates state.
"""

from __future__ import annotations

from typing import Any

from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.requests import Request as StarletteRequest
from starlette.responses import JSONResponse, Response

DEFAULT_API_PREFIXES = ("/api/",)
"""Path prefixes the middleware scopes to."""

DEFAULT_EXEMPT_PATHS = frozenset(
    {
        "/api/auth/token",
        "/api/auth/refresh",
        "/api/auth/logout",
    }
)
"""Endpoints that must be reachable without a bearer token."""


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


class AccessTokenMiddleware(BaseHTTPMiddleware):
    """Validate bearer access tokens for API routes (see module docstring)."""

    def __init__(
        self,
        app: Any,  # noqa: ANN401 — ASGI app
        api_prefixes: tuple[str, ...] = DEFAULT_API_PREFIXES,
        exempt_paths: frozenset[str] | set[str] = DEFAULT_EXEMPT_PATHS,
    ) -> None:
        super().__init__(app)
        self.api_prefixes = api_prefixes
        self.exempt_paths = exempt_paths

    def _in_scope(self, path: str) -> bool:
        return any(path.startswith(prefix) for prefix in self.api_prefixes)

    async def dispatch(
        self, request: StarletteRequest, call_next: RequestResponseEndpoint
    ) -> Response:
        config = getattr(request.app.state, "admin_config", {}) or {}

        if not config.get("api_token_middleware", True):
            return await call_next(request)

        path = request.url.path
        if not self._in_scope(path):
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            # No token presented: strict mode rejects, lenient mode lets
            # route dependencies decide.
            if config.get("api_token_strict", False) and path not in self.exempt_paths:
                return _unauthorized("Authentication required.")
            return await call_next(request)

        from fastapi_admin_kit.api.auth import (
            _get_secret_key,
            decode_access_token,
            token_predates_password_change,
        )
        from fastapi_admin_kit.auth.identity import resolve_user

        try:
            secret_key = _get_secret_key(request)
        except Exception:  # noqa: BLE001 — app misconfiguration surfaces below
            return await call_next(request)

        payload = decode_access_token(auth_header[7:], secret_key)
        if payload is None:
            return _unauthorized("Invalid or expired token.")

        sub = payload.get("sub")
        user_id: int | str | None = None
        if sub is not None:
            try:
                user_id = int(sub)
            except (TypeError, ValueError):
                user_id = None

        user = await resolve_user(request, user_id) if user_id is not None else None
        if user is None:
            return _unauthorized("Account not found or inactive.")

        if token_predates_password_change(payload, user):
            return _unauthorized("Token has been revoked.")

        # Share the work with per-route dependencies.
        request.state.admin_jwt_payload = payload

        return await call_next(request)
