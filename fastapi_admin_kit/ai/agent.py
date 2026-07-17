"""AIAgent protocol and ChatResult."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fastapi_admin_kit.ai.deps import AdminDeps


@dataclass
class UsageInfo:
    """Token usage and cost information."""

    request_tokens: int = 0
    response_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0

    @classmethod
    def from_pydantic_ai(cls, usage: Any, cost: float) -> UsageInfo:
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
    args: dict
    result: Any = None
    is_error: bool = False


@dataclass
class ChatResult:
    """Result returned from an agent chat call."""

    output: Any = None
    usage: UsageInfo = field(default_factory=UsageInfo)
    new_messages: list = field(default_factory=list)
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
    ) -> ChatResult: ...

    @abstractmethod
    def chat_stream(
        self,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
    ): ...

    @abstractmethod
    async def execute_tool(self, tool_name: str, params: dict, deps: AdminDeps) -> Any: ...

    @abstractmethod
    def get_tools(self) -> list[dict]: ...

    @abstractmethod
    async def get_usage_stats(self, period: str = "day") -> dict: ...
