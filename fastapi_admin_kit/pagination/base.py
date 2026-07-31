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
        query_adapter: Any = None,
    ) -> PaginationResult:
        """Execute paginated query and return results.

        Args:
            stmt: The base query/statement to paginate.
            session: Session or SessionBackend for query execution.
            per_page: Number of items per page.
            page: Page number (for offset pagination).
            after: Cursor for forward pagination.
            before: Cursor for backward pagination.
            pk_col: Primary key column for cursor pagination.
            model: SQLAlchemy model class.
            query_adapter: QueryBackend for ORM-agnostic query construction.
        """
        ...
