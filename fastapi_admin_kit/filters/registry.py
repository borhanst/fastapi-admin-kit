"""Filter registry."""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.filters.base import (
    BooleanFilter,
    EnumFilter,
    Filter,
    RelationFilter,
    TextFilter,
)


class FilterRegistry:
    """Registry for custom filters per model."""

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
                filters[field_name] = RelationFilter(field_name)
                continue

            if introspection is not None:
                type_name = introspection.get_column_type_name(model, field_name)
                col = introspection.get_column_attr(model, field_name)
            else:
                from sqlalchemy import inspect as sa_inspect

                mapper = sa_inspect(model)
                type_name = None
                col = None
                for prop in mapper.column_attrs:
                    if prop.key == field_name:
                        col = prop.columns[0] if prop.columns else None
                        if col is not None:
                            type_name = col.type.__class__.__name__
                        break

            if type_name == "Boolean":
                filters[field_name] = BooleanFilter(field_name)
            elif col is not None and hasattr(col.type, "enums") and col.type.enums:
                filters[field_name] = EnumFilter(field_name, choices=list(col.type.enums))
            elif col is not None and col.foreign_keys:
                filters[field_name] = RelationFilter(field_name)
            else:
                filters[field_name] = TextFilter(field_name)

        return filters
