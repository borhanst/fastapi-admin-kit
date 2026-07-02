"""Base pagination classes and result dataclass."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class PaginationResult:
    """Unified result from any pagination strategy."""

    items: list[Any]
    total: int
    per_page: int
    page: int | None = None
    total_pages: int | None = None
    next_cursor: str | None = None
    has_next: bool = False
    mode: str = "offset"


class BasePagination(ABC):
    """Abstract base for all pagination strategies."""

    @abstractmethod
    async def paginate(
        self,
        stmt: Any,
        session: Any,
        per_page: int,
        page: int = 1,
        after: str | None = None,
        before: str | None = None,
        pk_col: Any = None,
        model: Any = None,
    ) -> PaginationResult:
        """Execute paginated query and return results."""
        ...
