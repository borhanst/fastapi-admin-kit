"""ModelInspector — inspects SQLAlchemy models and extracts metadata."""

from __future__ import annotations

import re
from typing import Any

from fastapi_admin_kit.inspection.types import ColumnMeta, RelationMeta


class ModelInspector:
    """Inspects SQLAlchemy models and extracts column/relationship metadata.

    Delegates core inspection to an :class:`IntrospectionBackend` adapter
    and adds validation / metadata-extraction helpers on top.

    When no adapter is provided, falls back to ``SqlAlchemyIntrospectionAdapter``.
    """

    def __init__(self, adapter: Any = None) -> None:
        if adapter is not None:
            self._adapter = adapter
        else:
            from fastapi_admin_kit.backends.sqlalchemy import (
                SqlAlchemyIntrospectionAdapter,
            )

            self._adapter = SqlAlchemyIntrospectionAdapter()

    def inspect_model(self, model: type) -> tuple[list[ColumnMeta], list[RelationMeta]]:
        """Inspect a SQLAlchemy or SQLModel model and return column + relationship metadata.

        Args:
            model: A SQLAlchemy or SQLModel declarative model class.

        Returns:
            A tuple of (columns, relationships) metadata.
        """
        return self._adapter.inspect_model(model)

    def validate_model(self, model: type) -> None:
        """Validate that a model is suitable for admin registration.

        Args:
            model: A SQLAlchemy declarative model class.

        Raises:
            ValueError: If the model is not a valid SQLAlchemy model.
        """
        if not hasattr(model, "__tablename__"):
            raise ValueError(f"{model.__name__} is not a SQLAlchemy model (no __tablename__)")

    def extract_metadata(
        self,
        model: type,
        columns: list[ColumnMeta],
        relationships: list[RelationMeta],
    ) -> dict[str, Any]:
        """Extract additional metadata from a model.

        Args:
            model: A SQLAlchemy declarative model class.
            columns: The extracted column metadata.
            relationships: The extracted relationship metadata.

        Returns:
            A dictionary of extracted metadata.
        """
        pk_field = self.get_pk_field(model)
        table_name = model.__tablename__

        return {
            "table_name": table_name,
            "pk_field": pk_field,
            "columns": columns,
            "relationships": relationships,
        }

    def is_abstract(self, model: type) -> bool:
        """Check if a model is abstract and should be skipped during auto-discovery.

        Args:
            model: A SQLAlchemy declarative model class.

        Returns:
            True if the model is abstract, False otherwise.
        """
        return self._adapter.is_abstract(model)

    def get_pk_field(self, model: type) -> str | tuple[str, ...] | None:
        """Get the primary key field name for a model.

        Args:
            model: A SQLAlchemy declarative model class.

        Returns:
            The single PK field name for simple PKs,
            a tuple of names for composite PKs,
            or None if no primary key is found.
        """
        return self._adapter.get_pk_field(model)

    def auto_label(self, name: str) -> str:
        """Auto-generate a human-readable label from a field name.

        Args:
            name: The field name to convert.

        Returns:
            A human-readable label.

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

    def is_required(self, col: ColumnMeta) -> bool:
        """Determine if a column is required (NOT NULL with no default).

        A column is required if:
        - It is NOT NULL
        - It has no Python default
        - It has no server_default (DB-side default)
        - It is NOT a primary key (PKs are handled separately)

        Args:
            col: The column metadata to check.

        Returns:
            True if the column is required, False otherwise.
        """
        return (
            not col.nullable
            and col.default is None
            and col.server_default is None
            and not col.primary_key
        )
