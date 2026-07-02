"""Protocol interfaces for SOLID class-based views.

Each protocol has a single responsibility (ISP).
View classes depend on these abstractions (DIP).
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from fastapi import Request
from fastapi.responses import Response


@runtime_checkable
class QueryProvider(Protocol):
    """Single responsibility: build and execute database queries."""

    async def get_list(
        self, request: Request, q: str, page: int
    ) -> tuple[list[Any], int, int, int]:
        """Return (items, total, page, per_page)."""
        ...

    async def get_object(self, request: Request, id: Any) -> Any | None:
        """Return a single object or None."""
        ...


@runtime_checkable
class FormParser(Protocol):
    """Single responsibility: parse and validate form/request data."""

    async def parse(
        self, request: Request, obj: Any | None = None
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        """Return (parsed_values, errors)."""
        ...


@runtime_checkable
class HTMLRenderer(Protocol):
    """Single responsibility: return an HTML TemplateResponse."""

    async def render(
        self, request: Request, context: dict[str, Any]
    ) -> Response: ...


@runtime_checkable
class APIRenderer(Protocol):
    """Single responsibility: return a JSON Response."""

    async def render(self, request: Request, data: Any) -> Response: ...
