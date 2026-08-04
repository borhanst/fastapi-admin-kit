"""AIAgent protocol and ChatResult."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.messages import ModelMessage
    from pydantic_ai.settings import ModelSettings
    from pydantic_ai.usage import RunUsage

    from fastapi_admin_kit.ai.deps import AdminDeps

#: A dynamic system-prompt / instruction provider. Receives the per-run
#: ``RunContext`` (which exposes :class:`AdminDeps`) and returns the prompt
#: text to append, or ``None`` to contribute nothing.
PromptProvider = Callable[["RunContext[AdminDeps]"], str | None]

#: Resolves per-run metadata (e.g. ``{"agent": ..., "user_id": ...}``) from
#: the current run context.
MetadataProvider = Callable[["RunContext[AdminDeps]"], dict[str, object]]

#: Resolves per-request model settings from the current run context.
ModelSettingsProvider = Callable[["RunContext[AdminDeps]"], "ModelSettings"]


@dataclass
class UsageInfo:
    """Token usage and cost information."""

    request_tokens: int = 0
    response_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    @classmethod
    def from_pydantic_ai(cls, usage: RunUsage, cost: float) -> UsageInfo:
        return cls(
            request_tokens=getattr(usage, "request_tokens", None) or 0,
            response_tokens=getattr(usage, "response_tokens", None) or 0,
            total_tokens=getattr(usage, "total_tokens", None) or 0,
            cost=cost,
        )


@dataclass
class ToolCallRecord:
    """Record of a single tool call within a run."""

    name: str
    args: dict[str, Any]
    result: Any = None
    is_error: bool = False


@dataclass
class ChatResult:
    """Result returned from an agent chat call."""

    output: Any = None
    usage: UsageInfo = field(default_factory=UsageInfo)
    new_messages: list[ModelMessage] = field(default_factory=list)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    conversation_id: str | None = None


class AIAgent(ABC):
    """Provider-agnostic surface used by the dashboard and chat routes.

    Phase 1 ships exactly one implementation: PydanticAIAgent.
    """

    @abstractmethod
    async def chat(
        self,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
        conversation_id: str | None = None,
    ) -> ChatResult: ...

    @abstractmethod
    def chat_stream(
        self,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
    ) -> AsyncGenerator[Any, None]: ...

    @abstractmethod
    async def execute_tool(
        self, tool_name: str, params: dict[str, Any], deps: AdminDeps
    ) -> Any: ...

    @abstractmethod
    def get_tools(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def get_usage_stats(
        self, period: str = "day", session: Any | None = None
    ) -> dict[str, Any]: ...

    def get_raw_agent(self) -> Any | None:
        """Return the underlying backend-specific agent for streaming adapters.

        Returns ``None`` if the backend is not installed or not applicable.
        """
        return None

    def get_streaming_adapter(self) -> type | None:
        """Return the backend's streaming adapter class (e.g., VercelAIAdapter).

        Returns ``None`` if the backend doesn't support streaming.
        """
        return None
