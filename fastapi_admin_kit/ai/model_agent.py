"""Model-bound agents — auto CRUD tools via inheritance."""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING

from fastapi_admin_kit.ai.tools import Tool, tool_registry

if TYPE_CHECKING:
    from pydantic_ai import RunContext

    from fastapi_admin_kit.ai.deps import AdminDeps


def _build_query_tool(model: type, table_name: str) -> Tool:
    async def _query(
        ctx: RunContext[AdminDeps],
        filters: dict[str, object] | None = None,
        limit: int = 50,
    ) -> object:
        from fastapi_admin_kit.ai.builtin_tools import query_database

        return await query_database(ctx, table_name, filters, limit)

    return tool_registry.register(
        name=f"query_{table_name}",
        description=f"Query {table_name} records with filters.",
        handler=_query,
        uses_context=True,
        category="database",
    )


def _build_create_tool(model: type, table_name: str, exclude_fields: list[str]) -> Tool:
    async def _create(ctx: RunContext[AdminDeps], data: dict[str, object]) -> object:
        from fastapi_admin_kit.ai.builtin_tools import create_record

        for f in exclude_fields:
            data.pop(f, None)
        return await create_record(ctx, table_name, data)

    return tool_registry.register(
        name=f"create_{table_name}",
        description=f"Create a new {table_name} record.",
        handler=_create,
        uses_context=True,
        category="database",
    )


def _build_update_tool(model: type, table_name: str, exclude_fields: list[str]) -> Tool:
    async def _update(
        ctx: RunContext[AdminDeps], record_id: int, data: dict[str, object]
    ) -> dict[str, object]:
        if not await ctx.deps.permission_checker.has_permission(table_name, "edit"):
            raise ValueError(f"Not permitted to edit {table_name}.")

        for f in exclude_fields:
            data.pop(f, None)

        session = ctx.deps.session
        from sqlalchemy import select

        result = await session.execute(select(model).where(getattr(model, "id") == record_id))
        obj = result.scalar_one_or_none()
        if not obj:
            raise ValueError(f"No {table_name} with id {record_id}.")

        for k, v in data.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        await session.flush()
        return {"id": record_id, "table": table_name, "updated": True}

    return tool_registry.register(
        name=f"update_{table_name}",
        description=f"Update a {table_name} record by ID.",
        handler=_update,
        uses_context=True,
        category="database",
    )


def _build_delete_tool(model: type, table_name: str) -> Tool:
    async def _delete(ctx: RunContext[AdminDeps], record_id: int) -> dict[str, object]:
        if not await ctx.deps.permission_checker.has_permission(table_name, "delete"):
            raise ValueError(f"Not permitted to delete {table_name}.")

        session = ctx.deps.session
        from sqlalchemy import select

        result = await session.execute(select(model).where(getattr(model, "id") == record_id))
        obj = result.scalar_one_or_none()
        if not obj:
            raise ValueError(f"No {table_name} with id {record_id}.")

        await session.delete(obj)
        await session.flush()
        return {"id": record_id, "table": table_name, "deleted": True}

    return tool_registry.register(
        name=f"delete_{table_name}",
        description=f"Delete a {table_name} record by ID.",
        handler=_delete,
        uses_context=True,
        category="database",
    )


class ModelAIAgent(ABC):
    """Base class for model-bound agents.

    Subclassing and pointing at a model auto-generates CRUD tools.
    """

    model: type
    can_view: bool = True
    can_create: bool = True
    can_edit: bool = True
    can_delete: bool = False
    exclude_fields: list[str] = []

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._declared_tools = [m for m in vars(cls).values() if getattr(m, "_ai_tool", False)]

    @classmethod
    def build_tools(cls) -> list[Tool]:
        table = cls.model.__tablename__
        tools: list[Tool] = []
        if cls.can_view:
            tools.append(_build_query_tool(cls.model, table))
        if cls.can_create:
            tools.append(_build_create_tool(cls.model, table, cls.exclude_fields))
        if cls.can_edit:
            tools.append(_build_update_tool(cls.model, table, cls.exclude_fields))
        if cls.can_delete:
            tools.append(_build_delete_tool(cls.model, table))
        return tools + cls._declared_tools
