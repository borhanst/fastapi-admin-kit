"""Model inspection — SQLAlchemy model → ColumnMeta / RelationMeta."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import inspect

from fastapi_admin_kit.inspection.types import ColumnMeta, RelationMeta


def inspect_model(model: type) -> tuple[list[ColumnMeta], list[RelationMeta]]:
    """Inspect a SQLAlchemy model and return column + relationship metadata."""
    mapper = inspect(model)
    columns: list[ColumnMeta] = []
    relationships: list[RelationMeta] = []

    for col in mapper.columns:
        columns.append(
            ColumnMeta(
                name=col.key,
                type=col.type,
                nullable=col.nullable,
                primary_key=col.primary_key,
                foreign_keys=list(col.foreign_keys),
                default=col.default,
                server_default=col.server_default,
                index=col.index,
                unique=col.unique,
            )
        )

    for rel in mapper.relationships:
        relationships.append(
            RelationMeta(
                name=rel.key,
                direction=rel.direction.name,
                target_model=rel.mapper.class_,
                uselist=rel.uselist,
                back_populates=rel.back_populates,
                secondary=rel.secondary,
            )
        )

    return columns, relationships


def is_abstract(model: type) -> bool:
    """Check if a model is abstract and should be skipped during auto-discovery."""
    return getattr(model, "__abstract__", False)


def get_pk_field(model: type) -> str | None:
    """Get the primary key field name for a model.

    Returns the single PK field name for simple PKs,
    or a tuple of names for composite PKs.
    Returns None if no primary key is found.
    """
    mapper = inspect(model)
    pk_cols = mapper.primary_key
    if not pk_cols:
        return None
    if len(pk_cols) == 1:
        return pk_cols[0].key
    return tuple(col.key for col in pk_cols)


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
    Falls back to ``ClassName:pk`` when ``__str__`` is the default
    ``object.__str__``.
    """
    if type(obj).__str__ is not object.__str__:
        return str(obj)
    pk = getattr(obj, "id", None)
    return f"{type(obj).__name__}:{pk}" if pk is not None else type(obj).__name__
