"""Filter registry — auto-generates Filter instances per model.

ORM-agnostic: type detection goes through IntrospectionBackend.
The registry maps field_name → Filter for each registered model.
"""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.filters.base import (
    BooleanFilter,
    DateRangeFilter,
    DatetimeRangeFilter,
    EnumFilter,
    Filter,
    NumericFilter,
    RelationFilter,
    TextFilter,
    TimeFilter,
)

_NUMERIC_TYPE_NAMES = frozenset(
    {"Integer", "BigInteger", "SmallInteger", "Float", "Numeric", "DECIMAL"}
)


class FilterRegistry:
    """Registry for custom filters per model.

    Call ``auto_generate()`` once per model to build the default
    filter set, then override individual fields via ``register()``.
    """

    def __init__(self) -> None:
        self._filters: dict[str, dict[str, Filter]] = {}

    def register(self, model_name: str, filter_obj: Filter) -> None:
        self._filters.setdefault(model_name, {})[filter_obj.field_name] = filter_obj

    def get_filters(self, model_name: str) -> dict[str, Filter]:
        return self._filters.get(model_name, {}).copy()

    def auto_generate(
        self,
        model: Any,
        columns: list[Any],
        introspection: Any | None = None,
    ) -> dict[str, Filter]:
        """Auto-generate filters for a model's columns.

        Args:
            model: The ORM model.
            columns: List of ColumnMeta for the model.
            introspection: Optional IntrospectionBackend adapter. When None,
                falls back to direct SQLAlchemy inspection.
        """
        if introspection is not None:
            rel_names = introspection.get_relationship_names(model)
        else:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(model)
            rel_names = {r.key for r in mapper.relationships}

        filters: dict[str, Filter] = {}

        for col_meta in columns:
            field_name = col_meta.name
            if field_name == "id":
                continue

            if field_name in rel_names:
                resolved_col = self._resolve_fk_column(model, field_name, introspection)
                filters[field_name] = RelationFilter(field_name, resolved_column=resolved_col)
                continue

            type_name = self._get_type_name(model, field_name, introspection)
            col = self._get_column(model, field_name, introspection)
            has_enums = col is not None and hasattr(col.type, "enums") and bool(col.type.enums)
            has_fk = col is not None and bool(col.foreign_keys)

            if type_name == "Boolean":
                filters[field_name] = BooleanFilter(field_name)
            elif type_name == "DateTime":
                filters[field_name] = DatetimeRangeFilter(field_name)
            elif type_name == "Date":
                filters[field_name] = DateRangeFilter(field_name)
            elif type_name == "Time":
                filters[field_name] = TimeFilter(field_name)
            elif type_name in _NUMERIC_TYPE_NAMES:
                filters[field_name] = NumericFilter(field_name)
            elif has_enums:
                filters[field_name] = EnumFilter(field_name, choices=list(col.type.enums))
            elif has_fk:
                resolved_col = self._resolve_fk_column(model, field_name, introspection)
                filters[field_name] = RelationFilter(field_name, resolved_column=resolved_col)
            else:
                filters[field_name] = TextFilter(field_name)

        return filters

    # ------------------------------------------------------------------
    # Internal helpers — all go through IntrospectionBackend when available
    # ------------------------------------------------------------------

    @staticmethod
    def _get_type_name(model: Any, field_name: str, introspection: Any | None) -> str | None:
        """Return the ORM type class name for a column, or None."""
        if introspection is not None:
            return introspection.get_column_type_name(model, field_name)
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(model)
        for prop in mapper.column_attrs:
            if prop.key == field_name:
                col = prop.columns[0] if prop.columns else None
                return col.type.__class__.__name__ if col is not None else None
        return None

    @staticmethod
    def _get_column(model: Any, field_name: str, introspection: Any | None) -> Any:
        """Return the raw column attribute, or None."""
        if introspection is not None:
            return introspection.get_column_attr(model, field_name)
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(model)
        for prop in mapper.column_attrs:
            if prop.key == field_name:
                return prop.columns[0] if prop.columns else None
        return None

    @staticmethod
    def _resolve_fk_column(model: Any, field_name: str, introspection: Any | None) -> str | None:
        """Resolve a relationship/FK field to its local FK column name.

        Returns the column key string, or None if resolution fails.
        """
        if introspection is not None:
            local_cols = introspection.get_relationship_local_columns(model, field_name)
            return local_cols[0] if local_cols else None
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.orm import RelationshipProperty

        mapper = sa_inspect(model)
        for prop in mapper.column_attrs:
            if prop.key == field_name:
                col = prop.columns[0] if prop.columns else None
                if col is not None:
                    for fk in col.foreign_keys:
                        return fk.column.key
        rel = mapper.relationships.get(field_name)
        if rel is not None and isinstance(rel.property, RelationshipProperty):
            local_cols = list(rel.local_columns)
            if local_cols:
                return local_cols[0].key
        return None
