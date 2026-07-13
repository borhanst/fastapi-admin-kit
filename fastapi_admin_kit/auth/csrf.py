"""CSRF protection — double-submit cookie pattern with HMAC signing."""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse

CSRF_COOKIE_NAME = "admin_csrf_token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_TOKEN_MAX_AGE = 3600  # 1 hour


def _get_secret_key(request: Request) -> str | None:
    """Resolve the CSRF signing key from app state.

    Prefers an explicit ``app.state.admin_secret_key`` (the unified signing-key
    source shared with sessions and JWT); falls back to the session backend's
    public ``secret_key``. Returns ``None`` only when neither is configured.
    """
    explicit = getattr(request.app.state, "admin_secret_key", None)
    if explicit:
        return explicit
    session_backend = getattr(request.app.state, "admin_session_backend", None)
    if session_backend is None:
        return None
    return getattr(session_backend, "secret_key", None)


def generate_csrf_token(secret_key: str) -> str:
    """Generate a signed CSRF token: ``timestamp.random_hex.signature``."""
    random_bytes = os.urandom(16)
    timestamp = str(int(time.time()))
    payload = f"{timestamp}.{random_bytes.hex()}"
    signature = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{payload}.{signature}"


def _verify_csrf_token(secret_key: str, token: str) -> bool:
    """Verify the HMAC signature and check token freshness."""
    parts = token.rsplit(".", 2)
    if len(parts) != 3:
        return False
    timestamp_str, random_hex, provided_sig = parts
    payload = f"{timestamp_str}.{random_hex}"
    expected_sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(provided_sig, expected_sig):
        return False
    try:
        token_time = int(timestamp_str)
    except ValueError:
        return False
    if time.time() - token_time > CSRF_TOKEN_MAX_AGE:
        return False
    return True


def set_csrf_cookie(response: Response, secret_key: str) -> str:
    """Generate and set the CSRF cookie on a response. Returns the token."""
    token = generate_csrf_token(secret_key)
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        max_age=CSRF_TOKEN_MAX_AGE,
        path="/",
        secure=False,
        httponly=False,
        samesite="strict",
    )
    return token


def validate_csrf_token(request: Request, csrf_token: str | None = None) -> None:
    """Validate CSRF token from form body or header against the cookie.

    Raises ``HTTPException(403)`` if the token is missing or invalid.
    Fails *closed*: if no signing key is configured (the admin was not
    set up properly), raises ``HTTPException(500)`` rather than silently
    disabling CSRF protection — a missing key must never mean "protection off".
    """
    secret_key = _get_secret_key(request)
    if secret_key is None:
        raise HTTPException(
            status_code=500,
            detail="CSRF secret not configured — admin session backend not initialised.",
        )

    # Read token from argument, header, or request state (set by middleware)
    form_token = csrf_token
    if form_token is None:
        form_token = request.headers.get(CSRF_HEADER)
    if form_token is None:
        form_token = getattr(request.state, "_csrf_token", None)
    if not form_token:
        raise HTTPException(
            status_code=403,
            detail="CSRF token missing. Please refresh the page and try again.",
        )

    # Read the cookie token
    cookie_token = request.cookies.get(CSRF_COOKIE_NAME)
    if not cookie_token:
        raise HTTPException(
            status_code=403,
            detail="CSRF session cookie missing. Please refresh the page and try again.",
        )

    # Verify both tokens have valid HMAC signatures
    if not _verify_csrf_token(secret_key, form_token):
        raise HTTPException(
            status_code=403,
            detail="Invalid CSRF token. Please refresh the page and try again.",
        )
    if not _verify_csrf_token(secret_key, cookie_token):
        raise HTTPException(
            status_code=403,
            detail="Invalid CSRF cookie. Please refresh the page and try again.",
        )
    # Compare the inner payloads (timestamp + random)
    form_parts = form_token.rsplit(".", 2)
    cookie_parts = cookie_token.rsplit(".", 2)
    if form_parts[0] != cookie_parts[0] or form_parts[1] != cookie_parts[1]:
        raise HTTPException(
            status_code=403,
            detail="CSRF token mismatch. Please refresh the page and try again.",
        )


