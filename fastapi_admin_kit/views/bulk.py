"""Bulk action handler factory for registered models.

Backward-compatible wrapper — delegates to BulkView class.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from fastapi_admin_kit.registry import RegisteredModel


def bulk_factory(registered: RegisteredModel):
    """Create a bulk action handler — delegates to BulkView.html_response."""
    from fastapi_admin_kit.views.class_views import BulkView, _resolve_view_class

    view_class = _resolve_view_class(registered.admin, "bulk_view_class", BulkView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"bulk_{registered.table_name}"
    return _handler
