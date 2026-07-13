"""Search endpoint factory for FK/M2M relation pickers.

Backward-compatible wrapper — delegates to SearchView class.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from fastapi_admin_kit.registry import RegisteredModel


def search_factory(registered: RegisteredModel):
    """Create a search handler — delegates to SearchView.html_response."""
    from fastapi_admin_kit.views.class_views import (
        SearchView,
        _resolve_view_class,
    )

    view_class = _resolve_view_class(registered.admin, "search_view_class", SearchView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"search_{registered.table_name}"
    return _handler
