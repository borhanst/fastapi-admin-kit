"""Offset-based pagination (existing behavior)."""

from __future__ import annotations

import math
from typing import Any

from fastapi_admin_kit.pagination.base import BasePagination, PaginationResult


class OffsetPagination(BasePagination):
    """Traditional page-number pagination using OFFSET/LIMIT."""

    async def paginate(
        self,
        stmt: Any,
        session: Any,
        per_page: int,
        page: int = 1,
        query_adapter: Any = None,
        **kw: Any,
    ) -> PaginationResult:
        if query_adapter is not None:
            count_q = query_adapter.count(stmt)
            total = (await session.execute(count_q)).scalar() or 0
        else:
            from sqlalchemy import func, select

            count_q = select(func.count()).select_from(stmt.subquery())
            total = (await session.execute(count_q)).scalar() or 0

        total_pages = max(1, math.ceil(total / per_page))
        page = max(1, min(page, total_pages))
        offset = (page - 1) * per_page

        if query_adapter is not None:
            stmt = query_adapter.offset(stmt, offset)
            stmt = query_adapter.limit(stmt, per_page)
        else:
            stmt = stmt.offset(offset).limit(per_page)

        result = await session.execute(stmt)
        items = list(result.unique().scalars().all())

        return PaginationResult(
            items=items,
            total=total,
            per_page=per_page,
            page=page,
            total_pages=total_pages,
            mode="offset",
        )