async def require_csrf_token(request: Request) -> None:
    """FastAPI dependency that enforces CSRF validation on state-changing requests.

    Reads the CSRF token from ``X-CSRF-Token`` header or from the form body
    (extracted by :class:`CSRFMiddleware` and stored in ``request.state``).
    """
    validate_csrf_token(request)


# ---------------------------------------------------------------------------
# CSRF Middleware — extracts form CSRF token + generates per-request token
# ---------------------------------------------------------------------------


class CSRFMiddleware(BaseHTTPMiddleware):
    """Middleware that:
    1. Generates a CSRF token per request and stores it in ``request.state.csrf_token``
       for templates to render as a hidden field or meta tag.
    2. Sets the CSRF cookie on GET requests if not already present.
    3. Extracts the CSRF token from form bodies on POST/PUT/PATCH/DELETE requests
       and stores it in ``request.state._csrf_token`` for the dependency to validate.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate per-request CSRF token for templates
        secret_key = _get_secret_key(request)
        if secret_key is not None:
            existing_cookie = request.cookies.get(CSRF_COOKIE_NAME)
            if existing_cookie and _verify_csrf_token(secret_key, existing_cookie):
                csrf_token = existing_cookie
            else:
                csrf_token = generate_csrf_token(secret_key)
            request.state.csrf_token = csrf_token
        else:
            secret_key = ""
            csrf_token = ""
            request.state.csrf_token = ""

        # On state-changing requests, extract CSRF token from form body
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            content_type = request.headers.get("content-type", "")
            is_form = (
                "application/x-www-form-urlencoded" in content_type
                or "multipart/form-data" in content_type
            )
            if is_form:
                try:
                    body = await request.body()
                    from urllib.parse import parse_qs

                    form_data = parse_qs(body.decode("utf-8", errors="replace"))
                    csrf_values = form_data.get(CSRF_FORM_FIELD)
                    if csrf_values:
                        request.state._csrf_token = csrf_values[0]
                except Exception:
                    pass  # Let the dependency handle missing token

        response = await call_next(request)

        # Set CSRF cookie on all responses so it's always present
        if secret_key:
            response.set_cookie(
                key=CSRF_COOKIE_NAME,
                value=csrf_token,
                max_age=CSRF_TOKEN_MAX_AGE,
                path="/",
                secure=False,
                httponly=False,
                samesite="strict",
            )

        return response


# ---------------------------------------------------------------------------
# Auth Redirect Exception Handler — redirects HTML requests to login on 401
# ---------------------------------------------------------------------------


async def auth_redirect_handler(request: Request, exc: HTTPException) -> Response:
    """Exception handler that catches 401 HTTPExceptions and redirects
    HTML requests to the login page instead of returning a JSON error.
    """
    if exc.status_code == 401:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            admin_path = request.app.state.admin_config["admin_path"]
            login_url = f"{admin_path}/login"
            current_path = request.url.path
            if current_path != f"{admin_path}/login":
                if request.url.query:
                    login_url += f"?next={current_path}%3F{request.url.query}"
                else:
                    login_url += f"?next={current_path}"
            return RedirectResponse(url=login_url, status_code=302)
        from starlette.responses import JSONResponse

        return JSONResponse(
            status_code=401,
            content={"detail": exc.detail or "Not authenticated"},
        )
    raise exc


async def forbidden_handler(request: Request, exc: HTTPException) -> Response:
    """Exception handler for 403 Forbidden errors.

    Returns HTML error page for browser requests, JSON for API clients.
    """
    if exc.status_code == 403:
        accept = request.headers.get("accept", "")
        if "text/html" in accept or "text/xhtml" in accept:
            templates = request.app.state.admin_jinja_env
            admin_path = request.app.state.admin_config["admin_path"]
            detail = exc.detail or "You do not have permission to access this resource."
            return templates.TemplateResponse(
                request,
                "pages/403.html",
                {"admin_path": admin_path, "detail": detail},
                status_code=403,
            )
        from starlette.responses import JSONResponse

        return JSONResponse(
            status_code=403,
            content={"detail": exc.detail or "Forbidden"},
        )
    raise exc
