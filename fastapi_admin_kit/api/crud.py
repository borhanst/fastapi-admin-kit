"""JSON CRUD handlers for the Admin API.

Uses view classes' api_response() to eliminate duplicate logic.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response
from pydantic import BaseModel

from fastapi_admin_kit.api.deps import require_api_permission
from fastapi_admin_kit.api.schema_generator import (
    _file_field_names,
    get_or_build_schemas,
    has_file_fields,
)
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


def _export_endpoint(registered: Any) -> str | None:
    """Return the model's ``export_endpoint`` setting (None / "html" / "api")."""
    return getattr(registered.admin, "export_endpoint", None)


def build_api_router(registry: Any) -> APIRouter:
    """Build the CRUD API router for all registered models."""
    router = APIRouter(tags=["api-crud"])

    for registered in registry.all():
        # Respect skip_auto_routes (set for internal/built-in tables and any
        # model that opts out of auto routes) so internal tables like
        # admin_refresh_tokens / admin_user_totp are never exposed over JSON API.
        if getattr(registered.admin, "skip_auto_routes", False):
            continue
        # Models with export_endpoint="html" only expose their admin HTML
        # router — the JSON API router is skipped.
        if _export_endpoint(registered) == "html":
            continue
        router.include_router(build_api_router_for_model(registered))

    return router


def build_api_router_for_model(registered: Any) -> APIRouter:
    """Build a standalone CRUD router for a single model.

    Used by ``AdminRegistry``-driven route building and by the standalone
    ``ModelAdmin.export_api_route`` helper, so a model's JSON API can be
    exposed without registering it with the admin.
    """
    router = APIRouter(
        prefix=f"/{registered.table_name}",
        tags=["api-crud", registered.verbose_name],
    )
    _register_model_routes(router, registered)
    return router


def _wrap_body_handler(
    handler: Any, payload_schema: type[BaseModel], *, include_item_id: bool = False
) -> Any:
    """Wrap a view handler so FastAPI can document the request body.

    The view handlers parse the JSON body themselves, so we accept the
    generated Pydantic schema as a body parameter and stash the parsed dict
    on ``request.state`` for ``JSONBodyParser`` to pick up.

    Set ``include_item_id`` only for routes whose path contains ``{item_id}``
    so it is documented as a path parameter (and never leaks a query param
    on collection routes like POST).
    """
    payload_type = Annotated[payload_schema, Body(...)]

    if include_item_id:

        async def wrapped(request: Request, payload: payload_type, item_id: Any) -> Any:
            request.state._api_payload = payload.model_dump(exclude_unset=True)
            return await handler(request, item_id=item_id)

        wrapped.__annotations__ = {
            "request": Request,
            "payload": payload_type,
            "item_id": Any,
            "return": Any,
        }
    else:

        async def wrapped(request: Request, payload: payload_type) -> Any:
            request.state._api_payload = payload.model_dump(exclude_unset=True)
            return await handler(request)

        wrapped.__annotations__ = {
            "request": Request,
            "payload": payload_type,
            "return": Any,
        }

    wrapped.__name__ = getattr(handler, "__name__", "api_response")
    wrapped.__doc__ = getattr(handler, "__doc__", None)
    return wrapped


def _wrap_item_handler(handler: Any, *, returns_response: bool = False) -> Any:
    """Wrap a single-item view handler so only the ``item_id`` path param is exposed.

    The underlying handlers accept both ``id`` and ``item_id`` (the admin
    HTML routes pass ``id``); for the JSON API we only want ``item_id`` so a
    redundant ``id`` query parameter is not leaked into the OpenAPI docs.
    """

    async def wrapped(request: Request, item_id: Any) -> Any:
        return await handler(request, item_id=item_id)

    wrapped.__annotations__ = {
        "request": Request,
        "item_id": Any,
        "return": Response if returns_response else Any,
    }
    wrapped.__name__ = getattr(handler, "__name__", "api_response")
    wrapped.__doc__ = getattr(handler, "__doc__", None)
    return wrapped


