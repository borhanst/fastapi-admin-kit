"""Route handler factories — list, form, delete, roles, dashboard."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from fastapi_admin_kit.admin.decorators import column

if TYPE_CHECKING:
    from fastapi_admin_kit.registry import RegisteredModel


class ModelAdmin:
    """Base class for model admin configuration."""

    # List view config
    list_display: list[str] | None = None
    list_filter: list[str | Any] | None = None
    search_fields: list[str] | None = None
    ordering: list[str] | None = None
    per_page: int = 20

    # Form config
    fields: list[str] | None = None
    exclude: list[str] | None = None
    readonly_fields: list[str] | None = None

    # Labels and display
    verbose_name: str | None = None
    verbose_name_plural: str | None = None
    icon: str | None = None

    # Custom display functions (dict-based fallback)
    display_functions: dict[str, Any] | None = None

    # Decorator for custom column display
    column = staticmethod(column)

    def __str__(self, obj: Any) -> str:
        """How to display an object in dropdowns/links."""
        return str(getattr(obj, "name", None) or getattr(obj, "title", None) or f"#{obj.id}")


def create_list_view(registered: RegisteredModel) -> Any:
    """Create a list view handler for a model."""

    async def list_view(request: Request) -> HTMLResponse:
        # Placeholder — will render list template
        return HTMLResponse(
            f"<h1>{registered.verbose_name_plural}</h1><p>List view coming soon.</p>"
        )

    return list_view


def create_create_view(registered: RegisteredModel) -> Any:
    """Create a create view handler for a model."""

    async def create_view(request: Request) -> HTMLResponse:
        # Placeholder — will render form template
        return HTMLResponse(f"<h1>Create {registered.verbose_name}</h1><p>Form coming soon.</p>")

    return create_view


def create_edit_view(registered: RegisteredModel) -> Any:
    """Create an edit view handler for a model."""

    async def edit_view(request: Request, item_id: str) -> HTMLResponse:
        # Placeholder — will render form template
        return HTMLResponse(
            f"<h1>Edit {registered.verbose_name}</h1><p>Form for {item_id} coming soon.</p>"
        )

    return edit_view


def create_delete_view(registered: RegisteredModel) -> Any:
    """Create a delete view handler for a model."""

    async def delete_view(request: Request, item_id: str) -> HTMLResponse:
        # Placeholder — will handle deletion
        return HTMLResponse(
            f"<h1>Delete {registered.verbose_name}</h1><p>Delete {item_id} coming soon.</p>"
        )

    return delete_view


def create_model_router(registered: RegisteredModel) -> APIRouter:
    """Create all CRUD routes for a registered model."""
    router = APIRouter(prefix=f"/{registered.table_name}", tags=[registered.verbose_name])

    router.add_api_route("/", create_list_view(registered), methods=["GET"], name="list")
    router.add_api_route(
        "/create",
        create_create_view(registered),
        methods=["GET", "POST"],
        name="create",
    )
    router.add_api_route(
        "/{item_id}",
        create_edit_view(registered),
        methods=["GET", "POST"],
        name="edit",
    )
    router.add_api_route(
        "/{item_id}/delete",
        create_delete_view(registered),
        methods=["POST"],
        name="delete",
    )

    return router
