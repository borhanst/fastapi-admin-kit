"""Bulk actions for list views."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi_admin_kit.actions.base import Action, ModelAction
from fastapi_admin_kit.actions.registry import ActionRegistry

__all__ = ["Action", "ModelAction", "ActionRegistry", "action"]


def action(
    name: str = "",
    label: str = "",
    confirmation_message: str = "",
    icon: str | None = None,
    variant: str = "default",
    permissions: list[str] | None = None,
    location: str = "list",
    description: str = "",
) -> Callable:
    """Decorator to register an action on a ModelAdmin class.

    Usage::

        @admin.register(Product)
        class ProductAdmin(ModelAdmin):
            @action(
                description="Export selected products",
                icon="arrow-down-tray",
                variant="primary",
            )
            async def export_products(self, objects, request):
                ...
    """

    def decorator(fn: Callable) -> Callable:
        action_name = name or fn.__name__
        action_label = label or action_name.replace("_", " ").title()

        class DecoratedAction(Action):
            def __init__(self) -> None:
                super().__init__(
                    name=action_name,
                    label=action_label,
                    confirmation_message=confirmation_message,
                    icon=icon,
                    variant=variant,
                    permissions=permissions or [],
                    location=location,
                    description=description,
                )

            async def execute(self, objects: list[Any], request: Any) -> None:
                await fn(self, objects, request)

        fn._admin_action = DecoratedAction
        fn._admin_action_name = action_name
        return fn

    return decorator
