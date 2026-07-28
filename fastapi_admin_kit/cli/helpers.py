"""CLI helpers for resolving model class names to table names."""

from __future__ import annotations

import importlib
import logging

logger = logging.getLogger(__name__)


def import_by_path(dotted_path: str) -> type:
    """Import a class/object by its full dotted path (e.g. 'myapp.models.User').

    Returns the resolved object.
    Raises ImportError or AttributeError if not found.
    """
    module_path, _, attr_name = dotted_path.rpartition(".")
    if not module_path:
        raise ImportError(f"Invalid import path: {dotted_path!r} (no module component)")
    module = importlib.import_module(module_path)
    return getattr(module, attr_name)


def _all_subclasses(cls: type) -> set[type]:
    """Recursively collect all subclasses of *cls*, excluding the class itself."""
    result: set[type] = set()
    work = list(cls.__subclasses__())
    while work:
        sub = work.pop()
        if sub not in result:
            result.add(sub)
            work.extend(sub.__subclasses__())
    return result


def resolve_models_from_base(base_path: str, app_module: str | None = None) -> list[type]:
    """Import a base class by dot path, then return all its SQLAlchemy model subclasses.

    The base class itself is excluded — only concrete child classes are returned.
    """
    if app_module:
        try:
            module_name = app_module.split(":")[0]
            importlib.import_module(module_name)
        except Exception as exc:
            logger.warning("Could not import '%s': %s", app_module, exc)

    base_cls = import_by_path(base_path)
    subclasses = _all_subclasses(base_cls)

    models = []
    for sub in subclasses:
        if hasattr(sub, "__tablename__"):
            models.append(sub)
    return models


def resolve_model_by_path(dotted_path: str, app_module: str | None = None) -> type:
    """Import a single model class by its full dotted path.

    Raises ImportError or AttributeError if not found.
    """
    if app_module:
        try:
            module_name = app_module.split(":")[0]
            importlib.import_module(module_name)
        except Exception as exc:
            logger.warning("Could not import '%s': %s", app_module, exc)

    cls = import_by_path(dotted_path)
    if not hasattr(cls, "__tablename__"):
        raise TypeError(f"{dotted_path!r} does not have a __tablename__ — not a SQLAlchemy model")
    return cls


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
