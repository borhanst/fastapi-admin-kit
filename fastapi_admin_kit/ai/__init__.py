"""AI Agent Integration — Pydantic AI (Phase 1)."""

from fastapi_admin_kit.ai.agent import AIAgent, ChatResult, ToolCallRecord, UsageInfo
from fastapi_admin_kit.ai.config import AIAgentConfig, AIConfig
from fastapi_admin_kit.ai.tools import Tool, ToolRegistry, tool, tool_registry

__all__ = [
    "AIAgent",
    "AIAgentConfig",
    "AIConfig",
    "ChatResult",
    "Tool",
    "ToolCallRecord",
    "ToolRegistry",
    "UsageInfo",
    "tool",
    "tool_registry",
]
