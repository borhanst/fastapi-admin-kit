"""JSON CRUD handlers for the Admin API.

Uses view classes' api_response() to eliminate duplicate logic.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from fastapi_admin_kit.api.schema_generator import get_or_build_schemas
from fastapi_admin_kit.views.class_views import (
    CreateView,
    DeleteView,
    EditView,
    ListView,
    _resolve_view_class,
)


async def _get_current_user(request: Request) -> dict[str, Any]:
    """Extract and validate the current user from a Bearer token."""
    from fastapi_admin_kit.api.deps import get_api_current_user

    return await get_api_current_user(request)


async def _check_permission(
    request: Request, user: dict[str, Any], table_name: str, action: str
) -> None:
    """Check if user has permission from JWT payload."""
    if user.get("is_superuser"):
        return

    permissions = user.get("permissions", {})
    table_perms = permissions.get(table_name, [])
    if action not in table_perms:
        raise HTTPException(
            status_code=403,
            detail=f"You do not have permission to {action} {table_name}.",
        )


def build_api_router(registry: Any) -> APIRouter:
    """Build the CRUD API router for all registered models."""
    router = APIRouter(tags=["api-crud"])

    for registered in registry.all():
        _register_model_routes(router, registered)

    return router


def _register_model_routes(router: APIRouter, registered: Any) -> None:
    """Register CRUD routes for a single model using view classes."""
    table_name = registered.table_name
    prefix = f"/{table_name}"

    # DIP: resolve view classes from ModelAdmin config
    admin = registered.admin
    list_v = _resolve_view_class(admin, "list_view_class", ListView)(registered)
    create_v = _resolve_view_class(admin, "create_view_class", CreateView)(
        registered
    )
    edit_v = _resolve_view_class(admin, "edit_view_class", EditView)(registered)
    delete_v = _resolve_view_class(admin, "delete_view_class", DeleteView)(
        registered
    )

    # Generate dynamic schemas for OpenAPI docs
    schemas = get_or_build_schemas(registered)
    response_schema = schemas["response"]
    list_response_schema = schemas["list_response"]

    @router.get(prefix, response_model=list_response_schema)
    async def list_items(
        request: Request,
        page: int = Query(1, ge=1),
        per_page: int = Query(25, ge=1, le=100),
        q: str = Query(""),
        order: str = Query(""),
        after: str | None = Query(None),
        before: str | None = Query(None),
    ):
        user = await _get_current_user(request)
        await _check_permission(request, user, table_name, "view")
        result = await list_v.api_response(
            request, page=page, per_page=per_page, q=q, order=order,
            after=after, before=before,
        )
        if isinstance(result, JSONResponse):
            return result
        return result

    @router.post(prefix, response_model=response_schema, status_code=201)
    async def create_item(request: Request):
        user = await _get_current_user(request)
        await _check_permission(request, user, table_name, "create")
        result = await create_v.api_response(request)
        if isinstance(result, JSONResponse):
            return result
        return result

    @router.get(f"{prefix}/{{item_id}}", response_model=response_schema)
    async def retrieve_item(request: Request, item_id: str):
        user = await _get_current_user(request)
        await _check_permission(request, user, table_name, "view")
        result = await edit_v.api_response(request, item_id=item_id)
        if isinstance(result, JSONResponse):
            return result
        return result

    @router.put(f"{prefix}/{{item_id}}", response_model=response_schema)
    async def update_item(request: Request, item_id: str):
        user = await _get_current_user(request)
        await _check_permission(request, user, table_name, "edit")
        result = await edit_v.api_response(request, item_id=item_id)
        if isinstance(result, JSONResponse):
            return result
        return result

    @router.delete(f"{prefix}/{{item_id}}", status_code=204)
    async def delete_item(request: Request, item_id: str):
        user = await _get_current_user(request)
        await _check_permission(request, user, table_name, "delete")
        return await delete_v.api_response(request, item_id=item_id)
