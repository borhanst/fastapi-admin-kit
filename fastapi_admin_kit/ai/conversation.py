"""Conversation and message logging for AI agents."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from fastapi_admin_kit.ai.agent import AIAgent, ChatResult, ToolCallRecord
    from fastapi_admin_kit.ai.deps import AdminDeps
    from fastapi_admin_kit.ai.usage import AIConversation
    from fastapi_admin_kit.auth.protocol import AdminUserProtocol


class ConversationRecorder:
    """Handles persistence of conversations and messages."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_or_create(
        self,
        conversation_id: str | None,
        agent_name: str,
        user: AdminUserProtocol,
    ) -> AIConversation:
        from fastapi_admin_kit.ai.usage import AIConversation

        if conversation_id:
            from sqlalchemy import select

            result = await self.session.execute(
                select(AIConversation).where(AIConversation.id == conversation_id)
            )
            conv = result.scalar_one_or_none()
            if conv:
                return conv

        conv_id = str(uuid.uuid4())
        conv = AIConversation(
            id=conv_id,
            agent_name=agent_name,
            user_id=getattr(user, "id", None),
            user_email=getattr(user, "email", None),
        )
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def log_message(
        self,
        conv: AIConversation,
        role: str,
        content: str,
        tokens: int | None = None,
        latency_ms: int | None = None,
    ) -> None:
        from fastapi_admin_kit.ai.usage import AIMessage

        self.session.add(
            AIMessage(
                conversation_id=conv.id,
                role=role,
                content=content,
                tokens=tokens,
                latency_ms=latency_ms,
            )
        )
        await self.session.flush()

    async def log_tool_call(self, conv: AIConversation, call: ToolCallRecord) -> None:
        from fastapi_admin_kit.ai.usage import AIMessage

        self.session.add(
            AIMessage(
                conversation_id=conv.id,
                role="tool",
                tool_name=getattr(call, "name", None),
                tool_args=getattr(call, "args", None),
                tool_result=getattr(call, "result", None),
                content=str(getattr(call, "result", "")),
            )
        )
        await self.session.flush()

    async def log_error(self, conv: AIConversation, error: str) -> None:
        from fastapi_admin_kit.ai.usage import AIMessage

        self.session.add(
            AIMessage(
                conversation_id=conv.id,
                role="error",
                content=error,
                error=error,
            )
        )
        await self.session.flush()

    async def touch(
        self,
        conv: AIConversation,
        *,
        message_history: Any = None,
        tokens_delta: int = 0,
        cost_delta: float = 0.0,
    ) -> None:
        from sqlalchemy import func as sqlfunc

        conv.message_history = message_history
        conv.total_tokens = (conv.total_tokens or 0) + tokens_delta
        conv.total_cost = float(conv.total_cost or 0) + cost_delta
        conv.turn_count = (conv.turn_count or 0) + 1
        conv.last_message_at = sqlfunc.now()
        await self.session.flush()


def _with_conversation_logging(
    chat_fn: Callable[..., Awaitable[ChatResult]],
) -> Callable[..., Awaitable[ChatResult]]:
    """Wrap a chat() method to automatically log conversations and messages."""

    @wraps(chat_fn)
    async def wrapper(
        self: AIAgent,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
        conversation_id: str | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        recorder = ConversationRecorder(deps.session)
        conv = await recorder.get_or_create(
            conversation_id,
            agent_name=getattr(self, "name", "default"),
            user=deps.admin_user,
        )

        await recorder.log_message(conv, role="user", content=message)

        start = time.perf_counter()
        try:
            result = await chat_fn(self, message, deps, message_history=message_history, **kwargs)
        except Exception as exc:
            await recorder.log_error(conv, error=str(exc))
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)
        cost = getattr(self, "_compute_cost", lambda u: 0.0)(getattr(result, "usage", None))

        await recorder.log_message(
            conv,
            role="assistant",
            content=str(getattr(result, "output", "")),
            tokens=getattr(result, "usage", None) and getattr(result.usage, "total_tokens", None),
            latency_ms=latency_ms,
        )

        for call in getattr(result, "tool_calls", []):
            await recorder.log_tool_call(conv, call)

        tokens_delta = 0
        usage_obj = getattr(result, "usage", None)
        if usage_obj:
            tokens_delta = getattr(usage_obj, "total_tokens", 0) or 0

        await recorder.touch(
            conv,
            tokens_delta=tokens_delta,
            cost_delta=cost,
        )
        result.conversation_id = conv.id
        return result

    return wrapper


def _with_conversation_logging_stream(
    chat_stream_fn: Callable[..., AsyncGenerator[Any, None]],
) -> Callable[..., AsyncGenerator[Any, None]]:
    """Wrap a chat_stream() method to log conversations after stream completes."""

    @wraps(chat_stream_fn)
    async def wrapper(
        self: AIAgent,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
        conversation_id: str | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[Any, None]:
        recorder = ConversationRecorder(deps.session)
        conv = await recorder.get_or_create(
            conversation_id,
            agent_name=getattr(self, "name", "default"),
            user=deps.admin_user,
        )

        await recorder.log_message(conv, role="user", content=message)

        start = time.perf_counter()
        accumulated: list[str] = []
        try:
            async for chunk in chat_stream_fn(
                self, message, deps, message_history=message_history, **kwargs
            ):
                accumulated.append(str(chunk))
                yield chunk
        except Exception as exc:
            await recorder.log_error(conv, error=str(exc))
            raise

        latency_ms = int((time.perf_counter() - start) * 1000)
        full_content = "".join(accumulated)

        await recorder.log_message(
            conv,
            role="assistant",
            content=full_content,
            latency_ms=latency_ms,
        )

        await recorder.touch(conv)

    return wrapper


def patch_agent_with_conversation_logging(agent_cls: type[AIAgent]) -> None:
    """Apply conversation logging wrappers to an agent class's chat methods."""
    agent_cls.chat = _with_conversation_logging(agent_cls.chat)  # type: ignore[assignment]
    if hasattr(agent_cls, "chat_stream") and agent_cls.chat_stream is not None:
        agent_cls.chat_stream = _with_conversation_logging_stream(agent_cls.chat_stream)  # type: ignore[assignment]
