"""Django-style lookup parsing for filter query parameters.

The admin accepts filters as ``filter_<field>`` query parameters with the
same conventions as ``django-filter``::

    ?filter_name=value                     exact match
    ?filter_name__icontains=term           case-insensitive contains
    ?filter_name__startswith=Jo            starts with
    ?filter_name__endswith=hn              ends with
    ?filter_price__gt=100                  greater than
    ?filter_price__gte=100                 greater than or equal
    ?filter_price__lt=50                   less than
    ?filter_price__lte=200                 less than or equal
    ?filter_price__range=10,200            range (inclusive)
    ?filter_id__in=1,2,3                   in list

This module owns the (query params -> value) mapping so the HTML list views
and the JSON API share one source of truth.
"""

from __future__ import annotations

from typing import Any

# (lookup name, query-string suffix). The empty suffix means "exact match".
LOOKUP_SUFFIXES: tuple[tuple[str, str], ...] = (
    ("exact", ""),
    ("icontains", "__icontains"),
    ("startswith", "__startswith"),
    ("endswith", "__endswith"),
    ("gt", "__gt"),
    ("gte", "__gte"),
    ("lt", "__lt"),
    ("lte", "__lte"),
    ("range", "__range"),
    ("in", "__in"),
    ("from", "__from"),
    ("to", "__to"),
)

# Lookups grouped by the kind of condition they build.
COMPARISON_LOOKUPS = ("gt", "gte", "lt", "lte")
LIST_LOOKUPS = ("range", "in")
TEXT_LOOKUPS = ("icontains", "startswith", "endswith")


def parse_filter_params(
    query_params: Any,
    field_name: str,
) -> tuple[Any, dict[str, str]]:
    """Read filter query params for *field_name*.

    Args:
        query_params: Anything with a ``.get(key, default)`` interface
            (Starlette ``QueryParams`` or a plain dict).
        field_name: The model field being filtered.

    Returns:
        A ``(value, active_pairs)`` tuple. ``value`` is a plain string for an
        exact match or a dict keyed by lookup name (``{"icontains": "x"}``)
        when a lookup-style parameter is present. ``active_pairs`` maps the
        display key (e.g. ``"name__icontains"``) to the raw value so the admin
        UI can highlight and clear active filters.
    """
    parts: dict[str, str] = {}
    active: dict[str, str] = {}
    for lookup, suffix in LOOKUP_SUFFIXES:
        raw = query_params.get(f"filter_{field_name}{suffix}", "")
        if raw:
            parts[lookup] = raw
            active[f"{field_name}{suffix}"] = raw
    if not parts:
        return None, active
    if "exact" in parts and len(parts) == 1:
        return parts["exact"], active
    return parts, active
