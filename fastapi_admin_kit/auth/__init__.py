"""Auth module — models, session, AuthBackend, PermissionChecker, dependencies."""

from __future__ import annotations

from fastapi_admin_kit.auth.backend import AuthBackend, BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import (
    auth_redirect_handler,
    require_csrf_token,
    set_csrf_cookie,
)
from fastapi_admin_kit.auth.models import (
    AdminPermission,
    AdminRole,
    AdminUser,
    AdminUserPermission,
)
from fastapi_admin_kit.auth.session import (
    SessionBackend,
    SignedCookieSessionBackend,
)

__all__ = [
    "AdminPermission",
    "AdminRole",
    "AdminUser",
    "AdminUserPermission",
    "AuthBackend",
    "BuiltinAuthBackend",
    "SessionBackend",
    "SignedCookieSessionBackend",
    "auth_redirect_handler",
    "require_csrf_token",
    "set_csrf_cookie",
]
