"""Built-in tools for AI agents."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from fastapi_admin_kit.ai.tools import tool

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from fastapi_admin_kit.ai.deps import AdminDeps


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
    registered = ctx.deps.registry.get(table_name)
    if not registered:
        raise ValueError(f"'{table_name}' is not a registered model.")

    if not await ctx.deps.permission_checker.has_permission(table_name, "view"):
        raise ValueError(f"Not permitted to view {table_name}.")

    model = registered.model
    session = ctx.deps.session

    from sqlalchemy import select

    stmt = select(model)
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
        except Exception:
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
    registered = ctx.deps.registry.get(table_name)
    if not registered:
        raise ValueError(f"'{table_name}' is not a registered model.")

    if not await ctx.deps.permission_checker.has_permission(table_name, "create"):
        raise ValueError(f"Not permitted to create {table_name}.")

    model = registered.model
    session = ctx.deps.session

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
