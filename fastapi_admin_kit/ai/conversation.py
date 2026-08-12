"""Centralized conversation-turn persistence.

This module is the single home for "save one chat turn".  Before the
architecture review, that logic was duplicated three ways: inline in the
``ai_chat`` endpoint, again in the stream endpoint's ``on_complete``
closure, and a third time behind ``ConversationRecorder`` (wired through
``patch_agent_with_conversation_logging``) which the stream route bypassed
entirely.  All of it now lives here behind one ``AIConversationStore`` whose
``save_turn`` is the only call the routes make.

The store has no dependency on any LLM, so it is unit-testable with nothing
but an ``AsyncSession``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.ai.serialization import serialize

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from fastapi_admin_kit.ai.agent import ToolCallRecord, UsageInfo
    from fastapi_admin_kit.ai.usage import AIConversation
    from fastapi_admin_kit.auth.protocol import AdminUserProtocol
    from fastapi_admin_kit.backends.protocols import (
        QueryBackend,
        SessionBackend,
    )


def _session_adapter(session: Any) -> Any:
    """Wrap a raw session in a :class:`SessionBackend` adapter."""
    from fastapi_admin_kit.backends.sqlalchemy import SqlAlchemySessionAdapter

    return SqlAlchemySessionAdapter(session)


class AIConversationStore:
    """Deep module owning all conversation/message persistence.

    All reads/writes go through the Admin class's backend adapters:
    ``query_backend`` (a :class:`QueryBackend`) builds the queries and
    ``session_backend`` (a :class:`SessionBackend` wrapping the per-request
    session) executes them.  When neither is supplied the store falls back to
    the SQLAlchemy session directly, so call sites that only have a raw
    ``AsyncSession`` keep working.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        query_backend: QueryBackend | None = None,
        session_backend: SessionBackend | None = None,
        backend: Any = None,
    ) -> None:
        self.session = session
        # Prefer explicit adapters, then the composite backend's adapters.
        if query_backend is None and backend is not None:
            query_backend = getattr(backend, "query", None)
        self._qb = query_backend
        self._sb = session_backend or _session_adapter(session)

    # -- adapter-aware helpers ---------------------------------------------

    def _select(self, model: Any) -> Any:
        """Build a SELECT for *model* via the QueryBackend, or raw SQLAlchemy."""
        if self._qb is not None:
            return self._qb.select(model)
        from sqlalchemy import select

        return select(model)

    async def _exec(self, stmt: Any) -> Any:
        """Execute *stmt* through the session adapter and return the result."""
        return await self._sb.execute(stmt)

    def _add(self, obj: Any) -> None:
        self._sb.add(obj)

    async def _flush(self) -> None:
        await self._sb.flush()

    async def _delete(self, obj: Any) -> None:
        result = self._sb.delete(obj)
        if hasattr(result, "__await__"):
            await result

    async def _commit(self) -> None:
        result = self._sb.commit()
        if hasattr(result, "__await__"):
            await result

    # -- conversation lifecycle --------------------------------------------

    async def get_or_create(
        self,
        conversation_id: str | None,
        agent_name: str,
        user: AdminUserProtocol,
        title: str | None = None,
    ) -> AIConversation:
        from fastapi_admin_kit.ai.usage import AIConversation
        from fastapi_admin_kit.db import flush_with_rollback

        if conversation_id:
            stmt = self._select(AIConversation).where(AIConversation.id == conversation_id)
            conv = (await self._exec(stmt)).scalar_one_or_none()
            if conv:
                return conv

        conv_id = conversation_id if conversation_id else str(uuid.uuid4())
        conv = AIConversation(
            id=conv_id,
            agent_name=agent_name,
            user_id=getattr(user, "id", None),
            user_email=getattr(user, "email", None),
            title=title,
        )
        self._add(conv)
        await flush_with_rollback(self.session)
        return conv

    async def list_for_user(self, user: AdminUserProtocol) -> list[AIConversation]:
        from fastapi_admin_kit.ai.usage import AIConversation

        stmt = (
            self._select(AIConversation)
            .where(AIConversation.user_id == getattr(user, "id", None))
            .order_by(AIConversation.last_message_at.desc().nullslast())
            .limit(50)
        )
        return list((await self._exec(stmt)).scalars().all())

    async def load(self, conversation_id: str, user: AdminUserProtocol) -> AIConversation | None:
        from fastapi_admin_kit.ai.usage import AIConversation

        stmt = self._select(AIConversation).where(
            AIConversation.id == conversation_id,
            AIConversation.user_id == getattr(user, "id", None),
        )
        return (await self._exec(stmt)).scalar_one_or_none()

    async def load_messages(self, conversation_id: str) -> list[Any]:
        from fastapi_admin_kit.ai.usage import AIMessage

        stmt = (
            self._select(AIMessage)
            .where(AIMessage.conversation_id == conversation_id)
            .order_by(AIMessage.created_at)
        )
        return list((await self._exec(stmt)).scalars().all())

    async def delete(self, conversation_id: str, user: AdminUserProtocol) -> bool:
        from fastapi_admin_kit.ai.usage import AIAttachment

        conv = await self.load(conversation_id, user)
        if conv is None:
            return False

        # Bulk delete is not part of the SessionBackend protocol, so fall back
        # to fetching the dependent rows and deleting them via the adapter.
        msgs = await self.load_messages(conversation_id)
        for m in msgs:
            await self._delete(m)

        att_stmt = self._select(AIAttachment).where(AIAttachment.conversation_id == conversation_id)
        attachments = list((await self._exec(att_stmt)).scalars().all())
        for a in attachments:
            await self._delete(a)

        await self._delete(conv)
        await self._commit()
        return True

    # -- message-level writes -----------------------------------------------

    async def append_message(
        self,
        conv: AIConversation,
        role: str,
        content: str,
        *,
        tokens: int | None = None,
        latency_ms: int | None = None,
        tool_name: str | None = None,
        tool_args: Any = None,
        tool_result: Any = None,
        is_error: bool = False,
        error: str | None = None,
    ) -> None:
        from fastapi_admin_kit.ai.usage import AIMessage
        from fastapi_admin_kit.db import flush_with_rollback

        self._add(
            AIMessage(
                conversation_id=conv.id,
                role=role,
                content=content,
                tokens=tokens,
                latency_ms=latency_ms,
                tool_name=tool_name,
                tool_args=serialize(tool_args),
                tool_result=serialize(tool_result),
                is_error=is_error,
                error=error,
            )
        )
        await flush_with_rollback(self.session)

    async def log_tool_call(self, conv: AIConversation, call: ToolCallRecord) -> None:
        await self.append_message(
            conv,
            role="tool",
            content=str(getattr(call, "result", "")),
            tool_name=getattr(call, "name", None),
            tool_args=getattr(call, "args", None),
            tool_result=getattr(call, "result", None),
            is_error=getattr(call, "is_error", False),
        )

    async def log_error(self, conv: AIConversation, error: str) -> None:
        await self.append_message(conv, role="error", content=error, error=error)

    async def touch(
        self,
        conv: AIConversation,
        *,
        message_history: Any = None,
        tokens_delta: int = 0,
        cost_delta: float = 0.0,
    ) -> None:
        from datetime import UTC, datetime

        from fastapi_admin_kit.db import flush_with_rollback

        conv.message_history = message_history
        conv.total_tokens = (conv.total_tokens or 0) + tokens_delta
        conv.total_cost = float(conv.total_cost or 0) + cost_delta
        conv.turn_count = (conv.turn_count or 0) + 1
        conv.last_message_at = datetime.now(UTC)
        await flush_with_rollback(self.session)

    # -- the one call the routes make ---------------------------------------

    async def save_turn(
        self,
        *,
        agent_name: str,
        user: AdminUserProtocol,
        user_message: str,
        output: str,
        usage: UsageInfo,
        tool_calls: list[ToolCallRecord],
        conversation_id: str | None = None,
        new_messages: list[Any] | None = None,
        title: str | None = None,
        cost: float | None = None,
    ) -> str:
        """Persist a complete turn: conversation row, user + assistant messages,
        tool calls, and rolled-up usage.  Returns the conversation id.
        """
        from fastapi_admin_kit.ai.usage import AIMessage
        from fastapi_admin_kit.db import flush_with_rollback

        conv = await self.get_or_create(
            conversation_id,
            agent_name=agent_name,
            user=user,
            title=title or (user_message[:80] if user_message else None),
        )

        if conversation_id:
            existing = conv.message_history or []
            conv.message_history = existing + [serialize(m) for m in (new_messages or [])]
            conv.turn_count = (conv.turn_count or 0) + 1
            conv.total_tokens = (conv.total_tokens or 0) + usage.total_tokens
            conv.total_cost = float(conv.total_cost or 0) + (
                cost if cost is not None else usage.cost
            )
            from datetime import UTC, datetime

            conv.last_message_at = datetime.now(UTC)
        else:
            conv.message_history = [serialize(m) for m in (new_messages or [])]
            conv.turn_count = 1
            conv.total_tokens = usage.total_tokens
            conv.total_cost = cost if cost is not None else usage.cost

        self._add(
            AIMessage(
                conversation_id=conv.id,
                role="user",
                content=user_message,
            )
        )
        self._add(
            AIMessage(
                conversation_id=conv.id,
                role="assistant",
                content=output,
                tokens=usage.total_tokens,
                latency_ms=None,
            )
        )
        for tc in tool_calls:
            await self.log_tool_call(conv, tc)

        await flush_with_rollback(self.session)
        return conv.id

    async def record_usage(
        self,
        *,
        agent_name: str,
        model: str,
        usage: UsageInfo,
        user: AdminUserProtocol,
        success: bool,
        latency_ms: int,
        tool_calls: list[ToolCallRecord],
        cost: float | None = None,
    ) -> None:
        """Write the AIUsageLog row for a turn (streaming path)."""
        from fastapi_admin_kit.ai.usage import AIUsageWriter

        writer = AIUsageWriter()
        await writer.write(
            agent_name=agent_name,
            model=model,
            request_tokens=usage.request_tokens,
            response_tokens=usage.response_tokens,
            total_tokens=usage.total_tokens,
            cost=cost if cost is not None else usage.cost,
            user=user,
            success=success,
            latency_ms=latency_ms,
            tool_calls=[
                {
                    "name": getattr(tc, "name", ""),
                    "args": getattr(tc, "args", {}),
                    "ok": getattr(tc, "is_error", False) is False,
                }
                for tc in tool_calls
            ],
            session=self.session,
        )
