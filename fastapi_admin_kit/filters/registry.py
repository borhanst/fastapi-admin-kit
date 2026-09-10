"""Filter registry — auto-generates Filter instances per model.

ORM-agnostic: type detection goes through IntrospectionBackend.
The registry maps field_name → Filter for each registered model.
"""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.filters.base import (
    BooleanFilter,
    ChoiceFilter,
    DateRangeFilter,
    DatetimeRangeFilter,
    EnumFilter,
    Filter,
    NumericFilter,
    TextFilter,
    TimeFilter,
)

# Lowercased ORM type names — covers both SQLAlchemy class names
# ("Integer", "DECIMAL") and schema backend names ("integer", "float").
_NUMERIC_TYPE_NAMES = frozenset(
    {
        "integer",
        "bigint",
        "biginteger",
        "smallinteger",
        "float",
        "double",
        "real",
        "numeric",
        "decimal",
    }
)
_BOOLEAN_TYPE_NAMES = frozenset({"boolean", "bool"})
_DATETIME_TYPE_NAMES = frozenset({"datetime", "timestamp"})
_DATE_TYPE_NAMES = frozenset({"date"})
_TIME_TYPE_NAMES = frozenset({"time"})


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

        Type detection follows Django conventions:

        - FK/ManyToMany fields → ``ChoiceFilter``
        - Boolean columns → ``BooleanFilter``
        - DateTime → ``DatetimeRangeFilter``
        - Date → ``DateRangeFilter``
        - Time → ``TimeFilter``
        - Numeric types → ``NumericFilter``
        - Enum columns → ``EnumFilter``
        - Otherwise → ``TextFilter``

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
                filters[field_name] = self._relationship_filter(model, field_name, introspection)
                continue

            type_name = self._get_type_name(model, field_name, introspection)
            type_name = (type_name or "").lower()
            col = self._get_column(model, field_name, introspection)
            has_enums = (
                col is not None
                and hasattr(col, "type")
                and hasattr(col.type, "enums")
                and bool(col.type.enums)
            )
            has_fk = col is not None and hasattr(col, "foreign_keys") and bool(col.foreign_keys)

            if type_name in _BOOLEAN_TYPE_NAMES:
                filters[field_name] = BooleanFilter(field_name)
            elif type_name in _DATETIME_TYPE_NAMES:
                filters[field_name] = DatetimeRangeFilter(field_name)
            elif type_name in _DATE_TYPE_NAMES:
                filters[field_name] = DateRangeFilter(field_name)
            elif type_name in _TIME_TYPE_NAMES:
                filters[field_name] = TimeFilter(field_name)
            elif has_fk:
                resolved_col = self._resolve_fk_column(model, field_name, introspection)
                filters[field_name] = ChoiceFilter(field_name, resolved_column=resolved_col)
            elif type_name in _NUMERIC_TYPE_NAMES:
                filters[field_name] = NumericFilter(field_name)
            elif has_enums:
                filters[field_name] = EnumFilter(field_name, choices=list(col.type.enums))
            else:
                filters[field_name] = TextFilter(field_name)

        for rel_name in rel_names:
            if rel_name not in filters:
                filters[rel_name] = self._relationship_filter(model, rel_name, introspection)

        return filters

    # ------------------------------------------------------------------
    # Internal helpers — all go through IntrospectionBackend when available
    # ------------------------------------------------------------------

    @classmethod
    def _relationship_filter(
        cls,
        model: Any,
        rel_name: str,
        introspection: Any | None,
    ) -> ChoiceFilter:
        """Build a filter for a relationship, discovered via the backend.

        MANYTOONE relationships filter the local FK column. M2M / ONETOMANY
        relationships have no local FK — filtering uses related-object
        membership (``rel.any(target.pk == value)``). Falls back to a plain
        ``ChoiceFilter`` when the target cannot be resolved (e.g. memory
        backend, where relation filters aren't supported).
        """
        meta = cls._get_relationship_meta(model, rel_name, introspection)
        direction = meta.direction if meta is not None else None
        resolved_col = cls._resolve_fk_column(model, rel_name, introspection)

        if direction != "MANYTOONE":
            target = meta.target_model if meta is not None else None
            target_pk = (
                cls._resolve_pk_column(target, introspection)
                if target is not None
                else None
            )
            if target is not None and target_pk is not None:
                return ChoiceFilter(
                    rel_name,
                    relationship_name=rel_name,
                    target_model=target,
                    target_pk=target_pk,
                )
        return ChoiceFilter(rel_name, resolved_column=resolved_col)

    @staticmethod
    def _get_relationship_meta(
        model: Any,
        rel_name: str,
        introspection: Any | None,
    ) -> Any | None:
        """Return ORM-agnostic relationship metadata, or None."""
        if introspection is not None:
            try:
                return introspection.get_relationship_meta(model, rel_name)
            except Exception:
                return None
        try:
            from sqlalchemy import inspect as sa_inspect

            from fastapi_admin_kit.inspection.types import RelationMeta

            rel = sa_inspect(model).relationships.get(rel_name)
            if rel is None:
                return None
            return RelationMeta(
                name=rel.key,
                direction=rel.direction.name,
                target_model=rel.mapper.class_,
                uselist=rel.uselist,
                back_populates=rel.back_populates,
                secondary=rel.secondary,
            )
        except Exception:
            return None

    @staticmethod
    def _resolve_pk_column(model: Any, introspection: Any | None) -> str | None:
        """Return the single primary-key column name for *model*, or None."""
        if introspection is not None:
            try:
                cols = introspection.get_pk_columns(model)
                if cols:
                    col = cols[0]
                    return getattr(col, "key", col)
            except Exception:
                pass
        try:
            from sqlalchemy import inspect as sa_inspect

            mapper = sa_inspect(model)
            if mapper.primary_key:
                return mapper.primary_key[0].key
        except Exception:
            pass
        return None

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

        mapper = sa_inspect(model)
        for prop in mapper.column_attrs:
            if prop.key == field_name:
                col = prop.columns[0] if prop.columns else None
                if col is not None:
                    for fk in col.foreign_keys:
                        return fk.column.key
        rel = mapper.relationships.get(field_name)
        if rel is not None:
            local_cols = list(getattr(rel, "local_columns", ()))
            if not local_cols:
                prop = getattr(rel, "property", None)
                local_cols = list(getattr(prop, "local_columns", ()))
            if local_cols:
                return local_cols[0].key
        return None
