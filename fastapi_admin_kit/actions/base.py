"""Action ABCs."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from fastapi import Request


class Action(ABC):
    """Abstract base class for admin actions.

    Supports list-level, row-level, detail-level, and submit-line actions
    with Unfold-style icon, variant, and permission configuration.
    """

    def __init__(
        self,
        name: str,
        label: str = "",
        confirmation_message: str = "",
        icon: str | None = None,
        variant: str = "default",
        permissions: list[str] | None = None,
        location: str = "list",
        description: str = "",
    ) -> None:
        self.name = name
        self.label = label or name.replace("_", " ").title()
        self.confirmation_message = confirmation_message
        self.icon = icon
        self.variant = variant  # default, primary, danger, success, warning
        self.permissions = permissions or []
        self.location = location  # list, row, detail, submit_line
        self.description = description

    @abstractmethod
    async def execute(self, objects: list[Any], request: Request | None) -> None:
        """Run the action against the selected objects."""
        ...

    def get_confirmation_message(self) -> str:
        return self.confirmation_message or f"Run {self.label}?"

    def has_permission(self, user: Any) -> bool:
        """Check if the user has permission to run this action."""
        if not self.permissions:
            return True
        if getattr(user, "is_superuser", False):
            return True
        user_perms = getattr(user, "permissions", []) or []
        return any(p in user_perms for p in self.permissions)


class ModelAction(Action):
    """Action that operates on a single model instance (row/detail actions)."""

    async def execute_single(self, obj: Any, request: Request | None) -> None:
        """Run the action on a single object.

        Override this instead of execute for single-object actions.
        """
        await self.execute([obj], request)