def _wrap_multipart_handler(
    handler: Any,
    payload_schema: type[BaseModel],
    registered: Any,
    *,
    include_item_id: bool = False,
) -> Any:
    """Multipart variant of :func:`_wrap_body_handler` for file/image models.

    Declares one ``File()`` param per file column and a ``Form()`` param for
    every other write-schema field, so Swagger switches to a multipart form
    with file pickers. Non-file values arrive as raw strings (exactly like the
    HTML form) and are coerced by ``JSONBodyParser``'s widget pipeline;
    ``None`` values are dropped to keep partial-update semantics.
    """
    from inspect import Parameter, Signature

    file_names = _file_field_names(registered)

    params = [
        Parameter("request", Parameter.POSITIONAL_OR_KEYWORD, annotation=Request),
    ]
    if include_item_id:
        params.append(Parameter("item_id", Parameter.POSITIONAL_OR_KEYWORD, annotation=Any))
    for name in payload_schema.model_fields:
        if name in file_names:
            param_type = Annotated[UploadFile | None, File()]
        else:
            param_type = Annotated[str | None, Form()]
        # All params optional here — required fields are enforced by the
        # shared widget/validator pipeline, exactly like the HTML form.
        params.append(
            Parameter(name, Parameter.KEYWORD_ONLY, default=None, annotation=param_type)
        )

    if include_item_id:

        async def wrapped(request: Request, **kwargs: Any) -> Any:
            item_id = kwargs.pop("item_id", None)
            request.state._api_payload = {
                k: v for k, v in kwargs.items() if v is not None
            }
            return await handler(request, item_id=item_id)

    else:

        async def wrapped(request: Request, **kwargs: Any) -> Any:
            request.state._api_payload = {
                k: v for k, v in kwargs.items() if v is not None
            }
            return await handler(request)

    wrapped.__signature__ = Signature(params)
    wrapped.__name__ = getattr(handler, "__name__", "api_response")
    wrapped.__doc__ = getattr(handler, "__doc__", None)
    return wrapped


# Lookups each filter field_type supports — mirrors the apply() methods in
# filters/base.py. Exact uses the bare ``filter_<field>`` param.
LOOKUPS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "text": ("exact", "icontains", "startswith", "endswith"),
    "boolean": ("exact",),
    "enum": ("exact", "in"),
    "relation": ("exact",),
    "integer": ("exact", "gt", "gte", "lt", "lte", "range", "in"),
    "numeric": ("exact", "gt", "gte", "lt", "lte", "range", "in"),
    "date": ("exact", "gt", "gte", "lt", "lte", "range", "in", "from", "to"),
    "datetime": ("exact", "gt", "gte", "lt", "lte", "range", "in", "from", "to"),
    "time": ("exact", "gt", "gte", "lt", "lte", "range", "in"),
}


def _lookups_for_field_type(field_type: str) -> tuple[str, ...]:
    """Return the lookup names a filter field_type supports (from base.apply())."""
    return LOOKUPS_BY_TYPE.get(field_type, ("exact",))


