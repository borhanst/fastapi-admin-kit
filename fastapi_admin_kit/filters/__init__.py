"""Filter system for list views."""

from __future__ import annotations

from fastapi_admin_kit.filters.base import (
    AutocompleteFilter,
    BooleanFilter,
    DateRangeFilter,
    DatetimeRangeFilter,
    EnumFilter,
    Filter,
    IntegerFilter,
    NumericFilter,
    RelationFilter,
    TextFilter,
    TimeFilter,
)
from fastapi_admin_kit.filters.registry import FilterRegistry

__all__ = [
    "Filter",
    "TextFilter",
    "BooleanFilter",
    "RelationFilter",
    "EnumFilter",
    "IntegerFilter",
    "NumericFilter",
    "DateRangeFilter",
    "DatetimeRangeFilter",
    "TimeFilter",
    "AutocompleteFilter",
    "FilterRegistry",
]
