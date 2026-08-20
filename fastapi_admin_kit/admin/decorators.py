"""Decorators for ModelAdmin customization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic import BaseModel


@dataclass
class EndpointOptions:
    """Metadata for @endpoint() decorator."""

    path: str
    methods: list[str] = field(default_factory=lambda: ["GET"])
    tags: list[str] = field(default_factory=list)
    description: str = ""
    name: str = ""
    dependencies: list[Any] = field(default_factory=list)
    status_code: int = 200
    response_model: type[BaseModel] | None = None
    summary: str = ""
    response_description: str = ""
    permission: str | None = None
    include_in_schema: bool = True

    def __call__(self, func: Callable) -> Callable:
        func._admin_endpoint = self
        return func


@dataclass
class ColumnOptions:
    """Metadata for @column() decorator."""

    header: str = ""
    boolean: bool = False
    order: str | None = None
    format: str | None = None
    empty_value: str = "-"
    template: str | None = None
    admin_order_field: str | None = None
    css_class: str = ""
    width: str | None = None
    exportable: bool = True
    icon: str = ""

    def __call__(self, func: Callable) -> Callable:
        if not self.header:
            self.header = func.__name__.replace("_", " ").title()
        func._column_options = self
        return func


def column(
    header: str = "",
    boolean: bool = False,
    order: str | None = None,
    format: str | None = None,
    empty_value: str = "-",
    template: str | None = None,
    admin_order_field: str | None = None,
    css_class: str = "",
    width: str | None = None,
    exportable: bool = True,
    icon: str = "",
) -> ColumnOptions:
    """Decorator to mark a method as a custom column display.

    Usage::

        from fastapi_admin_kit import column

        class ProductAdmin(ModelAdmin):
            list_display = ["name", "price_display"]

            @column(header="Price", format="${:,.2f}", icon="attach_money")
            def price_display(self, obj):
                return obj.price
    """
    return ColumnOptions(
        header=header,
        boolean=boolean,
        order=order,
        format=format,
        empty_value=empty_value,
        template=template,
        admin_order_field=admin_order_field,
        css_class=css_class,
        width=width,
        exportable=exportable,
        icon=icon,
    )


def endpoint(
    path: str,
    methods: list[str] | None = None,
    tags: list[str] | None = None,
    description: str = "",
    name: str = "",
    dependencies: list[Any] | None = None,
    status_code: int = 200,
    response_model: type[BaseModel] | None = None,
    summary: str = "",
    response_description: str = "",
    permission: str | None = None,
    include_in_schema: bool = True,
) -> EndpointOptions:
    """Decorator to register a custom FastAPI endpoint on a ModelAdmin.

    Endpoints are auto-registered on the model's admin router by
    ``build_model_router()`` via ``APIRouter.add_api_route()``, keeping full
    FastAPI configuration support (path, methods, tags, dependencies,
    status code, response model, ...).

    Usage::

        from fastapi_admin_kit import endpoint

        class ProductAdmin(ModelAdmin):
            @endpoint(
                path="/health-check",
                methods=["GET"],
                tags=["monitoring"],
                description="Health check endpoint",
                permission="view",
            )
            async def health_check(self, request):
                return {"status": "healthy"}
    """
    return EndpointOptions(
        path=path,
        methods=methods or ["GET"],
        tags=tags or [],
        description=description,
        name=name,
        dependencies=dependencies or [],
        status_code=status_code,
        response_model=response_model,
        summary=summary,
        response_description=response_description,
        permission=permission,
        include_in_schema=include_in_schema,
    )
