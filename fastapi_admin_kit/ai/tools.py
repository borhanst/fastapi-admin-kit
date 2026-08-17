"""Tool system — registration, registry, and decorator."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Tool:
    """Represents an AI tool with its metadata and handler."""

    name: str
    description: str
    handler: Callable[..., Awaitable[Any]]
    uses_context: bool = True
    path: str | None = None
    method: str = "POST"
    requires_auth: bool = True
    category: str = "general"
    _schema: dict[str, Any] | None = field(default=None, repr=False)

    def to_schema(self) -> dict[str, Any]:
        return self._schema or {}


class ToolRegistry:
    """Global registry for AI tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: Callable[..., Awaitable[Any]],
        *,
        uses_context: bool = True,
        path: str | None = None,
        method: str = "POST",
        requires_auth: bool = True,
        category: str = "general",
    ) -> Tool:
        tool = Tool(
            name=name,
            description=description,
            handler=handler,
            uses_context=uses_context,
            path=path,
            method=method,
            requires_auth=requires_auth,
            category=category,
        )
        self._tools[name] = tool
        return tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def by_category(self, category: str) -> list[Tool]:
        return [t for t in self._tools.values() if t.category == category]

    def resolve(self, names: list[str]) -> list[Tool]:
        """Resolve a list of tool names to Tool objects, raising if any are unknown."""
        tools: list[Tool] = []
        for name in names:
            tool = self._tools.get(name)
            if tool is None:
                raise KeyError(
                    f"Tool '{name}' not found in registry. Available: {list(self._tools.keys())}"
                )
            tools.append(tool)
        return tools


tool_registry = ToolRegistry()


def tool(
    name: str,
    description: str,
    *,
    uses_context: bool = True,
    path: str | None = None,
    method: str = "POST",
    requires_auth: bool = True,
    category: str = "general",
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to register a function as an AI tool."""

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        tool_registry.register(
            name=name,
            description=description,
            handler=func,
            uses_context=uses_context,
            path=path,
            method=method,
            requires_auth=requires_auth,
            category=category,
        )
        func._ai_tool = True  # type: ignore[attr-defined]
        return func

    return decorator
