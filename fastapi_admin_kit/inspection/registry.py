"""ModelInspector — inspects SQLAlchemy models and extracts metadata."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy import inspect

from fastapi_admin_kit.types import ColumnMeta, RelationMeta

if TYPE_CHECKING:
    pass


class ModelInspector:
    """Inspects SQLAlchemy models and extracts column/relationship metadata.

    This class centralizes all model inspection logic, making it testable
    and separable from the registry's storage concerns.
    """

    def inspect_model(self, model: type) -> tuple[list[ColumnMeta], list[RelationMeta]]:
        """Inspect a SQLAlchemy or SQLModel model and return column + relationship metadata.

        Args:
            model: A SQLAlchemy or SQLModel declarative model class.

        Returns:
            A tuple of (columns, relationships) metadata.
        """
        mapper = inspect(model)
        columns: list[ColumnMeta] = []
        relationships: list[RelationMeta] = []

        # Check if this is a SQLModel
        is_sqlmodel = self._is_sqlmodel(model)

        for col in mapper.columns:
            # For SQLModel, we may need to extract type info from Pydantic fields
            col_type = col.type
            if is_sqlmodel:
                col_type = self._resolve_sqlmodel_type(model, col.key, col.type)

            columns.append(
                ColumnMeta(
                    name=col.key,
                    type=col_type,
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
            try:
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
            except Exception:
                # Skip relationships that fail to configure (e.g. SQLModel
                # relationships with incomplete FK resolution)
                pass

        return columns, relationships

    def _is_sqlmodel(self, model: type) -> bool:
        """Check if a model is a SQLModel instance."""
        try:
            from sqlmodel import SQLModel

            return isinstance(model, type) and issubclass(model, SQLModel)
        except ImportError:
            return False

    def _resolve_sqlmodel_type(self, model: type, field_name: str, default_type: Any) -> Any:
        """Resolve the column type for a SQLModel field.

        SQLModel may expose Python types (int, str, etc.) instead of SQLAlchemy types.
        This method maps them to equivalent SQLAlchemy types.
        """
        try:
            from sqlmodel import SQLModel

            if not (isinstance(model, type) and issubclass(model, SQLModel)):
                return default_type

            # Get SQLModel field info
            sqlmodel_fields = getattr(model, "__sqlmodel_fields__", {})
            if field_name not in sqlmodel_fields:
                return default_type

            field_info = sqlmodel_fields[field_name]
            annotation = getattr(field_info, "annotation", None)

            if annotation is None:
                return default_type

            # Map Python types to SQLAlchemy types
            type_map = {
                int: self._get_sa_type("Integer"),
                str: self._get_sa_type("String"),
                float: self._get_sa_type("Float"),
                bool: self._get_sa_type("Boolean"),
            }

            # Handle Optional types
            origin = getattr(annotation, "__origin__", None)
            if origin is not None:
                args = getattr(annotation, "__args__", ())
                if args:
                    inner = args[0]
                    if inner in type_map:
                        return type_map[inner]

            if annotation in type_map:
                return type_map[annotation]

            return default_type
        except Exception:
            return default_type

    def _get_sa_type(self, type_name: str) -> Any:
        """Get a SQLAlchemy type by name."""
        import sqlalchemy as sa

        return getattr(sa, type_name, None)

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
        return getattr(model, "__abstract__", False)

    def get_pk_field(self, model: type) -> str | tuple[str, ...] | None:
        """Get the primary key field name for a model.

        Args:
            model: A SQLAlchemy declarative model class.

        Returns:
            The single PK field name for simple PKs,
            a tuple of names for composite PKs,
            or None if no primary key is found.
        """
        mapper = inspect(model)
        pk_cols = mapper.primary_key
        if not pk_cols:
            return None
        if len(pk_cols) == 1:
            return pk_cols[0].key
        return tuple(col.key for col in pk_cols)

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
