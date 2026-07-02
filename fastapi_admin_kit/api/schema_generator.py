"""Dynamic Pydantic schema generation from SQLAlchemy models."""

from __future__ import annotations

import datetime
from typing import Any

from pydantic import BaseModel, Field, create_model


def _sa_type_to_python(sa_type: Any) -> type:
    """Map a SQLAlchemy column type to a Python type for Pydantic."""
    from sqlalchemy import (
        Boolean,
        Date,
        DateTime,
        Enum,
        Float,
        Integer,
        LargeBinary,
        Numeric,
        String,
        Text,
        Time,
    )

    type_cls = type(sa_type)

    if type_cls in (Integer,):
        return int
    if type_cls in (Float, Numeric):
        return float
    if type_cls in (Boolean,):
        return bool
    if type_cls in (String, Text):
        return str
    if type_cls in (DateTime,):
        return datetime.datetime
    if type_cls in (Date,):
        return datetime.date
    if type_cls in (Time,):
        return datetime.time
    if type_cls in (LargeBinary,):
        return bytes
    if type_cls is Enum:
        return str
    return Any


def _get_column_python_type(col: Any) -> type:
    """Get the Python type for a column, handling ForeignKey."""
    if col.foreign_keys:
        return int
    return _sa_type_to_python(col.type)


def _collect_fields(registered: Any, *, exclude_pk: bool = False) -> list[Any]:
    """Collect columns to include in a schema, respecting ModelAdmin config."""
    admin = registered.admin
    columns = list(registered.columns)

    if exclude_pk:
        columns = [c for c in columns if not c.primary_key]

    if admin.fields is not None:
        field_names = set(admin.fields)
        columns = [c for c in columns if c.name in field_names]

    if admin.exclude:
        columns = [c for c in columns if c.name not in admin.exclude]

    return columns


def build_create_schema(registered: Any) -> type[BaseModel]:
    """Build a Pydantic model for create requests.

    Excludes PK, readonly fields, and server-default-only fields.
    """
    admin = registered.admin
    readonly = set(admin.readonly_fields or [])
    columns = _collect_fields(registered, exclude_pk=True)

    fields: dict[str, Any] = {}
    for col in columns:
        if col.name in readonly:
            continue
        if col.server_default is not None and col.default is None:
            continue

        python_type = _get_column_python_type(col)
        if col.nullable:
            field_info = (python_type | None, Field(default=None))
        else:
            field_info = (python_type, Field(...))

        fields[col.name] = field_info

    model_name = f"{registered.verbose_name.replace(' ', '')}Create"
    return create_model(model_name, __config__=None, **fields)


def build_update_schema(registered: Any) -> type[BaseModel]:
    """Build a Pydantic model for update requests.

    All fields optional. Excludes PK and readonly fields.
    """
    admin = registered.admin
    readonly = set(admin.readonly_fields or [])
    columns = _collect_fields(registered, exclude_pk=True)

    fields: dict[str, Any] = {}
    for col in columns:
        if col.name in readonly:
            continue

        python_type = _get_column_python_type(col)
        field_info = (python_type | None, Field(default=None))
        fields[col.name] = field_info

    model_name = f"{registered.verbose_name.replace(' ', '')}Update"
    return create_model(model_name, __config__=None, **fields)


def build_response_schema(registered: Any) -> type[BaseModel]:
    """Build a Pydantic model for response output."""
    columns = list(registered.columns)

    fields: dict[str, Any] = {}
    for col in columns:
        python_type = _get_column_python_type(col)
        if col.nullable:
            field_info = (python_type | None, Field(default=None))
        else:
            field_info = (python_type, Field(...))
        fields[col.name] = field_info

    model_name = f"{registered.verbose_name.replace(' ', '')}Response"
    return create_model(model_name, __config__=None, **fields)


def build_list_response_schema(registered: Any) -> type[BaseModel]:
    """Build a paginated list response schema wrapping the response schema."""
    item_schema = build_response_schema(registered)

    model_name = f"{registered.verbose_name.replace(' ', '')}ListResponse"
    return create_model(
        model_name,
        items=(list[item_schema], Field(...)),
        total=(int, Field(...)),
        page=(int | None, Field(default=None)),
        per_page=(int, Field(...)),
        total_pages=(int | None, Field(default=None)),
        next_cursor=(str | None, Field(default=None)),
        has_next=(bool, Field(default=False)),
    )


def get_or_build_schemas(registered: Any) -> dict[str, type[BaseModel]]:
    """Get or generate and cache schemas for a registered model."""
    if hasattr(registered, "_schemas") and registered._schemas is not None:
        return registered._schemas

    schemas = {
        "create": build_create_schema(registered),
        "update": build_update_schema(registered),
        "response": build_response_schema(registered),
        "list_response": build_list_response_schema(registered),
    }
    registered._schemas = schemas
    return schemas
