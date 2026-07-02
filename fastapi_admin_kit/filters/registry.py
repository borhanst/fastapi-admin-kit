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
        self._filters.setdefault(model_name, {})[filter_obj.field_name] = (
            filter_obj
        )

    def get_filters(self, model_name: str) -> dict[str, Filter]:
        return self._filters.get(model_name, {}).copy()

    def auto_generate(
        self, model: Any, columns: list[Any]
    ) -> dict[str, Filter]:
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(model)
        filters: dict[str, Filter] = {}

        for col_meta in columns:
            field_name = col_meta.name
            if field_name == "id":
                continue

            rel_names = {r.key for r in mapper.relationships}
            if field_name in rel_names:
                filters[field_name] = RelationFilter(field_name)
                continue

            for prop in mapper.column_attrs:
                if prop.key != field_name:
                    continue
                col = prop.columns[0] if prop.columns else None
                if col is None:
                    break

                type_name = col.type.__class__.__name__
                if type_name == "Boolean":
                    filters[field_name] = BooleanFilter(field_name)
                elif hasattr(col.type, "enums") and col.type.enums:
                    filters[field_name] = EnumFilter(
                        field_name, choices=list(col.type.enums)
                    )
                elif col.foreign_keys:
                    filters[field_name] = RelationFilter(field_name)
                else:
                    filters[field_name] = TextFilter(field_name)
                break

        return filters
