"""Filter ABCs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Filter(ABC):
    """Abstract base class for list view filters."""

    def __init__(self, field_name: str, label: str = "") -> None:
        self.field_name = field_name
        self.label = label or field_name.replace("_", " ").title()

    @abstractmethod
    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
        """Apply the filter to a query via QueryBackend.

        Args:
            query_adapter: A QueryBackend adapter instance.
            query: The current query statement.
            model: The ORM model the query selects.
            value: The filter value from request query params.

        Returns:
            The updated query with the filter applied.
        """
        ...

    def get_choices(self, session: Any) -> list[tuple[str, str]]:
        """Return available filter choices as (value, label) pairs.

        Args:
            session: A SessionBackend adapter instance.
        """
        return []


class TextFilter(Filter):
    """Simple text equality filter."""

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query_adapter.where(query, col == value)
        return query


class BooleanFilter(Filter):
    """Boolean filter — maps '1' to True, '0' to False."""

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query_adapter.where(query, col == (value == "1"))
        return query


class RelationFilter(Filter):
    """Filter by foreign key relationship."""

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query_adapter.where(query, col == value)
        return query


class EnumFilter(Filter):
    """Filter for enum columns."""

    def __init__(
        self,
        field_name: str,
        label: str = "",
        choices: list[str] | None = None,
    ) -> None:
        super().__init__(field_name, label)
        self._enum_choices = choices or []

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query_adapter.where(query, col == value)
        return query

    def get_choices(self, session: Any) -> list[tuple[str, str]]:
        choices = [("", "All")]
        for val in self._enum_choices:
            choices.append((val, val.replace("_", " ").title()))
        return choices


class NumericFilter(Filter):
    """Numeric range filter (gte/lte)."""

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        if isinstance(value, dict):
            if value.get("gte"):
                query = query_adapter.where(query, col >= value["gte"])
            if value.get("lte"):
                query = query_adapter.where(query, col <= value["lte"])
        return query


class DateRangeFilter(Filter):
    """Date range filter (from/to)."""

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
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


class DatetimeRangeFilter(Filter):
    """Datetime range filter (from/to)."""

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
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


class AutocompleteFilter(Filter):
    """Autocomplete search filter for related fields."""

    def __init__(
        self,
        field_name: str,
        label: str = "",
        search_fields: list[str] | None = None,
    ) -> None:
        super().__init__(field_name, label)
        self.search_fields = search_fields or ["name"]

    def apply(self, query_adapter: Any, query: Any, model: Any, value: str) -> Any:
        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        return query_adapter.where(query, col == value)
