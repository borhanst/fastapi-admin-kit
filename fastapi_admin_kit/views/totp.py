"""TOTP 2FA management views."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from fastapi_admin_kit.auth.csrf import require_csrf_token
from fastapi_admin_kit.auth.dependencies import get_current_admin_user
from fastapi_admin_kit.auth.models import UserTOTP
from fastapi_admin_kit.auth.protocol import AdminUserProtocol
from fastapi_admin_kit.auth.totp import (
    generate_backup_codes,
    generate_secret,
    get_totp_uri,
    hash_backup_code,
    verify_totp,
)
from fastapi_admin_kit.db import get_db_session
from fastapi_admin_kit.views.sidebar import inject_sidebar_context

router = APIRouter()


@router.get("/profile/2fa", response_class=HTMLResponse)
async def totp_setup_view(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
):
    """Show 2FA setup page with QR code."""
    templates = request.app.state.admin_jinja_env
    session = get_db_session(request)

    result = await session.execute(
        select(UserTOTP).where(UserTOTP.user_id == user.id)
    )
    totp_record = result.scalar_one_or_none()

    secret = None
    qr_uri = None
    enabled = False

    if totp_record and totp_record.enabled:
        enabled = True
    else:
        if totp_record is None:
            secret = generate_secret()
            totp_record = UserTOTP(
                user_id=user.id,
                secret_key=secret,
                enabled=False,
            )
            session.add(totp_record)
            await session.flush()
        else:
            secret = totp_record.secret_key

        qr_uri = get_totp_uri(secret, user.email) if secret else None

    return templates.TemplateResponse(
        request,
        "pages/2fa/setup.html",
        await inject_sidebar_context(
            request,
            {
                "secret": secret,
                "qr_uri": qr_uri,
                "totp_enabled": enabled,
            },
        ),
    )


@router.post("/profile/2fa/enable")
async def totp_enable_post(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
    _csrf: bool = Depends(require_csrf_token),
):
    """Verify TOTP code and enable 2FA."""
    session = get_db_session(request)
    form = await request.form()

    code = form.get("code", "").strip()

    result = await session.execute(
        select(UserTOTP).where(UserTOTP.user_id == user.id)
    )
    totp_record = result.scalar_one_or_none()

    if totp_record is None:
        raise HTTPException(status_code=400, detail="No TOTP setup found.")

    if not verify_totp(totp_record.secret_key, code):
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/2fa/setup.html",
            await inject_sidebar_context(
                request,
                {
                    "secret": totp_record.secret_key,
                    "qr_uri": get_totp_uri(totp_record.secret_key, user.email),
                    "totp_enabled": False,
                    "error": "Invalid TOTP code. Please try again.",
                },
            ),
        )

    backup_codes = generate_backup_codes()
    hashed_codes = [hash_backup_code(c) for c in backup_codes]

    totp_record.enabled = True
    totp_record.backup_codes = json.dumps(hashed_codes)
    await session.flush()

    templates = request.app.state.admin_jinja_env
    return templates.TemplateResponse(
        request,
        "pages/2fa/setup.html",
        await inject_sidebar_context(
            request,
            {
                "secret": None,
                "qr_uri": None,
                "totp_enabled": True,
                "backup_codes": backup_codes,
                "success": "2FA enabled successfully. Save your backup codes!",
            },
        ),
    )


@router.post("/profile/2fa/disable")
async def totp_disable_post(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
    _csrf: bool = Depends(require_csrf_token),
):
    """Disable 2FA after verifying TOTP code and password."""
    

    session = get_db_session(request)
    form = await request.form()

    code = form.get("code", "").strip()
    password = form.get("password", "")

    if not user.verify_password(password):
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/2fa/setup.html",
            await inject_sidebar_context(
                request,
                {
                    "totp_enabled": True,
                    "error": "Incorrect password.",
                },
            ),
        )

    result = await session.execute(
        select(UserTOTP).where(UserTOTP.user_id == user.id)
    )
    totp_record = result.scalar_one_or_none()

    if totp_record is None or not totp_record.enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled.")

    if not verify_totp(totp_record.secret_key, code):
        templates = request.app.state.admin_jinja_env
        return templates.TemplateResponse(
            request,
            "pages/2fa/setup.html",
            await inject_sidebar_context(
                request,
                {
                    "totp_enabled": True,
                    "error": "Invalid TOTP code.",
                },
            ),
        )

    totp_record.enabled = False
    totp_record.backup_codes = None
    await session.flush()

    return RedirectResponse(url="/admin/profile/2fa", status_code=302)


@router.post("/profile/2fa/backup-codes")
async def totp_regenerate_backup_codes(
    request: Request,
    user: AdminUserProtocol = Depends(get_current_admin_user),
    _csrf: bool = Depends(require_csrf_token),
):
    """Generate new backup codes (invalidates old ones)."""
    session = get_db_session(request)

    result = await session.execute(
        select(UserTOTP).where(UserTOTP.user_id == user.id)
    )
    totp_record = result.scalar_one_or_none()

    if totp_record is None or not totp_record.enabled:
        raise HTTPException(status_code=400, detail="2FA is not enabled.")

    backup_codes = generate_backup_codes()
    hashed_codes = [hash_backup_code(c) for c in backup_codes]

    totp_record.backup_codes = json.dumps(hashed_codes)
    await session.flush()

    templates = request.app.state.admin_jinja_env
    return templates.TemplateResponse(
        request,
        "pages/2fa/setup.html",
        await inject_sidebar_context(
            request,
            {
                "totp_enabled": True,
                "backup_codes": backup_codes,
                "success": "New backup codes generated. Old codes are now invalid.",
            },
        ),
    )


@router.get("/verify-2fa", response_class=HTMLResponse)
async def totp_verify_view(
    request: Request,
    temp_token: str | None = None,
):
    """Show 2FA verification page during login."""
    templates = request.app.state.admin_jinja_env
    return templates.TemplateResponse(
        request,
        "pages/2fa/verify.html",
        await inject_sidebar_context(
            request,
            {
                "temp_token": temp_token,
            },
        ),
    )
