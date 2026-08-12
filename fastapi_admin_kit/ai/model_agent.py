"""Model-bound agents — auto CRUD tools via inheritance.

Usage example::

    from fastapi_admin_kit.ai.model_agent import ModelAIAgent
    from fastapi_admin_kit.ai import AIAgentConfig
    from myapp.models import Product

    # Read-only agent (default) — only query_products tool is registered
    class ProductAgent(ModelAIAgent):
        model = Product
        can_view = True
        can_create = False
        can_edit = False
        can_delete = False
        # allow_write defaults to False — write tools are never built

    # Write-enabled agent — all CRUD tools are built, writes are audit-logged
    class ProductWriteAgent(ModelAIAgent):
        model = Product
        allow_write = True   # enable write tools
        can_view = True
        can_create = True
        can_edit = True
        can_delete = False   # still blocked even with allow_write=True

    # Convert to AIAgentConfig for use with AIPlugin / PydanticAIAgent
    config = ProductAgent.to_agent_config(
        name="product-agent",
        model="openai:gpt-4o",
        system_prompt="You are a helpful product catalog assistant.",
    )
"""

from __future__ import annotations

import datetime
from abc import ABC
from typing import TYPE_CHECKING, Any

from pydantic_ai import RunContext

from fastapi_admin_kit.ai.deps import AdminDeps
from fastapi_admin_kit.ai.tools import Tool, tool_registry

if TYPE_CHECKING:
    from fastapi_admin_kit.ai.config import AIAgentConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client_ip(ctx: RunContext[AdminDeps]) -> str | None:
    """Extract the client IP from the request in deps."""
    try:
        return ctx.deps.request.client.host if ctx.deps.request.client else None
    except Exception:  # noqa: BLE001
        return None


def _get_user_agent(ctx: RunContext[AdminDeps]) -> str | None:
    """Extract the User-Agent header from the request in deps."""
    try:
        return ctx.deps.request.headers.get("user-agent")
    except Exception:  # noqa: BLE001
        return None


async def _write_audit(
    ctx: RunContext[AdminDeps],
    event_type: str,
    table_name: str,
    object_id: str,
    object_repr: str = "",
    changes: dict[str, Any] | None = None,
) -> None:
    """Persist a write event to the admin audit log.

    Routes through :attr:`~fastapi_admin_kit.ai.deps.AdminDeps.audit_backend`
    when it is available (ORM-agnostic path).  Falls back to the built-in
    ``SqlAlchemyAuditLogger`` for setups that do not expose an audit backend
    on ``app.state``.
    """
    from fastapi_admin_kit.audit.events import AuditEvent

    user = ctx.deps.admin_user
    event = AuditEvent(
        event_type=event_type,
        model_name=table_name,
        table_name=table_name,
        object_id=str(object_id),
        object_repr=object_repr,
        changes=changes,
        user_id=getattr(user, "id", None),
        user_email=getattr(user, "email", None),
        ip_address=_get_client_ip(ctx),
        user_agent=_get_user_agent(ctx),
        timestamp=datetime.datetime.now(datetime.UTC),
    )

    audit_backend = ctx.deps.audit_backend
    if audit_backend is None:
        # Fallback: direct SQLAlchemy audit logger.
        from fastapi_admin_kit.audit.sqlalchemy_logger import (
            SqlAlchemyAuditLogger,
        )

        logger = SqlAlchemyAuditLogger(session=ctx.deps.session)
        logger.log_create(event) if event_type == "CREATE" else (
            logger.log_update(event) if event_type == "UPDATE" else logger.log_delete(event)
        )
        await logger.flush_pending(ctx.deps.session)
    # When audit_backend is present the session-level listeners registered via
    # audit_backend.attach_listeners() already capture changes automatically;
    # no explicit log call is needed here.


# ---------------------------------------------------------------------------
# Tool builders
# ---------------------------------------------------------------------------


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
        description=f"Query {table_name} records with optional filters. Read-only.",
        handler=_query,
        uses_context=True,
        category="database",
    )


