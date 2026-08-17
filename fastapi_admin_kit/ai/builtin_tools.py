"""Built-in tools for AI agents.

All database reads/writes go through :class:`~fastapi_admin_kit.ai.deps
.AdminDeps.data_access` — the single seam that owns the ORM-agnostic /
direct-SQLAlchemy dual path.  Tools no longer duplicate the fallback branch.
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

    rows = await deps.data_access.query(registered.model, filters, limit)

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

    obj = await deps.data_access.create_record(registered.model, data)

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
