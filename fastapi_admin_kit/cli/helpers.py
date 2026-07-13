"""CLI helpers for resolving model class names to table names."""

from __future__ import annotations


def resolve_table_names(names: list[str]) -> dict[str, str]:
    """Resolve class names or table names to actual table names.

    Accepts class names (e.g., 'User', 'product') or table names (e.g., 'admin_users').
    Returns a dict mapping input name -> resolved table_name.
    """
    from fastapi_admin_kit.audit.models import AuditLog
    from fastapi_admin_kit.auth.models import (
        LoginAttempt,
        Permission,
        RefreshToken,
        Role,
        User,
        UserPermission,
        UserTOTP,
    )

    all_models = [
        User,
        Role,
        Permission,
        UserPermission,
        RefreshToken,
        UserTOTP,
        LoginAttempt,
        AuditLog,
    ]

    class_to_table: dict[str, str] = {}
    for cls in all_models:
        class_to_table[cls.__name__.lower()] = cls.__tablename__

    resolved: dict[str, str] = {}
    for name in names:
        key = name.lower()
        if key in class_to_table:
            resolved[name] = class_to_table[key]
        else:
            resolved[name] = name

    return resolved
