"""Decorators for ModelAdmin customization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


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
