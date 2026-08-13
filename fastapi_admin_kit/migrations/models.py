"""Materialized SQLAlchemy models for Alembic migrations.

This module materializes all built-in admin schemas into SQLAlchemy models
at import time, providing a single source of truth for both runtime
and migration autogeneration.

The models are created using SqlAlchemyDatabaseBackend.materialize() from
the Schema definitions in schemas/builtin.py. This ensures schema
definitions are the authoritative source for both the admin UI and
database migrations.
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, Table

from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyDatabaseBackend
from fastapi_admin_kit.models.base import Base
from fastapi_admin_kit.schemas.builtin import (
    AI_ATTACHMENT_SCHEMA,
    AI_CONVERSATION_SCHEMA,
    AI_MESSAGE_SCHEMA,
    AI_USAGE_LOG_SCHEMA,
    AUDIT_LOG_SCHEMA,
    LOGIN_ATTEMPT_SCHEMA,
    NOTIFICATION_LOG_SCHEMA,
    NOTIFICATION_PREFERENCE_SCHEMA,
    NOTIFICATION_SCHEMA,
    PERMISSION_SCHEMA,
    REFRESH_TOKEN_SCHEMA,
    ROLE_SCHEMA,
    USER_PERMISSION_SCHEMA,
    USER_SCHEMA,
    USER_TOTP_SCHEMA,
)

# Materialize all built-in schemas at import time
_backend = SqlAlchemyDatabaseBackend()

# First, create junction tables explicitly so they exist for many-to-many relationships

admin_user_roles = Table(
    "admin_user_roles",
    Base.metadata,
    Column(
        "user_id",
        Integer,
        ForeignKey("admin_users.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "role_id",
        Integer,
        ForeignKey("admin_roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

admin_role_permissions = Table(
    "admin_role_permissions",
    Base.metadata,
    Column(
        "role_id",
        Integer,
        ForeignKey("admin_roles.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "permission_id",
        Integer,
        ForeignKey("admin_permissions.id", ondelete="CASCADE"),
        primary_key=True,
    ),
)

# Auth models - order matters for foreign key resolution
# Materialize child tables first so parent relationships can find FK columns
UserPermission = _backend.materialize(USER_PERMISSION_SCHEMA, base=Base)
RefreshToken = _backend.materialize(REFRESH_TOKEN_SCHEMA, base=Base)
UserTOTP = _backend.materialize(USER_TOTP_SCHEMA, base=Base)

# Then parent tables with relationships to children
# Order matters for many-to-many back_populates relationships
# Role must be materialized before User so the reverse relationship is available
Role = _backend.materialize(ROLE_SCHEMA, base=Base)
User = _backend.materialize(USER_SCHEMA, base=Base)
Permission = _backend.materialize(PERMISSION_SCHEMA, base=Base)

# Audit models
AuditLog = _backend.materialize(AUDIT_LOG_SCHEMA, base=Base)
LoginAttempt = _backend.materialize(LOGIN_ATTEMPT_SCHEMA, base=Base)

# Notification models
Notification = _backend.materialize(NOTIFICATION_SCHEMA, base=Base)
NotificationPreference = _backend.materialize(NOTIFICATION_PREFERENCE_SCHEMA, base=Base)
NotificationLog = _backend.materialize(NOTIFICATION_LOG_SCHEMA, base=Base)

# AI models
AIUsageLog = _backend.materialize(AI_USAGE_LOG_SCHEMA, base=Base)
AIConversation = _backend.materialize(AI_CONVERSATION_SCHEMA, base=Base)
AIMessage = _backend.materialize(AI_MESSAGE_SCHEMA, base=Base)
AIAttachment = _backend.materialize(AI_ATTACHMENT_SCHEMA, base=Base)

# Junction tables are now available via metadata
admin_user_roles = Base.metadata.tables.get("admin_user_roles")
admin_role_permissions = Base.metadata.tables.get("admin_role_permissions")

# Public API for Alembic env.py
__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "UserPermission",
    "RefreshToken",
    "UserTOTP",
    "AuditLog",
    "LoginAttempt",
    "Notification",
    "NotificationPreference",
    "NotificationLog",
    "AIUsageLog",
    "AIConversation",
    "AIMessage",
    "AIAttachment",
    "admin_user_roles",
    "admin_role_permissions",
]

# Emit deprecation warning if old modules are imported
# (This is a module-level side effect; actual warnings are in auth.models/audit.models)


def get_admin_metadata():
    """Return the metadata containing all admin tables for Alembic.

    Usage in alembic/env.py:
        from fastapi_admin_kit.migrations.models import get_admin_metadata
        target_metadata = get_admin_metadata()
    """
    return Base.metadata
