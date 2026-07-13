"""Action registry."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from fastapi_admin_kit.actions.base import Action


class DeleteSelectedAction(Action):
    """Built-in bulk delete action."""

    def __init__(self) -> None:
        super().__init__(
            name="delete_selected",
            label="Delete selected",
            confirmation_message="Are you sure you want to delete the selected items?",
        )

    async def execute(self, objects: list[Any], request: Request | None) -> None:
        # Actual deletion is handled by the existing bulk handler in views/factory.py
        pass


class ActionRegistry:
    """Registry for custom actions per model."""

    def __init__(self) -> None:
        self._actions: dict[str, list[Action]] = {}

    def register(self, model_name: str, action: Action) -> None:
        self._actions.setdefault(model_name, []).append(action)

    def get_actions(self, model_name: str) -> list[Action]:
        return self._actions.get(model_name, []).copy()

    def auto_generate(self, model_name: str) -> list[Action]:
        """Auto-generate default bulk actions for a model."""
        return [DeleteSelectedAction()]
