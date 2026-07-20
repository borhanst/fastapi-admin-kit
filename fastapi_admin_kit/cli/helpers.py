"""CLI helpers for resolving model class names to table names."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve_table_names(names: list[str], app_module: str | None = None) -> dict[str, str]:
    """Resolve class names or table names to actual table names.

    Accepts class names (e.g., 'User', 'Product') or table names (e.g., 'admin_users').
    Returns a dict mapping input name -> resolved table_name.

    If *app_module* is provided (e.g. 'example:app'), it is imported first
    so that user-defined models are available for resolution.
    """
    from sqlalchemy.orm import DeclarativeBase

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

    # Import user's app module so their models are discoverable
    if app_module:
        try:
            import importlib

            module_name = app_module.split(":")[0]
            importlib.import_module(module_name)
        except Exception as exc:
            logger.warning("Could not import '%s': %s", app_module, exc)

    # Discover user-defined models via SQLAlchemy declarative registry
    try:
        for subclass in _all_declarative_subclasses(DeclarativeBase):
            if hasattr(subclass, "registry"):
                for mapper in subclass.registry.mappers:
                    cls = mapper.class_
                    if hasattr(cls, "__tablename__"):
                        key = cls.__name__.lower()
                        if key not in class_to_table:
                            class_to_table[key] = cls.__tablename__
    except Exception:
        pass

    # Also discover SQLModel subclasses if installed
    try:
        from sqlmodel import SQLModel

        for subclass in _all_declarative_subclasses(SQLModel):
            if hasattr(subclass, "registry"):
                for mapper in subclass.registry.mappers:
                    cls = mapper.class_
                    if hasattr(cls, "__tablename__"):
                        key = cls.__name__.lower()
                        if key not in class_to_table:
                            class_to_table[key] = cls.__tablename__
    except ImportError:
        pass

    resolved: dict[str, str] = {}
    for name in names:
        key = name.lower()
        if key in class_to_table:
            resolved[name] = class_to_table[key]
        else:
            resolved[name] = name

    return resolved


def _all_declarative_subclasses(base: type) -> set[type]:
    """Recursively collect all subclasses of *base*."""
    result: set[type] = set()
    work = [base]
    while work:
        cls = work.pop()
        for sub in cls.__subclasses__():
            if sub not in result:
                result.add(sub)
                work.append(sub)
    return result
