"""Cursor-based (keyset) pagination using base64-encoded cursors."""

from __future__ import annotations

import base64
import json
from typing import Any

from sqlalchemy import func, select

from fastapi_admin_kit.pagination.base import BasePagination, PaginationResult


class CursorPagination(BasePagination):
    """Keyset pagination using opaque base64-encoded cursors.

    Uses a configurable column (default: primary key) for cursor values.
    Supports forward (after) and backward (before) navigation.
    """

    def __init__(self, cursor_column: str | None = None):
        self.cursor_column = cursor_column

    def _decode_cursor(self, cursor: str) -> Any:
        """Decode base64 cursor to Python value."""
        return json.loads(base64.b64decode(cursor))

    def _encode_cursor(self, value: Any) -> str:
        """Encode Python value to base64 cursor string."""
        return base64.b64encode(json.dumps(value).encode()).decode()

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
        # Determine cursor column
        if self.cursor_column and model is not None:
            col = getattr(model, self.cursor_column)
        elif pk_col is not None:
            col = pk_col
        else:
            raise ValueError(
                "CursorPagination requires either cursor_column on a model "
                "or pk_col to be provided."
            )

        # Apply cursor filter
        if after:
            cursor_val = self._decode_cursor(after)
            stmt = stmt.where(col > cursor_val)
        elif before:
            cursor_val = self._decode_cursor(before)
            stmt = stmt.where(col < cursor_val)
            # For backward pagination, we need to reverse order then flip results
            from sqlalchemy import desc as sa_desc

            # Check current ordering and reverse it
            stmt = stmt.order_by(sa_desc(col))

        # Count filtered total
        count_q = select(func.count()).select_from(stmt.subquery())
        total = (await session.execute(count_q)).scalar() or 0

        # Fetch per_page + 1 to detect has_next
        stmt = stmt.limit(per_page + 1)
        result = await session.execute(stmt)
        items = list(result.unique().scalars().all())

        # For backward pagination, reverse back to natural order
        if before:
            items = list(reversed(items))

        has_next = len(items) > per_page
        if has_next:
            items = items[:per_page]

        # Build next cursor from last item
        next_cursor = None
        if has_next and items:
            last_val = getattr(items[-1], self.cursor_column or "id")
            next_cursor = self._encode_cursor(last_val)

        return PaginationResult(
            items=items,
            total=total,
            per_page=per_page,
            next_cursor=next_cursor,
            has_next=has_next,
            mode="cursor",
        )
