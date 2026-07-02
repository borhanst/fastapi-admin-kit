"""Create and edit form handler factories.

Backward-compatible wrappers — delegate to CreateView/EditView classes.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from starlette.datastructures import UploadFile

from fastapi_admin_kit.form.pipeline import build_form_context
from fastapi_admin_kit.registry import RegisteredModel
from fastapi_admin_kit.types import PermissionSet
from fastapi_admin_kit.views.sidebar import inject_sidebar_context
from fastapi_admin_kit.widgets.inputs import FileUploadWidget, ImageUploadWidget

# Widgets that handle file uploads
_FILE_WIDGET_TYPES = (FileUploadWidget, ImageUploadWidget)


def _get_storage(request: Request):
    """Get the storage backend from app.state, or None."""
    return getattr(request.app.state, "admin_storage", None)


async def _handle_file_field(
    request: Request,
    widget: Any,
    field_meta: Any,
    form_data: Any,
    obj: Any | None,
    action: str | None,
    parsed: dict[str, Any],
    errors: dict[str, list[str]],
) -> None:
    """Handle a file upload field during form submission.

    For create: always save the new upload.
    For edit: respect the ``action`` parameter:
      - ``keep`` (default): keep existing file path unchanged
      - ``replace``: save new upload, delete old file
      - ``clear``: delete old file, set value to None
    """
    storage = _get_storage(request)
    field_name = field_meta.name
    raw = form_data.get(field_name)

    if isinstance(raw, UploadFile) and raw.filename:
        # New file uploaded
        if widget.max_size_mb is not None:
            content = await raw.read()
            max_bytes = int(widget.max_size_mb * 1024 * 1024)
            if len(content) > max_bytes:
                errors[field_name] = [
                    f"File size exceeds maximum allowed size ({widget.max_size_mb} MB)."
                ]
                # Reset file position for potential re-read
                await raw.seek(0)
                return
            # Reset file position after size check
            await raw.seek(0)

        if storage is None:
            errors[field_name] = ["No storage backend configured."]
            return

        try:
            path = await storage.save(raw, directory=field_meta.name)
        except ValueError as exc:
            errors[field_name] = [str(exc)]
            return

        # Delete old file if replacing
        if action == "replace" and obj is not None:
            old_path = getattr(obj, field_name, None)
            if old_path:
                await storage.delete(old_path)

        parsed[field_name] = path

    elif action == "clear":
        # User wants to remove the file
        if storage is not None and obj is not None:
            old_path = getattr(obj, field_name, None)
            if old_path:
                await storage.delete(old_path)
        parsed[field_name] = None

    elif action == "keep" or action is None:
        # Keep existing value
        if obj is not None:
            parsed[field_name] = getattr(obj, field_name, None)

    else:
        # No new upload, no explicit action — keep existing
        if obj is not None:
            parsed[field_name] = getattr(obj, field_name, None)


def create_form_factory(registered: RegisteredModel):
    async def create_form(request: Request, _: Any = None):
        templates = request.app.state.admin_jinja_env
        ctx = build_form_context(registered, is_create=True)
        context = await inject_sidebar_context(request, {
            "form_context": ctx,
            "is_create": True,
            "permissions": PermissionSet(
                can_view=True, can_create=True, can_edit=True, can_delete=True
            ),
        })
        return templates.TemplateResponse(
            request, "pages/form.html", context
        )
    create_form.__name__ = f"create_form_{registered.table_name}"
    return create_form


def create_submit_factory(registered: RegisteredModel):
    """Create form submission handler — delegates to CreateView.html_response."""
    from fastapi_admin_kit.views.class_views import CreateView, _resolve_view_class

    view_class = _resolve_view_class(registered.admin, "create_view_class", CreateView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"create_submit_{registered.table_name}"
    return _handler


def edit_form_factory(registered: RegisteredModel):
    """Edit form display handler — delegates to EditView.html_response."""
    from fastapi_admin_kit.views.class_views import EditView, _resolve_view_class

    view_class = _resolve_view_class(registered.admin, "edit_view_class", EditView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"edit_form_{registered.table_name}"
    return _handler


def edit_submit_factory(registered: RegisteredModel):
    """Edit form submission handler — delegates to EditView.html_response."""
    from fastapi_admin_kit.views.class_views import EditView, _resolve_view_class

    view_class = _resolve_view_class(registered.admin, "edit_view_class", EditView)
    view_instance = view_class(registered)

    async def _handler(request: Request, **kwargs: Any):
        return await view_instance.html_response(request, **kwargs)

    _handler.__name__ = f"edit_submit_{registered.table_name}"
    return _handler
