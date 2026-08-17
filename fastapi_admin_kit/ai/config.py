"""AI configuration dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from fastapi_admin_kit.ai.agent import (
        MetadataProvider,
        ModelSettingsProvider,
        PromptProvider,
    )
    from fastapi_admin_kit.ai.tools import Tool


#: Backend identifiers understood by the AI backend registry. ``"auto"``
#: resolves to the first available backend (see ``docs/agents/``).
AIBackendName = Literal["pydantic_ai", "langchain", "auto"]


#: Token pricing unit understood by :class:`Cost`. ``"1k"`` means price per
#: 1,000 tokens; ``"1m"`` means price per 1,000,000 tokens.
CostPerUnit = Literal["1k", "1m"]


@dataclass
class Cost:
    """Token pricing for an agent.

    ``amount`` is the price and ``per`` is the token unit it applies to
    (``"1k"`` or ``"1m"``). The divisor converts raw token counts into the
    unit used for cost calculation.
    """

    amount: float
    per: CostPerUnit = "1k"

    @property
    def divisor(self) -> int:
        return 1_000_000 if self.per == "1m" else 1000


def parse_cost(value: Cost | str | float) -> Cost:
    """Normalize a cost value into a :class:`Cost`.

    Accepts:

    * a :class:`Cost` (returned unchanged),
    * a ``"amount/per"`` string (e.g. ``"0.00059/1k"``, ``"0.00079/1m"``),
    * a bare ``float`` (treated as price per 1k tokens, for backward compat).
    """
    if isinstance(value, Cost):
        return value
    if isinstance(value, str):
        amount_s, _, per = value.partition("/")
        return Cost(float(amount_s), (per or "1k"))  # type: ignore[arg-type]
    return Cost(float(value), "1k")


@dataclass
class AIAgentConfig:
    """Configuration for a single AI agent.

    ``tools`` accepts a mixed list of tool names (strings) and Tool objects.
    Strings are resolved against the global :data:`tool_registry` at init time.

    ``system_prompt`` is a static prompt string. ``system_prompt_providers``
    are dynamic, per-run instruction providers (functions from ``RunContext``
    to text) registered after the static prompt; they receive the current
    ``AdminDeps`` so they can contextualise the run.
    """

    name: str
    model: str
    backend: AIBackendName = "auto"
    system_prompt: str = ""
    system_prompt_providers: list[PromptProvider] = field(default_factory=list)
    enable_default_guardrails: bool = True
    api_key: str | None = None
    result_type: type | None = None
    tools: list[str | Tool] = field(default_factory=list)
    retries: int = 3
    input_cost: Cost | str | float = 0.0
    output_cost: Cost | str | float = 0.0
    metadata: MetadataProvider | None = None
    model_settings: ModelSettingsProvider | object | None = None
    usage_limits: object | None = None
    max_concurrency: int | None = None

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
        self.input_cost = parse_cost(self.input_cost)
        self.output_cost = parse_cost(self.output_cost)

    def get_tool(self, name: str) -> Tool | None:
        return next((t for t in self._resolved_tools if t.name == name), None)


@dataclass
class AIConfig:
    """Top-level AI configuration for the admin panel."""

    agents: list[AIAgentConfig] = field(default_factory=list)
    default_agent: str = "default"
    dashboard_enabled: bool = True
    log_retention_days: int = 30
