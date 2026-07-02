"""Profile views — password change and profile editing."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from fastapi_admin_kit.auth.csrf import require_csrf_token
from fastapi_admin_kit.auth.dependencies import get_current_admin_user
from fastapi_admin_kit.auth.protocol import AdminUserProtocol
from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.views.sidebar import inject_sidebar_context

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
async def profile_view(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
):
    """Show current user profile."""
    templates = request.app.state.admin_jinja_env
    return templates.TemplateResponse(
        request,
        "pages/profile/profile.html",
        await inject_sidebar_context(
            request,
            {
                "profile_user": user,
            },
        ),
    )


@router.post("/profile")
async def profile_update(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
    _csrf: bool = Depends(require_csrf_token),
):
    """Update profile (full_name, email)."""
    from fastapi_admin_kit.auth.backend import pwd_context

    session = get_db_session(request)
    form = await request.form()

    email = form.get("email", "").strip()
    full_name = form.get("full_name", "").strip()
    password = form.get("password", "")

    if not password:
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/profile/profile.html",
            await inject_sidebar_context(
                request,
                {
                    "profile_user": user,
                    "error": "Password is required to save changes.",
                },
            ),
        )

    if not pwd_context.verify(password, user.hashed_password):
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/profile/profile.html",
            await inject_sidebar_context(
                request,
                {
                    "profile_user": user,
                    "error": "Incorrect password.",
                },
            ),
        )

    if email:
        existing = await session.execute(
            select(type(user)).where(
                type(user).email == email, type(user).id != user.id
            )
        )
        if existing.scalar_one_or_none():
            templates = request.app.state.admin_jinja_env
            return templates.TemplateResponse(
                request,
                "pages/profile/profile.html",
                await inject_sidebar_context(
                    request,
                    {
                        "profile_user": user,
                        "error": "Email already in use.",
                    },
                ),
            )
        user.email = email

    user.full_name = full_name
    await session.flush()

    return RedirectResponse(url="/admin/profile", status_code=302)


@router.get("/profile/password", response_class=HTMLResponse)
async def password_change_view(
    request: Request,
    _: AdminUserProtocol = Depends(get_current_admin_user),
):
    """Show change password form."""
    templates = request.app.state.admin_jinja_env
    return templates.TemplateResponse(
        request,
        "pages/profile/password.html",
        await inject_sidebar_context(request, {}),
    )


@router.post("/profile/password")
async def password_change_post(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
    _csrf: bool = Depends(require_csrf_token),
):
    """Handle password change."""
    from fastapi_admin_kit.auth.backend import pwd_context
    from fastapi_admin_kit.auth.password import validate_password_strength

    session = get_db_session(request)
    form = await request.form()

    current_password = form.get("current_password", "")
    new_password = form.get("new_password", "")
    confirm_password = form.get("confirm_password", "")

    if not pwd_context.verify(current_password, user.hashed_password):
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/profile/password.html",
            await inject_sidebar_context(
                request,
                {
                    "error": "Current password is incorrect.",
                },
            ),
        )

    if new_password != confirm_password:
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/profile/password.html",
            await inject_sidebar_context(
                request,
                {
                    "error": "New passwords do not match.",
                },
            ),
        )

    password_errors = validate_password_strength(new_password)
    if password_errors:
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/profile/password.html",
            await inject_sidebar_context(
                request,
                {
                    "error": password_errors[0],
                },
            ),
        )

    user.hashed_password = pwd_context.hash(new_password)
    user.password_changed_at = datetime.now(UTC)
    await session.flush()

    # Revoke all refresh tokens for this user
    from sqlalchemy import update

    from fastapi_admin_kit.auth.models import AdminRefreshToken

    await session.execute(
        update(AdminRefreshToken)
        .where(
            AdminRefreshToken.user_id == user.id,
            AdminRefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(UTC))
    )
    await session.flush()

    # Clear session and redirect to login
    from fastapi_admin_kit.auth.csrf import CSRF_COOKIE_NAME

    response = RedirectResponse(url="/admin/login", status_code=302)
    session_backend = request.app.state.admin_session_backend
    samesite = getattr(
        request.app.state.admin_state, "session_samesite", "strict"
    )
    response.delete_cookie(
        key=session_backend.cookie_name,
        path="/",
        secure=session_backend.secure,
        httponly=True,
        samesite=samesite,
    )
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        path="/",
    )
    return response
