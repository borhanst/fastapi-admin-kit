"""Filter ABCs — ORM-agnostic filter system for list views.

Each Filter subclass owns one field and knows how to:
1. Apply a WHERE clause via QueryBackend (never raw ORM).
2. Convert values from query-string strings to Python types.
3. Provide static choices for template rendering.

Type detection lives in FilterRegistry.auto_generate(), not here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Filter(ABC):
    """Abstract base class for list view filters."""

    field_type: str = "text"

    def __init__(self, field_name: str, label: str = "") -> None:
        self.field_name = field_name
        self.label = label or field_name.replace("_", " ").title()

    @abstractmethod
    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        """Apply the filter to a query via QueryBackend.

        Args:
            query_adapter: A QueryBackend adapter instance.
            query: The current query statement.
            model: The ORM model the query selects.
            value: The filter value — a plain string for equality
                   filters, or a dict for range filters.

        Returns:
            The updated query with the filter applied.
        """
        ...

    def get_choices(self, session: Any = None) -> list[tuple[str, str]]:
        """Return available filter choices as (value, label) pairs.

        Subclasses with static choices override this directly.
        Dynamic choices (text distinct values, relation lookups) are
        built by the pipeline, not by the filter.
        """
        return [("", "All")]


class TextFilter(Filter):
    """Simple text equality filter."""

    field_type = "text"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("eq", "")
        if not value or not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        return query_adapter.where(query, col == value)


class BooleanFilter(Filter):
    """Boolean filter — maps '1' to True, '0' to False."""

    field_type = "boolean"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("eq", "")
        if not value or not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        return query_adapter.where(query, col == (value == "1"))

    def get_choices(self, session: Any = None) -> list[tuple[str, str]]:
        return [("", "All"), ("1", "Yes"), ("0", "No")]


class RelationFilter(Filter):
    """Filter by foreign key relationship.

    The resolved FK column name is set by FilterRegistry so that
    filtering goes through the FK, not the ORM relationship object.
    """

    field_type = "relation"

    def __init__(
        self,
        field_name: str,
        label: str = "",
        resolved_column: str | None = None,
    ) -> None:
        super().__init__(field_name, label)
        self.resolved_column = resolved_column

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("eq", "")
        if not value:
            return query
        col_name = self.resolved_column or self.field_name
        if not hasattr(model, col_name):
            return query
        col = getattr(model, col_name)
        return query_adapter.where(query, col == value)


class EnumFilter(Filter):
    """Filter for enum columns."""

    field_type = "enum"

    def __init__(
        self,
        field_name: str,
        label: str = "",
        choices: list[str] | None = None,
    ) -> None:
        super().__init__(field_name, label)
        self._enum_choices = choices or []

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("eq", "")
        if not value or not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        return query_adapter.where(query, col == value)

    def get_choices(self, session: Any = None) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = [("", "All")]
        for val in self._enum_choices:
            choices.append((val, val.replace("_", " ").title()))
        return choices


class IntegerFilter(Filter):
    """Integer equality filter — converts value to int."""

    field_type = "integer"

    def __init__(
        self,
        field_name: str,
        label: str = "",
        resolved_column: str | None = None,
    ) -> None:
        super().__init__(field_name, label)
        self.resolved_column = resolved_column

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("eq", "")
        if not value:
            return query
        col_name = self.resolved_column or self.field_name
        if not hasattr(model, col_name):
            return query
        try:
            int_value = int(value)
        except (ValueError, TypeError):
            return query
        col = getattr(model, col_name)
        return query_adapter.where(query, col == int_value)


class NumericFilter(Filter):
    """Numeric range filter (gte/lte).

    Value is a dict with optional 'gte' and 'lte' keys.
    Also accepts a plain string for equality.
    """

    field_type = "numeric"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        if isinstance(value, dict):
            gte = value.get("gte", "")
            lte = value.get("lte", "")
            if gte:
                try:
                    query = query_adapter.where(query, col >= type(col.type)().coerce(gte))
                except Exception:
                    pass
            if lte:
                try:
                    query = query_adapter.where(query, col <= type(col.type)().coerce(lte))
                except Exception:
                    pass
            return query
        if value:
            try:
                query = query_adapter.where(query, col == type(col.type)().coerce(value))
            except Exception:
                pass
        return query


class DateRangeFilter(Filter):
    """Date range filter (from/to).

    Value is a dict with optional 'from' and 'to' keys.
    Also accepts a plain string for equality.
    """

    field_type = "date"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        from datetime import date

        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        if isinstance(value, dict):
            if value.get("from"):
                try:
                    d = date.fromisoformat(value["from"])
                    query = query_adapter.where(query, col >= d)
                except (ValueError, TypeError):
                    pass
            if value.get("to"):
                try:
                    d = date.fromisoformat(value["to"])
                    query = query_adapter.where(query, col <= d)
                except (ValueError, TypeError):
                    pass
            return query
        if value:
            try:
                d = date.fromisoformat(value)
                query = query_adapter.where(query, col == d)
            except (ValueError, TypeError):
                pass
        return query


class DatetimeRangeFilter(Filter):
    """Datetime range filter (from/to).

    Value is a dict with optional 'from' and 'to' keys.
    Also accepts a plain string for equality.
    """

    field_type = "datetime"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        from datetime import datetime

        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        if isinstance(value, dict):
            if value.get("from"):
                try:
                    dt = datetime.fromisoformat(value["from"])
                    query = query_adapter.where(query, col >= dt)
                except (ValueError, TypeError):
                    pass
            if value.get("to"):
                try:
                    dt = datetime.fromisoformat(value["to"])
                    query = query_adapter.where(query, col <= dt)
                except (ValueError, TypeError):
                    pass
            return query
        if value:
            try:
                dt = datetime.fromisoformat(value)
                query = query_adapter.where(query, col == dt)
            except (ValueError, TypeError):
                pass
        return query


class TimeFilter(Filter):
    """Time equality filter."""

    field_type = "time"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        from datetime import time

        if isinstance(value, dict):
            value = value.get("eq", "")
        if not value or not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        try:
            t = time.fromisoformat(value)
        except (ValueError, TypeError):
            return query
        return query_adapter.where(query, col == t)


class AutocompleteFilter(Filter):
    """Autocomplete search filter for related fields."""

    field_type = "relation"

    def __init__(
        self,
        field_name: str,
        label: str = "",
        search_fields: list[str] | None = None,
    ) -> None:
        super().__init__(field_name, label)
        self.search_fields = search_fields or ["name"]

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        if isinstance(value, dict):
            value = value.get("eq", "")
        if not value or not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        return query_adapter.where(query, col == value)
