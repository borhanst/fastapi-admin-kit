"""SQLAlchemy models for admin auth: roles, users, permissions.

.. deprecated:: 2.1.0
   This module is deprecated. Use ``fastapi_admin_kit.migrations.models`` instead,
   which materializes models from schemas for both runtime and Alembic migrations.
   This module will be removed in v3.0.
"""

from __future__ import annotations

import warnings

from fastapi_admin_kit.auth.mixins import AuthModelMixin
from fastapi_admin_kit.migrations.models import (
    LoginAttempt,
    Permission,
    RefreshToken,
    Role,
    User,
    UserPermission,
    UserTOTP,
    admin_role_permissions,
    admin_user_roles,
)

warnings.warn(
    "fastapi_admin_kit.auth.models is deprecated and will be removed in v3.0. "
    "Use fastapi_admin_kit.migrations.models instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the mixin
__all__ = [
    "AuthModelMixin",
    "User",
    "Role",
    "Permission",
    "UserPermission",
    "RefreshToken",
    "UserTOTP",
    "LoginAttempt",
    "admin_user_roles",
    "admin_role_permissions",
]
