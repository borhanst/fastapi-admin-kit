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
    def apply(self, query: Any, value: str) -> Any:
        """Apply the filter to a SQLAlchemy select query."""
        ...

    def get_choices(self, session: Any) -> list[tuple[str, str]]:
        """Return available filter choices as (value, label) pairs."""
        return []


class TextFilter(Filter):
    """Simple text equality filter."""

    def apply(self, query: Any, value: str) -> Any:
        model = query.column_descriptions[0]["entity"]
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query.where(col == value)
        return query


class BooleanFilter(Filter):
    """Boolean filter — maps '1' to True, '0' to False."""

    def apply(self, query: Any, value: str) -> Any:
        model = query.column_descriptions[0]["entity"]
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query.where(col == (value == "1"))
        return query


class RelationFilter(Filter):
    """Filter by foreign key relationship."""

    def apply(self, query: Any, value: str) -> Any:
        model = query.column_descriptions[0]["entity"]
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query.where(col == value)
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

    def apply(self, query: Any, value: str) -> Any:
        model = query.column_descriptions[0]["entity"]
        if hasattr(model, self.field_name):
            col = getattr(model, self.field_name)
            return query.where(col == value)
        return query

    def get_choices(self, session: Any) -> list[tuple[str, str]]:
        choices = [("", "All")]
        for val in self._enum_choices:
            choices.append((val, val.replace("_", " ").title()))
        return choices


class NumericFilter(Filter):
    """Numeric range filter (gte/lte)."""

    def apply(self, query: Any, value: str) -> Any:
        model = query.column_descriptions[0]["entity"]
        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        if isinstance(value, dict):
            if value.get("gte"):
                query = query.where(col >= value["gte"])
            if value.get("lte"):
                query = query.where(col <= value["lte"])
        return query


class DateRangeFilter(Filter):
    """Date range filter (from/to)."""

    def apply(self, query: Any, value: str) -> Any:
        from datetime import date

        model = query.column_descriptions[0]["entity"]
        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        if isinstance(value, dict):
            if value.get("from"):
                try:
                    d = date.fromisoformat(value["from"])
                    query = query.where(col >= d)
                except (ValueError, TypeError):
                    pass
            if value.get("to"):
                try:
                    d = date.fromisoformat(value["to"])
                    query = query.where(col <= d)
                except (ValueError, TypeError):
                    pass
        return query


class DatetimeRangeFilter(Filter):
    """Datetime range filter (from/to)."""

    def apply(self, query: Any, value: str) -> Any:
        from datetime import datetime

        model = query.column_descriptions[0]["entity"]
        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        if isinstance(value, dict):
            if value.get("from"):
                try:
                    dt = datetime.fromisoformat(value["from"])
                    query = query.where(col >= dt)
                except (ValueError, TypeError):
                    pass
            if value.get("to"):
                try:
                    dt = datetime.fromisoformat(value["to"])
                    query = query.where(col <= dt)
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

    def apply(self, query: Any, value: str) -> Any:
        model = query.column_descriptions[0]["entity"]
        if not hasattr(model, self.field_name):
            return query
        col = getattr(model, self.field_name)
        return query.where(col == value)
