"""JSON CRUD handlers for the Admin API.

Uses view classes' api_response() to eliminate duplicate logic.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel

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
        # Respect skip_auto_routes (set for internal/built-in tables and any
        # model that opts out of auto routes) so internal tables like
        # admin_refresh_tokens / admin_user_totp are never exposed over JSON API.
        if getattr(registered.admin, "skip_auto_routes", False):
            continue
        _register_model_routes(router, registered)

    return router


def _wrap_body_handler(handler: Any, payload_schema: type[BaseModel]) -> Any:
    """Wrap a view handler so FastAPI can document the request body.

    The view handlers parse the JSON body themselves, so we accept the
    generated Pydantic schema as a body parameter and stash the parsed dict
    on ``request.state`` for ``JSONBodyParser`` to pick up.
    """
    payload_type = Annotated[payload_schema, Body(...)]

    async def wrapped(request: Request, payload: payload_type) -> Any:
        request.state._api_payload = payload.model_dump(exclude_unset=True)
        return await handler(request)

    # Bypass lazy annotation resolution so FastAPI sees the concrete schema.
    wrapped.__annotations__ = {
        "request": Request,
        "payload": payload_type,
        "return": Any,
    }
    wrapped.__name__ = getattr(handler, "__name__", "api_response")
    wrapped.__doc__ = getattr(handler, "__doc__", None)
    return wrapped


def _register_model_routes(router: APIRouter, registered: Any) -> None:
    """Register CRUD routes for a single model using view classes."""
    table_name = registered.table_name
    prefix = f"/{table_name}"

    # DIP: resolve view classes from ModelAdmin config
    admin = registered.admin
    list_v = _resolve_view_class(admin, "list_view_class", ListView)(registered)
    create_v = _resolve_view_class(admin, "create_view_class", CreateView)(registered)
    edit_v = _resolve_view_class(admin, "edit_view_class", EditView)(registered)
    delete_v = _resolve_view_class(admin, "delete_view_class", DeleteView)(registered)

    # Generate dynamic schemas for OpenAPI docs
    schemas = get_or_build_schemas(registered)
    response_schema = schemas["response"]
    list_response_schema = schemas["list_response"]
    create_schema = schemas["create"]
    update_schema = schemas["update"]

    # Add routes with both "api-crud" and model verbose_name tags
    router.add_api_route(
        prefix,
        list_v.api_response if hasattr(list_v, "api_response") else list_v,
        methods=["GET"],
        response_model=list_response_schema,
        tags=["api-crud", registered.verbose_name],
    )
    router.add_api_route(
        prefix,
        _wrap_body_handler(create_v.api_response, create_schema),
        methods=["POST"],
        response_model=response_schema,
        status_code=201,
        tags=["api-crud", registered.verbose_name],
    )
    router.add_api_route(
        f"{prefix}/{{item_id}}",
        edit_v.api_response if hasattr(edit_v, "api_response") else edit_v,
        methods=["GET"],
        response_model=response_schema,
        tags=["api-crud", registered.verbose_name],
    )
    router.add_api_route(
        f"{prefix}/{{item_id}}",
        _wrap_body_handler(edit_v.api_response, update_schema),
        methods=["PUT"],
        response_model=response_schema,
        tags=["api-crud", registered.verbose_name],
    )
    router.add_api_route(
        f"{prefix}/{{item_id}}",
        delete_v.api_response if hasattr(delete_v, "api_response") else delete_v,
        methods=["DELETE"],
        status_code=204,
        tags=["api-crud", registered.verbose_name],
    )
