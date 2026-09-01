"""Auth views — login, logout."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from fastapi import (
    APIRouter,
    Depends,
    Form,
    Request,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi_admin_kit.auth.backend import AuthBackend
from fastapi_admin_kit.auth.csrf import CSRF_COOKIE_NAME, require_csrf_token
from fastapi_admin_kit.auth.dependencies import _get_db_session, get_session
from fastapi_admin_kit.auth.proxy import get_client_ip
from fastapi_admin_kit.auth.session import SessionBackend
from fastapi_admin_kit.redis import LoginRateGuard, get_login_guard

router = APIRouter()


def _is_safe_url(url: str | None) -> bool:
    """Return True if the URL is relative (no scheme or netloc)."""
    if not url:
        return False
    parsed = urlparse(url)
    return not (parsed.scheme or parsed.netloc)


@router.get("/login", response_class=HTMLResponse, include_in_schema=False)
async def login_get(
    request: Request,
    next: str | None = None,
    error: str | None = None,
    session_payload: dict[str, Any] | None = Depends(get_session),
) -> HTMLResponse:
    """GET /admin/login — show login page, redirect if already logged in."""
    if session_payload is not None:
        # Validate the session actually resolves to a real user.
        # If the DB was reset, the old cookie is stale — show the login
        # page instead of looping between /admin/login ↔ /admin.
        from fastapi_admin_kit.auth.identity import resolve_user

        user = await resolve_user(request, session_payload.get("user_id"))
        if user is not None:
            admin_path = request.app.state.admin_config["admin_path"]
            target = next if _is_safe_url(next) else f"{admin_path}/"
            return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)
        # Stale session — clear the cookie so we don't loop
        session_backend = getattr(request.app.state, "admin_session_backend", None)
        if session_backend is not None:
            from fastapi_admin_kit.auth.csrf import CSRF_COOKIE_NAME

            samesite = getattr(request.app.state.admin_state, "session_samesite", "strict")
            response = RedirectResponse(url=str(request.url), status_code=status.HTTP_302_FOUND)
            response.delete_cookie(
                key=session_backend.cookie_name,
                path="/",
                secure=session_backend.should_secure(request),
                httponly=True,
                samesite=samesite,
            )
            response.delete_cookie(key=CSRF_COOKIE_NAME, path="/")
            return response

    # Parse error from query string
    error_msg = None
    if error:
        from urllib.parse import unquote

        error_msg = unquote(error)

    jinja_env = request.app.state.admin_jinja_env
    template = jinja_env.get_template("pages/login.html")
    csrf_token = getattr(request.state, "csrf_token", "")
    return HTMLResponse(
        template.render(
            {
                "request": request,
                "csrf_token": csrf_token,
                "admin_config": request.app.state.admin_config,
                "error": error_msg,
            }
        )
    )


@router.post("/login", response_model=None, include_in_schema=False)
async def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str | None = Form(None),
    session: AsyncSession = Depends(_get_db_session),
    _csrf: bool = Depends(require_csrf_token),
    _guard: LoginRateGuard = Depends(get_login_guard),
) -> HTMLResponse | RedirectResponse:
    """POST /admin/login — process login form."""
    client_ip = get_client_ip(request)
    await _guard.check(client_ip)

    auth_backend: AuthBackend = request.app.state.admin_auth_backend
    login_field = request.app.state.admin_config.get("login_field", "email")
    # Use the multi-ORM seam: pass the QueryBackend so BuiltinAuthBackend
    # builds queries via backend.query instead of importing sqlalchemy.
    query_adapter = getattr(request.app.state, "admin_query_adapter", None)
    try:
        user = await auth_backend.authenticate(
            username,
            password,
            session,
            login_field=login_field,
            query_adapter=query_adapter,
        )
        print("login user: ", user)
    except TypeError:
        print("login user error: ", user)
        # Custom backends that don't accept query_adapter
        user = await auth_backend.authenticate(username, password, session, login_field=login_field)
    if user is not None:
        await _guard.reset(client_ip)
        now_utc = datetime.now(UTC)
        user_fields = getattr(user, "model_fields", None) or getattr(user, "__fields__", None) or {}
        if "last_login" in user_fields:
            user.last_login = now_utc
        elif "last_login_at" in user_fields:
            user.last_login_at = now_utc
        await session.flush()

        # ── 2FA enforcement (S02) ────────────────────────────────────
        # If the user has TOTP enabled, do NOT issue a session cookie.
        # Issue a short-lived pending token and redirect to /verify-2fa.
        from fastapi_admin_kit.auth.models import LoginAttempt
        from fastapi_admin_kit.auth.totp import has_totp_enabled

        query_adapter = getattr(request.app.state, "admin_query_adapter", None)
        if await has_totp_enabled(session, user.id, query_adapter):
            attempt = LoginAttempt(
                email=username,
                ip_address=client_ip,
                user_agent=request.headers.get("user-agent", ""),
                success=True,
                note="Credentials verified — 2FA required",
            )
            session.add(attempt)
            await session.flush()

            session_backend: SessionBackend = request.app.state.admin_session_backend
            temp_token = session_backend.encode_pending_2fa(user.id)
            admin_path = request.app.state.admin_config["admin_path"]
            redirect_url = f"{admin_path}/verify-2fa?temp_token={temp_token}"
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)

        attempt = LoginAttempt(
            email=username,
            ip_address=client_ip,
            user_agent=request.headers.get("user-agent", ""),
            success=True,
        )
        session.add(attempt)
        await session.flush()

        session_backend: SessionBackend = request.app.state.admin_session_backend
        # Random session id (S18): guarantees a fresh cookie value on every
        # login — two logins in the same second must never mint identical
        # session tokens (itsdangerous timestamps alone are second-granular).
        session_data = {"user_id": user.id, "sid": secrets.token_urlsafe(32)}
        token = session_backend.encode(session_data)

        if next and _is_safe_url(next):
            redirect_url = next
        else:
            admin_path = request.app.state.admin_config["admin_path"]
            redirect_url = f"{admin_path}/"

        samesite = getattr(request.app.state.admin_state, "session_samesite", "strict")
        response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
        response.set_cookie(
            key=session_backend.cookie_name,
            value=token,
            max_age=session_backend._session_ttl,
            path="/",
            secure=session_backend.should_secure(request),
            httponly=True,
            samesite=samesite,
        )

        return response

    await _guard.record_failure(client_ip)

    from fastapi_admin_kit.auth.models import LoginAttempt

    note = "Invalid credentials"
    if await _guard.is_rate_limited(client_ip):
        remaining = await _guard.remaining_seconds(client_ip)
        note = f"Too many failed attempts. Rate limited for {remaining}s"

    attempt = LoginAttempt(
        email=username,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", ""),
        success=False,
        note=note,
    )
    session.add(attempt)
    await session.flush()

    jinja_env = request.app.state.admin_jinja_env
    template = jinja_env.get_template("pages/login.html")
    csrf_token = getattr(request.state, "csrf_token", "")
    remaining = await _guard.remaining_seconds(client_ip)
    error_msg = "Invalid credentials. Please try again."
    if await _guard.is_rate_limited(client_ip):
        error_msg = f"Too many failed attempts. Try again in {remaining} seconds."

    return HTMLResponse(
        template.render(
            {
                "request": request,
                "error": error_msg,
                "csrf_token": csrf_token,
                "admin_config": request.app.state.admin_config,
            }
        ),
        status_code=status.HTTP_200_OK,
    )


@router.post("/logout", include_in_schema=False)
async def logout_post(
    request: Request,
    session_payload: dict[str, Any] | None = Depends(get_session),
    _csrf: bool = Depends(require_csrf_token),
) -> RedirectResponse:
    """POST /admin/logout — clear session and redirect to login."""
    if session_payload is not None:
        auth_backend = request.app.state.admin_auth_backend
        if hasattr(auth_backend, "on_logout"):
            await auth_backend.on_logout(session_payload.get("user_id"))

    session_backend = request.app.state.admin_session_backend
    samesite = getattr(request.app.state.admin_state, "session_samesite", "strict")
    response = RedirectResponse(
        url=f"{request.app.state.admin_config['admin_path']}/login",
        status_code=status.HTTP_302_FOUND,
    )
    response.delete_cookie(
        key=session_backend.cookie_name,
        path="/",
        secure=session_backend.should_secure(request),
        httponly=True,
        samesite=samesite,
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
    )
    return response
