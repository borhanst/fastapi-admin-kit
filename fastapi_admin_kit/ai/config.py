"""AI configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi_admin_kit.ai.tools import Tool


@dataclass
class AIAgentConfig:
    """Configuration for a single AI agent."""

    name: str
    model: str
    system_prompt: str = ""
    api_key: str | None = None
    result_type: type | None = None
    tools: list[Tool] = field(default_factory=list)
    retries: int = 1
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0

    def get_tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)


@dataclass
class AIConfig:
    """Top-level AI configuration for the admin panel."""

    agents: list[AIAgentConfig] = field(default_factory=list)
    default_agent: str = "default"
    dashboard_enabled: bool = True
    log_retention_days: int = 30
