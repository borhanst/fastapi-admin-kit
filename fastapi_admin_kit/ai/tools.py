"""Tool system — registration, registry, and decorator."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class Tool:
    """Represents an AI tool with its metadata and handler."""

    name: str
    description: str
    handler: Callable
    uses_context: bool = True
    path: str | None = None
    method: str = "POST"
    requires_auth: bool = True
    category: str = "general"
    _schema: dict | None = field(default=None, repr=False)

    def to_schema(self) -> dict:
        return self._schema or {}


class ToolRegistry:
    """Global registry for AI tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self,
        name: str,
        description: str,
        handler: Callable,
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
) -> Callable:
    """Decorator to register a function as an AI tool."""

    def decorator(func: Callable) -> Callable:
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
        func._ai_tool = True
        return func

    return decorator
