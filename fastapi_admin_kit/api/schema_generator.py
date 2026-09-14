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
    return Any


def _enum_python_type(sa_type: Any, field_name: str) -> type:
    """Return the Python type for a SQLAlchemy ``Enum`` column.

    Uses the underlying Python enum class when the column declares one;
    otherwise builds a dynamic ``Enum`` with one member per stored value so
    Swagger renders the field as a dropdown either way. Falls back to ``str``
    when no value list is known.
    """
    import enum

    enum_class = getattr(sa_type, "enum_class", None)
    if isinstance(enum_class, type) and issubclass(enum_class, enum.Enum):
        return enum_class
    values = list(getattr(sa_type, "enums", None) or [])
    if values:
        # ponytail: member names are generated (values may not be valid
        # identifiers); two models sharing a field_name with different values
        # would share one OpenAPI component — scope by model if it ever bites.
        members = {f"MEMBER_{i}": v for i, v in enumerate(values)}
        return enum.Enum(f"{field_name}Enum", members)
    return str


def _get_column_python_type(col: Any) -> type:
    """Get the Python type for a column, handling ForeignKey and Enum."""
    if col.foreign_keys:
        return int
    from sqlalchemy import Enum

    if isinstance(col.type, Enum):
        return _enum_python_type(col.type, col.name)
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


def _collect_relationships(registered: Any) -> list[Any]:
    """Collect relationships to include in a schema, respecting ModelAdmin config."""
    admin = registered.admin
    relationships = list(registered.relationships)

    if admin.fields is not None:
        field_names = set(admin.fields)
        relationships = [r for r in relationships if r.name in field_names]

    if admin.exclude:
        relationships = [r for r in relationships if r.name not in admin.exclude]

    return relationships


def _add_extra_fields(admin: Any, fields: dict[str, Any], *, required_on_create: bool) -> None:
    """Add ModelAdmin.extra_fields (e.g. ``password``) to a request schema.

    The HTML form exposes these virtual fields; the JSON API must accept
    them too so create/update validation behaves identically on both
    transports.
    """
    readonly = set(admin.readonly_fields or [])
    for extra in getattr(admin, "extra_fields", None) or []:
        if extra.name in fields or extra.name in readonly:
            continue
        if required_on_create and extra.required_on_create:
            fields[extra.name] = (str | None, Field(...))
        else:
            fields[extra.name] = (str | None, Field(default=None))


def _relationship_python_type(rel: Any) -> type:
    """Get the Python type for a relationship field in a request schema.

    MANYTOONE → the target primary key (int); MANYTOMANY → a list of PKs.
    """
    if rel.direction == "MANYTOMANY":
        return list[int]
    return int


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

    for rel in _collect_relationships(registered):
        if rel.name in readonly or rel.name in fields:
            continue
        python_type = _relationship_python_type(rel)
        fields[rel.name] = (python_type | None, Field(default=None))

    _add_extra_fields(admin, fields, required_on_create=True)

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

    for rel in _collect_relationships(registered):
        if rel.name in readonly or rel.name in fields:
            continue
        python_type = _relationship_python_type(rel)
        fields[rel.name] = (python_type | None, Field(default=None))

    _add_extra_fields(admin, fields, required_on_create=False)

    model_name = f"{registered.verbose_name.replace(' ', '')}Update"
    return create_model(model_name, __config__=None, **fields)


def build_response_schema(registered: Any) -> type[BaseModel]:
    """Build a Pydantic model for response output."""
    from fastapi_admin_kit.inspection.types import SENSITIVE_FIELDS

    columns = [c for c in registered.columns if c.name not in SENSITIVE_FIELDS]

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


def _file_field_names(registered: Any) -> set[str]:
    """Names of file/image upload fields, honoring fields/exclude config.

    Detection is widget-based (same rule as the HTML form's ``has_file_field``):
    a field is a file field when its widget is a file-upload widget, whether
    by column type (``LargeBinary``) or a ``formfield_overrides`` entry on a
    string column (the usual path-storage pattern).
    """
    from fastapi_admin_kit.views.file_handler import FILE_WIDGET_TYPES

    names: set[str] = set()
    admin = registered.admin
    for col in registered.columns:
        if col.name == "id":
            continue
        if admin.fields is not None and col.name not in admin.fields:
            continue
        if admin.exclude and col.name in admin.exclude:
            continue
        try:
            if isinstance(registered.get_widget(col.name), FILE_WIDGET_TYPES):
                names.add(col.name)
        except Exception:
            continue
    return names


def has_file_fields(registered: Any) -> bool:
    """True when the model's write schemas include file/image upload columns."""
    return bool(_file_field_names(registered))


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
