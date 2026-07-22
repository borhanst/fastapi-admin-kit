"""AI configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi_admin_kit.ai.tools import Tool


@dataclass
class AIAgentConfig:
    """Configuration for a single AI agent.

    ``tools`` accepts a mixed list of tool names (strings) and Tool objects.
    Strings are resolved against the global :data:`tool_registry` at init time.
    """

    name: str
    model: str
    system_prompt: str = ""
    api_key: str | None = None
    result_type: type | None = None
    tools: list[str | Tool] = field(default_factory=list)
    retries: int = 1
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0

    _resolved_tools: list[Tool] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        from fastapi_admin_kit.ai.tools import Tool, tool_registry

        resolved: list[Tool] = []
        for t in self.tools:
            if isinstance(t, str):
                found = tool_registry.get(t)
                if found is None:
                    raise KeyError(
                        f"Tool '{t}' not found in registry. "
                        f"Available: {[x.name for x in tool_registry.all()]}"
                    )
                resolved.append(found)
            elif isinstance(t, Tool):
                resolved.append(t)
            else:
                raise TypeError(f"Expected str or Tool, got {type(t).__name__}")
        self._resolved_tools = resolved
        self.tools = self._resolved_tools  # type: ignore[assignment]

    def get_tool(self, name: str) -> Tool | None:
        return next((t for t in self._resolved_tools if t.name == name), None)


@dataclass
class AIConfig:
    """Top-level AI configuration for the admin panel."""

    agents: list[AIAgentConfig] = field(default_factory=list)
    default_agent: str = "default"
    dashboard_enabled: bool = True
    log_retention_days: int = 30
