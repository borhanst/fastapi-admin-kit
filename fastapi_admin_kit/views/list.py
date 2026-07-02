"""List view handler factory for registered models.

Backward-compatible wrapper — delegates to ListView class.
"""

from __future__ import annotations

from typing import Any

from fastapi_admin_kit.registry import RegisteredModel


def list_view_factory(registered: RegisteredModel):
    """Create a list view handler — delegates to ListView.html_response."""
    from fastapi_admin_kit.views.class_views import ListView, _resolve_view_class

    view_class = _resolve_view_class(registered.admin, "list_view_class", ListView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"list_{registered.table_name}"
    return _handler


# Need Request for type annotation in the wrapper
from fastapi import Request  # noqa: E402
