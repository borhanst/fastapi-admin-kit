"""Filter ABCs — ORM-agnostic filter system for list views.

Each Filter subclass owns one field and knows how to:
1. Apply a WHERE clause via QueryBackend (never raw ORM).
2. Convert values from query-string strings to Python types.
3. Provide static choices for template rendering.

Values follow the Django ``field__lookup`` convention. They arrive as a
plain string for exact matches or a dict keyed by lookup name (``icontains``,
``startswith``, ``endswith``, ``gt``, ``gte``, ``lt``, ``lte``, ``range``,
``in``, ``from``, ``to``). See :mod:`fastapi_admin_kit.filters.lookups`.

Type detection lives in FilterRegistry.auto_generate(), not here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from fastapi_admin_kit.filters.lookups import COMPARISON_LOOKUPS, TEXT_LOOKUPS


def _split_csv(value: str) -> list[str]:
    """Split a comma-separated list value, ignoring empty segments."""
    return [part.strip() for part in value.split(",") if part.strip()]


class Filter(ABC):
    """Abstract base class for list view filters."""

    field_type: str = "text"

    def __init__(self, field_name: str, label: str = "") -> None:
        self.field_name = field_name
        self.label = label or field_name.replace("_", " ").title()

    @abstractmethod
    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        """Build a WHERE clause for this filter.

        Args:
            query_adapter: A QueryBackend adapter instance (may be None).
            query: The current query statement (may be None when collecting clauses).
            model: The ORM model the query selects.
            value: A plain string for an exact match, or a dict keyed by
                lookup name for Django-style lookups.

        Returns:
            A boolean clause (SQLAlchemy BinaryExpression, MemExpr, ...) or
            None to skip the filter.
        """
        ...

    def get_choices(self, session: Any = None) -> list[tuple[str, str]]:
        """Return available filter choices as (value, label) pairs.

        Subclasses with static choices override this directly.
        Dynamic choices (text distinct values, relation lookups) are
        built by the pipeline, not by the filter.
        """
        return [("", "All")]

    # ------------------------------------------------------------------
    # Shared helpers — kept backend-agnostic
    # ------------------------------------------------------------------

    @staticmethod
    def _column(model: Any, field_name: str) -> Any | None:
        """Return the model column descriptor or None if absent."""
        if not hasattr(model, field_name):
            return None
        return getattr(model, field_name)

    @staticmethod
    def _coerce(value: str, converter: Callable[[str], Any]) -> Any | None:
        """Convert a query-string value, returning None on parse failure."""
        try:
            return converter(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _combine(conditions: list, query_adapter: Any = None) -> Any | None:
        """Combine zero or more conditions into a single AND clause."""
        if not conditions:
            return None
        if len(conditions) == 1:
            return conditions[0]
        if query_adapter is not None and hasattr(query_adapter, "and_"):
            return query_adapter.and_(*conditions)
        from sqlalchemy import and_

        return and_(*conditions)

    def _comparison_lookups(
        self,
        col: Any,
        value: dict[str, str],
        converter: Callable[[str], Any] | None = None,
        query_adapter: Any = None,
    ) -> list:
        """Build gt/gte/lt/lte/range/in conditions from a lookup dict."""
        conditions: list = []

        ops = {
            "gt": col.__gt__,
            "gte": col.__ge__,
            "lt": col.__lt__,
            "lte": col.__le__,
        }
        for lookup in COMPARISON_LOOKUPS:
            raw = value.get(lookup)
            if not raw:
                continue
            converted = self._coerce(raw, converter) if converter else raw
            if converted is not None:
                conditions.append(ops[lookup](converted))

        raw_range = value.get("range")
        if raw_range:
            parts = _split_csv(raw_range)
            if len(parts) == 2:
                lo = self._coerce(parts[0], converter) if converter else parts[0]
                hi = self._coerce(parts[1], converter) if converter else parts[1]
                if lo is not None and hi is not None:
                    conditions.append(col >= lo)
                    conditions.append(col <= hi)

        raw_in = value.get("in")
        if raw_in:
            items: list = []
            for part in _split_csv(raw_in):
                converted = self._coerce(part, converter) if converter else part
                if converted is not None:
                    items.append(converted)
            if items:
                conditions.append(col.in_(items))

        return conditions


class TextFilter(Filter):
    """Text filter — exact match plus icontains/startswith/endswith lookups."""

    field_type = "text"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        col = self._column(model, self.field_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                conditions.append(col == exact)

            patterns = {
                "icontains": lambda v: f"%{v}%",
                "startswith": lambda v: f"{v}%",
                "endswith": lambda v: f"%{v}",
            }
            for lookup in TEXT_LOOKUPS:
                raw = value.get(lookup)
                if not raw:
                    continue
                if query_adapter is not None:
                    conditions.append(query_adapter.ilike(col, patterns[lookup](raw)))
                else:
                    conditions.append(col.ilike(patterns[lookup](raw)))

            return self._combine(conditions, query_adapter)

        if value:
            return col == value
        return None


class ChoiceFilter(Filter):
    """Choice filter for relation/foreign-key/enum fields rendered as a select.

    Supports exact match and ``in`` list lookups. When no static choices are
    provided the list-view pipeline builds dynamic choices (distinct values or
    related rows) via :meth:`get_choices`.
    """

    field_type = "relation"

    def __init__(
        self,
        field_name: str,
        label: str = "",
        resolved_column: str | None = None,
        choices: list[str] | None = None,
    ) -> None:
        super().__init__(field_name, label)
        self.resolved_column = resolved_column
        self._choices = list(choices or [])

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        col_name = self.resolved_column or self.field_name
        col = self._column(model, col_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                conditions.append(col == exact)
            raw_in = value.get("in")
            if raw_in:
                items = _split_csv(raw_in)
                if items:
                    conditions.append(col.in_(items))
            return self._combine(conditions, query_adapter)

        if value:
            return col == value
        return None

    def get_choices(self, session: Any = None) -> list[tuple[str, str]]:
        if not self._choices:
            return [("", "All")]
        choices: list[tuple[str, str]] = [("", "All")]
        for val in self._choices:
            label = val.replace("_", " ").title() if isinstance(val, str) else str(val)
            choices.append((str(val), label))
        return choices


class RelationFilter(ChoiceFilter):
    """Filter by foreign key relationship (backwards-compatible alias).

    The resolved FK column name is set by FilterRegistry so filtering goes
    through the FK, not the ORM relationship object.
    """

    field_type = "relation"

    def __init__(
        self,
        field_name: str,
        label: str = "",
        resolved_column: str | None = None,
    ) -> None:
        super().__init__(field_name, label, resolved_column=resolved_column)


class BooleanFilter(Filter):
    """Boolean filter — maps '1'/'true' to True, '0'/'false' to False."""

    field_type = "boolean"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        col = self._column(model, self.field_name)
        if col is None:
            return None

        raw = value.get("exact") if isinstance(value, dict) else value
        if not raw:
            return None
        if raw.lower() in ("1", "true", "yes"):
            return col == True  # noqa: E712
        if raw.lower() in ("0", "false", "no"):
            return col == False  # noqa: E712
        return None

    def get_choices(self, session: Any = None) -> list[tuple[str, str]]:
        return [("", "All"), ("1", "Yes"), ("0", "No")]


class EnumFilter(Filter):
    """Filter for enum columns with static choices."""

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
        col = self._column(model, self.field_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                conditions.append(col == exact)
            raw_in = value.get("in")
            if raw_in:
                items = _split_csv(raw_in)
                if items:
                    conditions.append(col.in_(items))
            return self._combine(conditions, query_adapter)

        if value:
            return col == value
        return None

    def get_choices(self, session: Any = None) -> list[tuple[str, str]]:
        choices: list[tuple[str, str]] = [("", "All")]
        for val in self._enum_choices:
            choices.append((val, val.replace("_", " ").title()))
        return choices


class IntegerFilter(Filter):
    """Integer filter — exact plus gt/gte/lt/lte/range/in lookups."""

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
        col_name = self.resolved_column or self.field_name
        col = self._column(model, col_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                converted = self._coerce(exact, int)
                if converted is not None:
                    conditions.append(col == converted)
            conditions.extend(self._comparison_lookups(col, value, int, query_adapter))
            return self._combine(conditions, query_adapter)

        if value:
            converted = self._coerce(value, int)
            if converted is None:
                return None
            return col == converted
        return None


class NumericFilter(Filter):
    """Numeric range filter — exact plus gt/gte/lt/lte/range/in lookups."""

    field_type = "numeric"

    @staticmethod
    def _to_number(value: str) -> float | None:
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        col = self._column(model, self.field_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                converted = self._to_number(exact)
                if converted is not None:
                    conditions.append(col == converted)
            conditions.extend(self._comparison_lookups(col, value, self._to_number, query_adapter))
            return self._combine(conditions, query_adapter)

        if value:
            converted = self._to_number(value)
            if converted is None:
                return None
            return col == converted
        return None


class DateRangeFilter(Filter):
    """Date range filter — exact plus gt/gte/lt/lte/range/in/from/to lookups."""

    field_type = "date"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        from datetime import date

        col = self._column(model, self.field_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                converted = self._coerce(exact, date.fromisoformat)
                if converted is not None:
                    conditions.append(col == converted)
            conditions.extend(
                self._comparison_lookups(col, value, date.fromisoformat, query_adapter)
            )
            from_ = value.get("from", "")
            to_ = value.get("to", "")
            if from_:
                d = self._coerce(from_, date.fromisoformat)
                if d is not None:
                    conditions.append(col >= d)
            if to_:
                d = self._coerce(to_, date.fromisoformat)
                if d is not None:
                    conditions.append(col <= d)
            return self._combine(conditions, query_adapter)

        if value:
            converted = self._coerce(value, date.fromisoformat)
            if converted is None:
                return None
            return col == converted
        return None


class DatetimeRangeFilter(Filter):
    """Datetime range filter — exact plus gt/gte/lt/lte/range/in/from/to lookups."""

    field_type = "datetime"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        from datetime import datetime

        col = self._column(model, self.field_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                converted = self._coerce(exact, datetime.fromisoformat)
                if converted is not None:
                    conditions.append(col == converted)
            conditions.extend(
                self._comparison_lookups(col, value, datetime.fromisoformat, query_adapter)
            )
            from_ = value.get("from", "")
            to_ = value.get("to", "")
            if from_:
                dt = self._coerce(from_, datetime.fromisoformat)
                if dt is not None:
                    conditions.append(col >= dt)
            if to_:
                dt = self._coerce(to_, datetime.fromisoformat)
                if dt is not None:
                    conditions.append(col <= dt)
            return self._combine(conditions, query_adapter)

        if value:
            converted = self._coerce(value, datetime.fromisoformat)
            if converted is None:
                return None
            return col == converted
        return None


class TimeFilter(Filter):
    """Time filter — exact plus gt/gte/lt/lte/range/in lookups."""

    field_type = "time"

    def apply(self, query_adapter: Any, query: Any, model: Any, value: Any) -> Any:
        from datetime import time

        col = self._column(model, self.field_name)
        if col is None:
            return None

        if isinstance(value, dict):
            conditions: list = []
            exact = value.get("exact", "")
            if exact:
                converted = self._coerce(exact, time.fromisoformat)
                if converted is not None:
                    conditions.append(col == converted)
            conditions.extend(
                self._comparison_lookups(col, value, time.fromisoformat, query_adapter)
            )
            return self._combine(conditions, query_adapter)

        if value:
            converted = self._coerce(value, time.fromisoformat)
            if converted is None:
                return None
            return col == converted
        return None


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
        col = self._column(model, self.field_name)
        if col is None:
            return None
        raw = value.get("exact") if isinstance(value, dict) else value
        if raw:
            return col == raw
        return None