def _wrap_list_handler(handler: Any, registered: Any) -> Any:
    """Document configured list filters as query params in the OpenAPI schema.

    Filtering already works — the query provider reads ``filter_*`` from
    ``request.query_params``. This wrapper only declares those params so
    Swagger lists them: it mirrors the handler's own signature (pagination
    stays documented) and appends one optional string param per filter field
    for each lookup its type supports. Only the handler's original params are
    forwarded; the ``filter_*`` values reach the provider through the raw
    query string.
    """
    import inspect
    from inspect import Parameter, Signature

    from fastapi_admin_kit.filters import Filter, FilterRegistry, SimpleFilter
    from fastapi_admin_kit.filters.lookups import LOOKUP_SUFFIXES

    suffix = dict(LOOKUP_SUFFIXES)
    try:
        auto = FilterRegistry().auto_generate(registered.model, registered.columns)
    except Exception:
        auto = {}

    filter_fields: list[tuple[str, str]] = []  # (field_name, field_type)
    for item in registered.admin.list_filter or []:
        if isinstance(item, str):
            f = auto.get(item)
            filter_fields.append((item, getattr(f, "field_type", "text") if f else "text"))
        elif isinstance(item, Filter):
            filter_fields.append((item.field_name, item.field_type))
        elif isinstance(item, type) and issubclass(item, SimpleFilter):
            f = item()
            filter_fields.append((f.field_name, f.field_type))
        else:
            continue

    sig = inspect.signature(handler)
    params = list(sig.parameters.values())
    for name, field_type in filter_fields:
        for lookup in _lookups_for_field_type(field_type):
            qname = f"{name}{suffix[lookup]}"
            params.append(
                Parameter(
                    qname,
                    Parameter.KEYWORD_ONLY,
                    default=Query(None, description=f"Filter on '{name}' ({lookup})"),
                )
            )

    handler_params = {p.name for p in sig.parameters.values() if p.name != "request"}

    async def wrapped(request: Request, **kwargs: Any) -> Any:
        return await handler(request, **{k: v for k, v in kwargs.items() if k in handler_params})

    wrapped.__signature__ = Signature(params)
    wrapped.__name__ = getattr(handler, "__name__", "api_response")
    wrapped.__doc__ = getattr(handler, "__doc__", None)
    return wrapped


def _register_model_routes(router: APIRouter, registered: Any) -> None:
    """Register CRUD routes for a single model using view classes."""
    table_name = registered.table_name

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

    list_handler = list_v.api_response if hasattr(list_v, "api_response") else list_v

    # Models with file/image columns use multipart form bodies (file pickers
    # in Swagger); everything else keeps the JSON body.
    use_multipart = has_file_fields(registered)

    def _body_wrapper(
        handler: Any, payload_schema: type[BaseModel], *, include_item_id: bool = False
    ) -> Any:
        if use_multipart:
            return _wrap_multipart_handler(
                handler, payload_schema, registered, include_item_id=include_item_id
            )
        return _wrap_body_handler(handler, payload_schema, include_item_id=include_item_id)

    # Add routes with both "api-crud" and model verbose_name tags
    router.add_api_route(
        "",
        _wrap_list_handler(list_handler, registered),
        methods=["GET"],
        response_model=list_response_schema,
        tags=["api-crud", registered.verbose_name],
        dependencies=[Depends(require_api_permission(table_name, "view"))],
    )
    router.add_api_route(
        "",
        _body_wrapper(create_v.api_response, create_schema),
        methods=["POST"],
        response_model=response_schema,
        status_code=201,
        tags=["api-crud", registered.verbose_name],
        dependencies=[Depends(require_api_permission(table_name, "create"))],
    )
    router.add_api_route(
        "/{item_id}",
        _wrap_item_handler(edit_v.api_response),
        methods=["GET"],
        response_model=response_schema,
        tags=["api-crud", registered.verbose_name],
        dependencies=[Depends(require_api_permission(table_name, "view"))],
    )
    router.add_api_route(
        "/{item_id}",
        _body_wrapper(edit_v.api_response, update_schema, include_item_id=True),
        methods=["PUT"],
        response_model=response_schema,
        tags=["api-crud", registered.verbose_name],
        dependencies=[Depends(require_api_permission(table_name, "edit"))],
    )
    router.add_api_route(
        "/{item_id}",
        _body_wrapper(edit_v.api_response, update_schema, include_item_id=True),
        methods=["PATCH"],
        response_model=response_schema,
        tags=["api-crud", registered.verbose_name],
        dependencies=[Depends(require_api_permission(table_name, "edit"))],
    )
    router.add_api_route(
        "/{item_id}",
        _wrap_item_handler(delete_v.api_response, returns_response=True),
        methods=["DELETE"],
        status_code=204,
        tags=["api-crud", registered.verbose_name],
        dependencies=[Depends(require_api_permission(table_name, "delete"))],
    )
