"""AI Agent Integration — Pydantic AI (Phase 1)."""

import fastapi_admin_kit.ai.backends  # noqa: F401  (registers built-in backends)
from fastapi_admin_kit.ai.agent import (
    AIAgent,
    ChatResult,
    ToolCallRecord,
    UsageInfo,
)
from fastapi_admin_kit.ai.config import (
    AIAgentConfig,
    AIBackendName,
    AIConfig,
    Cost,
    parse_cost,
)
from fastapi_admin_kit.ai.errors import error_detail
from fastapi_admin_kit.ai.model_agent import ModelAIAgent
from fastapi_admin_kit.ai.tools import Tool, ToolRegistry, tool, tool_registry

__all__ = [
    "AIAgent",
    "AIAgentConfig",
    "AIBackendName",
    "AIConfig",
    "ChatResult",
    "Cost",
    "ModelAIAgent",
    "Tool",
    "ToolCallRecord",
    "ToolRegistry",
    "UsageInfo",
    "error_detail",
    "parse_cost",
    "tool",
    "tool_registry",
]
