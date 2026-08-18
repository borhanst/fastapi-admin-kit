"""Model inspection — SQLAlchemy model → ColumnMeta / RelationMeta.

Re-exports backward-compatible module-level functions from
:class:`~fastapi_admin_kit.backends.sqlalchemy.SqlAlchemyIntrospectionAdapter`.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, Request

from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemyIntrospectionAdapter
from fastapi_admin_kit.inspection.types import ColumnMeta, RelationMeta

_inspector = SqlAlchemyIntrospectionAdapter()


def inspect_model(model: type) -> tuple[list[ColumnMeta], list[RelationMeta]]:
    """Inspect a SQLAlchemy model and return column + relationship metadata."""
    return _inspector.inspect_model(model)


def is_abstract(model: type) -> bool:
    """Check if a model is abstract and should be skipped during auto-discovery."""
    return getattr(model, "__abstract__", False)


def get_pk_field(model: type) -> str | None:
    """Get the primary key field name for a model.

    Returns the single PK field name for simple PKs,
    or a tuple of names for composite PKs.
    Returns None if no primary key is found.
    """
    return _inspector.get_pk_field(model)


def cast_pk_value(model: type, value: Any) -> Any:
    """Cast a string primary key value to the correct Python type.

    Inspects the model's primary key column type and converts the value
    accordingly. Supports Integer, BigInteger, String, and UUID types.
    Returns the original value if type cannot be determined.
    """
    return _inspector.cast_pk_value(model, value)


def cast_value(col_meta: Any, value: Any) -> Any:
    """Cast a string form value to the correct Python type based on column type.

    Supports Integer, Float, Boolean, and String types.
    Returns the original value if type cannot be determined.
    """
    if value is None:
        return None
    from sqlalchemy import Boolean, Float, Integer

    col_type = type(col_meta.type) if hasattr(col_meta, "type") else None
    if col_type is None:
        return value

    if col_type in (Integer,):
        try:
            return int(value)
        except (ValueError, TypeError):
            return value
    if col_type in (Float,):
        try:
            return float(value)
        except (ValueError, TypeError):
            return value
    if col_type in (Boolean,):
        return value in ("1", "on", "true", "True", "yes")
    return value


def auto_label(name: str) -> str:
    """Auto-generate a human-readable label from a field name.

    Examples:
        "category_id"  → "Category"
        "is_active"    → "Is Active"
        "created_at"   → "Created At"
        "skuCode"      → "Sku Code"
    """
    label = name
    if label.endswith("_id"):
        label = label[:-3]
    label = re.sub(r"([A-Z])", r" \1", label)
    return label.replace("_", " ").strip().title()


def is_required(col: ColumnMeta) -> bool:
    """Determine if a column is required (NOT NULL with no default).

    A column is required if:
    - It is NOT NULL
    - It has no Python default
    - It has no server_default (DB-side default)
    - It is NOT a primary key (PKs are handled separately)
    """
    return (
        not col.nullable
        and col.default is None
        and col.server_default is None
        and not col.primary_key
    )


def model_display_name(obj: Any) -> str:
    """Return a human-readable label for an ORM object.

    Uses the model's ``__str__`` if it has a custom implementation.
    Falls back to ``name``, ``title``, or ``ClassName:pk``.
    """
    if type(obj).__str__ is not object.__str__:
        return str(obj)
    label = getattr(obj, "name", None) or getattr(obj, "title", None)
    if label is not None:
        return str(label)
    pk = getattr(obj, "id", None)
    return f"{type(obj).__name__}:{pk}" if pk is not None else type(obj).__name__


async def validate_related_id(
    model: type,
    related_model: type,
    id_value: Any,
    field_name: str = "id",
    request: Request | None = None,
) -> Any:
    """Validate that a related model ID exists in the database.

    Casts the ID value to the correct type for the related model's primary key,
    fetches the related object, and raises ``HTTPException(404)`` if not found.

    Args:
        model: The model containing the foreign key field (for type resolution).
        related_model: The model whose ID is being validated.
        id_value: The ID value from the request (typically a string from form data).
        field_name: Name of the field for error messaging.
        request: FastAPI Request object. If not provided, session will be
            obtained from the application state (legacy mode).

    Returns:
        The cast primary key value if the related object exists.

    Raises:
        HTTPException: 404 if the related object does not exist.
    """
    from fastapi_admin_kit.db import get_db_session
    from fastapi_admin_kit.inspection import cast_pk_value

    pk_value = cast_pk_value(related_model, id_value)
    session = get_db_session(request) if request else get_db_session(None)
    obj = await session.get(related_model, pk_value)
    if obj is None:
        raise HTTPException(
            status_code=404,
            detail=f"{related_model.__name__} with {field_name}={id_value} not found",
        )
    return pk_value
