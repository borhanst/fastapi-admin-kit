"""Create and edit form handler factories.

Backward-compatible wrappers — delegate to CreateView/EditView classes.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request

from fastapi_admin_kit.auth.types import PermissionSet
from fastapi_admin_kit.form.pipeline import build_form_context
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.views.sidebar import inject_sidebar_context


def create_form_factory(registered: RegisteredModel):
    async def create_form(request: Request, _: Any = None):
        templates = request.app.state.admin_jinja_env
        ctx = build_form_context(registered, is_create=True)
        context = await inject_sidebar_context(
            request,
            {
                "form_context": ctx,
                "is_create": True,
                "permissions": PermissionSet(
                    can_view=True,
                    can_create=True,
                    can_edit=True,
                    can_delete=True,
                ),
            },
        )
        return templates.TemplateResponse(request, "pages/form.html", context)

    create_form.__name__ = f"create_form_{registered.table_name}"
    return create_form


def create_submit_factory(registered: RegisteredModel):
    """Create form submission handler — delegates to CreateView.html_response."""
    from fastapi_admin_kit.views.class_views import (
        CreateView,
        _resolve_view_class,
    )

    view_class = _resolve_view_class(registered.admin, "create_view_class", CreateView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"create_submit_{registered.table_name}"
    return _handler


def edit_form_factory(registered: RegisteredModel):
    """Edit form display handler — delegates to EditView.html_response."""
    from fastapi_admin_kit.views.class_views import (
        EditView,
        _resolve_view_class,
    )

    view_class = _resolve_view_class(registered.admin, "edit_view_class", EditView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"edit_form_{registered.table_name}"
    return _handler


def edit_submit_factory(registered: RegisteredModel):
    """Edit form submission handler — delegates to EditView.html_response."""
    from fastapi_admin_kit.views.class_views import (
        EditView,
        _resolve_view_class,
    )

    view_class = _resolve_view_class(registered.admin, "edit_view_class", EditView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"edit_submit_{registered.table_name}"
    return _handler
