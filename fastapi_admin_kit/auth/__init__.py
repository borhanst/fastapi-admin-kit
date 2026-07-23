"""Auth module — models, session, AuthBackend, PermissionChecker, dependencies."""

from __future__ import annotations

from fastapi_admin_kit.auth.backend import AuthBackend, BuiltinAuthBackend
from fastapi_admin_kit.auth.csrf import (
    auth_redirect_handler,
    forbidden_handler,
    require_csrf_token,
    set_csrf_cookie,
)
from fastapi_admin_kit.auth.hasher import BcryptHasher, PasswordHasher
from fastapi_admin_kit.auth.mixins import AuthModelMixin
from fastapi_admin_kit.auth.models import (
    Permission,
    Role,
    User,
    UserPermission,
)
from fastapi_admin_kit.auth.protocol import (
    AdminPermissionProtocol,
    AdminRoleProtocol,
    AdminUserProtocol,
)
from fastapi_admin_kit.auth.session import (
    SessionBackend,
    SignedCookieSessionBackend,
)

__all__ = [
    "AdminPermissionProtocol",
    "AdminRoleProtocol",
    "AdminUserProtocol",
    "AuthModelMixin",
    "BcryptHasher",
    "Permission",
    "PasswordHasher",
    "Role",
    "User",
    "UserPermission",
    "AuthBackend",
    "BuiltinAuthBackend",
    "SessionBackend",
    "SignedCookieSessionBackend",
    "auth_redirect_handler",
    "forbidden_handler",
    "require_csrf_token",
    "set_csrf_cookie",
]