def _build_create_tool(model: type, table_name: str, exclude_fields: list[str]) -> Tool:
    async def _create(ctx: RunContext[AdminDeps], data: dict[str, object]) -> object:
        from fastapi_admin_kit.ai.builtin_tools import create_record

        for f in exclude_fields:
            data.pop(f, None)

        result = await create_record(ctx, table_name, data)

        # Audit: record creation
        await _write_audit(
            ctx,
            event_type="CREATE",
            table_name=table_name,
            object_id=str(result.get("id", "")),
            object_repr=str(data),
            changes={"created": data},
        )

        return result

    return tool_registry.register(
        name=f"create_{table_name}",
        description=f"Create a new {table_name} record. Writes are audit-logged.",
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
        audit = ctx.deps.audit_backend

        # Single fetch-by-PK path (SQLAlchemy fallback lives in DataAccess).
        obj = await ctx.deps.data_access.get_by_pk(model, record_id)

        if not obj:
            raise ValueError(f"No {table_name} with id {record_id}.")

        # Capture before-state for audit diff using AuditBackend.snapshot
        # when available, otherwise fall back to a plain attribute read.
        if audit is not None:
            try:
                before = audit.snapshot(obj)
            except Exception:  # noqa: BLE001
                before = {k: getattr(obj, k, None) for k in data}
        else:
            before = {k: getattr(obj, k, None) for k in data}

        for k, v in data.items():
            if hasattr(obj, k):
                setattr(obj, k, v)
        await session.flush()

        # Compute field-level diff via AuditBackend when available.
        if audit is not None:
            try:
                after_snapshot = audit.snapshot(obj)
                diff = audit.compute_diff(before, after_snapshot)
                changes: dict[str, object] = {"diff": diff}
            except Exception:  # noqa: BLE001
                changes = {"before": before, "after": data}
        else:
            changes = {"before": before, "after": data}

        await _write_audit(
            ctx,
            event_type="UPDATE",
            table_name=table_name,
            object_id=str(record_id),
            object_repr=str(obj),
            changes=changes,
        )

        return {"id": record_id, "table": table_name, "updated": True}

    return tool_registry.register(
        name=f"update_{table_name}",
        description=f"Update a {table_name} record by ID. Writes are audit-logged.",
        handler=_update,
        uses_context=True,
        category="database",
    )


def _build_delete_tool(model: type, table_name: str) -> Tool:
    async def _delete(ctx: RunContext[AdminDeps], record_id: int) -> dict[str, object]:
        if not await ctx.deps.permission_checker.has_permission(table_name, "delete"):
            raise ValueError(f"Not permitted to delete {table_name}.")

        session = ctx.deps.session
        audit = ctx.deps.audit_backend

        # Single fetch-by-PK path (SQLAlchemy fallback lives in DataAccess).
        obj = await ctx.deps.data_access.get_by_pk(model, record_id)

        if not obj:
            raise ValueError(f"No {table_name} with id {record_id}.")

        # Capture pre-deletion snapshot via AuditBackend.snapshot when
        # available; fall back to reading __table__.columns (SQLAlchemy-specific).
        if audit is not None:
            try:
                snapshot: dict[str, object] = audit.snapshot(obj)
            except Exception:  # noqa: BLE001
                snapshot = {"id": record_id}
        else:
            try:
                snapshot = {
                    c.name: getattr(obj, c.name, None)
                    for c in obj.__table__.columns  # type: ignore[attr-defined]
                }
            except Exception:  # noqa: BLE001
                snapshot = {"id": record_id}

        await session.delete(obj)
        await session.flush()

        await _write_audit(
            ctx,
            event_type="DELETE",
            table_name=table_name,
            object_id=str(record_id),
            object_repr=str(snapshot),
            changes={"deleted_snapshot": snapshot},
        )

        return {"id": record_id, "table": table_name, "deleted": True}

    return tool_registry.register(
        name=f"delete_{table_name}",
        description=f"Delete a {table_name} record by ID. Writes are audit-logged.",
        handler=_delete,
        uses_context=True,
        category="database",
    )


# ---------------------------------------------------------------------------
# ModelAIAgent base class
# ---------------------------------------------------------------------------


class ModelAIAgent(ABC):
    """Base class for model-bound agents.

    Subclass and point at a SQLAlchemy model to auto-generate CRUD tools.
    By default the agent is **read-only** (``allow_write = False``).  Set
    ``allow_write = True`` to also register write tools; every write will be
    persisted to the admin audit log.

    Class attributes
    ----------------
    model : type
        The SQLAlchemy model class this agent is bound to.
    allow_write : bool
        Master write switch (default ``False``).  When ``False`` only the
        ``query_<table>`` tool is built regardless of the ``can_*`` flags.
    can_view : bool
        Register a ``query_<table>`` tool (default ``True``).
    can_create : bool
        Register a ``create_<table>`` tool when ``allow_write=True``
        (default ``True``).
    can_edit : bool
        Register an ``update_<table>`` tool when ``allow_write=True``
        (default ``True``).
    can_delete : bool
        Register a ``delete_<table>`` tool when ``allow_write=True``
        (default ``False``).
    exclude_fields : list[str]
        Field names that are stripped from write payloads (e.g. ``["id"]``).
    """

    model: type
    allow_write: bool = False  # ← master write gate; default read-only
    can_view: bool = True
    can_create: bool = True
    can_edit: bool = True
    can_delete: bool = False
    exclude_fields: list[str] = []

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        cls._declared_tools: list[Tool] = [
            m for m in vars(cls).values() if getattr(m, "_ai_tool", False)
        ]

    @classmethod
    def build_tools(cls) -> list[Tool]:
        """Build and return the list of :class:`~fastapi_admin_kit.ai.tools.Tool`
        objects for this agent.

        When ``allow_write=False`` only the query tool is included even if
        ``can_create``/``can_edit``/``can_delete`` are ``True``.  This ensures
        the agent cannot accidentally mutate data.
        """
        table = cls.model.__tablename__
        tools: list[Tool] = []

        if cls.can_view:
            tools.append(_build_query_tool(cls.model, table))

        if cls.allow_write:
            # Write operations are opt-in and individually gated by can_* flags
            if cls.can_create:
                tools.append(_build_create_tool(cls.model, table, list(cls.exclude_fields)))
            if cls.can_edit:
                tools.append(_build_update_tool(cls.model, table, list(cls.exclude_fields)))
            if cls.can_delete:
                tools.append(_build_delete_tool(cls.model, table))

        return tools + list(cls._declared_tools)

    @classmethod
    def to_agent_config(
        cls,
        name: str,
        model: str,
        system_prompt: str = "",
        **kwargs: object,
    ) -> AIAgentConfig:
        """Convert this ``ModelAIAgent`` subclass into an :class:`AIAgentConfig`.

        Builds all tools (respecting ``allow_write``) and returns a ready-to-use
        config that can be passed directly to :class:`AIPlugin` or
        :class:`PydanticAIAgent`.

        Parameters
        ----------
        name:
            Unique agent name (used as the key in ``ai_agents`` app state).
        model:
            LLM model string, e.g. ``"openai:gpt-4o"`` or ``"google:gemini-2.0-flash"``.
        system_prompt:
            Optional static system prompt prepended before the tools list.
        **kwargs:
            Any additional keyword arguments forwarded to :class:`AIAgentConfig`
            (e.g. ``api_key``, ``retries``, ``input_cost``, ``output_cost``).

        Returns
        -------
        AIAgentConfig
            Fully configured agent config with all applicable tools pre-loaded.

        Example
        -------
        ::

            config = ProductAgent.to_agent_config(
                name="product-agent",
                model="openai:gpt-4o",
                system_prompt="You are a product catalog assistant.",
                api_key="sk-...",
            )
            plugin = AIPlugin(agents=[config])
        """
        from fastapi_admin_kit.ai.config import AIAgentConfig

        tools = cls.build_tools()
        return AIAgentConfig(
            name=name,
            model=model,
            system_prompt=system_prompt,
            tools=tools,
            **kwargs,  # type: ignore[arg-type]
        )
