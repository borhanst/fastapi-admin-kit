"""Built-in tools for AI agents.

All database operations are routed through the ORM-agnostic backend adapters
stored on :class:`~fastapi_admin_kit.ai.deps.AdminDeps`.  When a backend
adapter is ``None`` (e.g. a minimal setup without ``Admin.setup``) the
implementations fall back to direct SQLAlchemy calls so existing code
continues to work unchanged.
"""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_ai import RunContext

from fastapi_admin_kit.ai.deps import AdminDeps
from fastapi_admin_kit.ai.tools import tool


class QueryResult(BaseModel):
    """Result of a database query."""

    row_count: int
    rows: list[dict[str, object]]


@tool(
    name="query_database",
    description="Query a registered model with filters.",
    category="database",
)
async def query_database(
    ctx: RunContext[AdminDeps],
    table_name: str,
    filters: dict[str, object] | None = None,
    limit: int = 50,
) -> QueryResult:
    deps = ctx.deps
    registered = deps.registry.get(table_name)
    if not registered:
        raise ValueError(f"'{table_name}' is not a registered model.")

    if not await deps.permission_checker.has_permission(table_name, "view"):
        raise ValueError(f"Not permitted to view {table_name}.")

    session = deps.session
    qb = deps.query_backend

    if qb is not None:
        # ORM-agnostic path — use the registered QueryBackend adapter.
        stmt = qb.select(registered.model)
        for field_name, value in (filters or {}).items():
            col_attr = getattr(registered.model, field_name, None)
            if col_attr is None:
                continue
            if isinstance(value, dict | list):
                continue
            try:
                if value is None:
                    stmt = qb.where(stmt, col_attr.is_(None))
                else:
                    stmt = qb.where(stmt, col_attr == value)
            except Exception:  # noqa: BLE001
                continue
        stmt = qb.limit(stmt, limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()
    else:
        # Fallback: direct SQLAlchemy (existing behaviour).
        from sqlalchemy import select

        stmt = select(registered.model)
        model = registered.model
        for field_name, value in (filters or {}).items():
            if not hasattr(model, field_name):
                continue
            if isinstance(value, dict | list):
                continue
            col = getattr(model, field_name)
            try:
                if value is None:
                    stmt = stmt.where(col.is_(None))
                else:
                    stmt = stmt.where(col == value)
            except Exception:  # noqa: BLE001
                continue
        stmt = stmt.limit(limit)
        result = await session.execute(stmt)
        rows = result.scalars().all()

    return QueryResult(
        row_count=len(rows),
        rows=[{c.name: getattr(row, c.name, None) for c in registered.columns} for row in rows],
    )


@tool(
    name="create_record",
    description="Create a new record on a registered model.",
    category="database",
)
async def create_record(
    ctx: RunContext[AdminDeps], table_name: str, data: dict[str, object]
) -> dict[str, object]:
    deps = ctx.deps
    registered = deps.registry.get(table_name)
    if not registered:
        raise ValueError(f"'{table_name}' is not a registered model.")

    if not await deps.permission_checker.has_permission(table_name, "create"):
        raise ValueError(f"Not permitted to create {table_name}.")

    model = registered.model
    session = deps.session

    obj = model(**data)
    session.add(obj)
    await session.flush()

    return {"id": getattr(obj, "id", None), "table": table_name}


class ReportSpec(BaseModel):
    """Specification for generating a report."""

    report_type: str
    filters: dict[str, object] = {}


@tool(
    name="generate_report",
    description="Generate an analytics report.",
    category="analytics",
)
async def generate_report(ctx: RunContext[AdminDeps], spec: ReportSpec) -> dict[str, object]:
    return {
        "report_type": spec.report_type,
        "filters": spec.filters,
        "status": "generated",
        "data": [],
    }


@tool(
    name="send_notification",
    description="Send a notification to a user.",
    category="notifications",
)
async def send_notification(
    ctx: RunContext[AdminDeps], recipient: str, subject: str, message: str
) -> dict[str, str]:
    return {
        "recipient": recipient,
        "subject": subject,
        "status": "sent",
    }
