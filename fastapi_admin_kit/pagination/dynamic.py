"""Dynamic pagination — auto-selects offset vs cursor based on data volume."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from fastapi_admin_kit.pagination.base import BasePagination, PaginationResult
from fastapi_admin_kit.pagination.cursor import CursorPagination
from fastapi_admin_kit.pagination.offset import OffsetPagination


class DynamicPagination(BasePagination):
    """Automatically switches between offset and cursor pagination.

    Uses offset for small datasets (fast page jumping),
    cursor for large datasets (consistent performance at any depth).
    """

    def __init__(
        self,
        cursor_column: str | None = None,
        threshold: int = 1000,
    ):
        self.cursor_column = cursor_column
        self.threshold = threshold
        self._offset = OffsetPagination()
        self._cursor = CursorPagination(cursor_column=cursor_column)

    async def paginate(
        self,
        stmt: Any,
        session: Any,
        per_page: int,
        **kw: Any,
    ) -> PaginationResult:
        # Count total to decide strategy
        count_q = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_q)).scalar() or 0

        if total <= self.threshold:
            result = await self._offset.paginate(stmt, session, per_page, **kw)
        else:
            result = await self._cursor.paginate(stmt, session, per_page, **kw)

        result.mode = "dynamic_offset" if total <= self.threshold else "dynamic_cursor"
        return result
