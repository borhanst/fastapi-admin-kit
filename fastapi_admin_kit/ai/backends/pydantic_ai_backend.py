"""Pydantic AI backend implementation of AIAgent."""

from __future__ import annotations

import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.ai.agent import (
    AIAgent,
    ChatResult,
    ToolCallRecord,
    UsageInfo,
)
from fastapi_admin_kit.ai.deps import AdminDeps

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.result import AgentRunResult, RunUsage, StreamedRunResult

    from fastapi_admin_kit.ai.config import AIAgentConfig
    from fastapi_admin_kit.ai.tools import Tool
    from fastapi_admin_kit.ai.usage import AIUsageWriter


def _extract_tool_calls(result: AgentRunResult[Any]) -> list[ToolCallRecord]:
    """Extract tool call records from a Pydantic AI run result."""
    records: list[ToolCallRecord] = []
    messages = result.all_messages()
    for msg in messages:
        parts = getattr(msg, "parts", [])
        for part in parts:
            if getattr(part, "part_kind", "") == "tool-call":
                records.append(
                    ToolCallRecord(
                        name=getattr(part, "tool_name", ""),
                        args=getattr(part, "args", {}),
                    )
                )
            elif getattr(part, "part_kind", "") == "tool-return":
                if records:
                    records[-1].result = getattr(part, "content", None)
    return records


class PydanticAIAgent(AIAgent):
    """Phase 1 implementation using Pydantic AI."""

    def __init__(
        self,
        config: AIAgentConfig,
        deps_factory: Callable[..., Awaitable[AdminDeps]],
        usage_writer: AIUsageWriter,
    ) -> None:
        self._config = config
        self._deps_factory = deps_factory
        self._usage_writer = usage_writer
        self.name = config.name

        try:
            from pydantic_ai import Agent

            model = self._build_model(config)

            self._agent: Agent[AdminDeps, Any] | None = Agent(
                model,
                deps_type=AdminDeps,
                output_type=config.result_type or str,
                system_prompt=config.system_prompt,
                retries=config.retries,
            )
            self._bind_tools(config.tools)
            self._register_instructions()
        except ImportError:
            self._agent = None

    def _build_model(self, config: AIAgentConfig) -> Any:
        """Build a pydantic-ai model, injecting api_key if provided."""
        model_str = config.model

        if not config.api_key:
            return model_str

        provider_name = model_str.split(":")[0] if ":" in model_str else ""

        if provider_name == "google":
            from pydantic_ai.models.google import GoogleModel
            from pydantic_ai.providers.google import GoogleProvider

            model_name = model_str.split(":", 1)[1] if ":" in model_str else model_str
            provider = GoogleProvider(api_key=config.api_key)
            return GoogleModel(model_name, provider=provider)

        if provider_name == "openai":
            from pydantic_ai.models.openai import OpenAIModel
            from pydantic_ai.providers.openai import OpenAIProvider

            model_name = model_str.split(":", 1)[1] if ":" in model_str else model_str
            provider = OpenAIProvider(api_key=config.api_key)
            return OpenAIModel(model_name, provider=provider)

        if provider_name == "anthropic":
            from pydantic_ai.models.anthropic import AnthropicModel
            from pydantic_ai.providers.anthropic import AnthropicProvider

            model_name = model_str.split(":", 1)[1] if ":" in model_str else model_str
            provider = AnthropicProvider(api_key=config.api_key)
            return AnthropicModel(model_name, provider=provider)

        if provider_name == "groq":
            from pydantic_ai.models.groq import GroqModel
            from pydantic_ai.providers.groq import GroqProvider

            model_name = model_str.split(":", 1)[1] if ":" in model_str else model_str
            provider = GroqProvider(api_key=config.api_key)
            return GroqModel(model_name, provider=provider)

        return model_str

    def _bind_tools(self, tools: list[Tool]) -> None:
        if self._agent is None:
            return
        for t in tools:
            if t.uses_context:
                self._agent.tool(t.handler)
            else:
                self._agent.tool_plain(t.handler)

    def _register_instructions(self) -> None:
        if self._agent is None:
            return
        from pydantic_ai import RunContext

        @self._agent.instructions
        def _page_context(ctx: RunContext[AdminDeps]) -> str:
            page_url = ctx.deps.page_url
            if not page_url:
                return ""

            admin_path = "/"
            try:
                admin_path = ctx.deps.request.app.state.admin_config.get("admin_path", "/admin")
            except Exception:
                pass

            path = page_url.rstrip("/")
            if not path.startswith(admin_path):
                return ""
            relative = path[len(admin_path) :].strip("/")
            if not relative:
                return ""

            table_name = relative.split("/")[0]
            registered = ctx.deps.registry.get(table_name)
            if registered is None:
                return ""

            col_names = [c.name for c in registered.columns]
            col_types = {c.name: str(c.type) for c in registered.columns}
            cols_desc = ", ".join(f"{name} ({col_types.get(name, '?')})" for name in col_names)
            return (
                f"The user is currently on the {registered.verbose_name} page "
                f"(table: {table_name}). "
                f"Available columns: {cols_desc}. "
                f"Use these exact table and column names when querying."
            )

    async def chat(
        self,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
        conversation_id: str | None = None,
    ) -> ChatResult:
        if self._agent is None:
            raise RuntimeError(
                "pydantic-ai is not installed. Install with: pip install pydantic-ai"
            )

        start = time.perf_counter()
        result = await self._agent.run(
            message,
            deps=deps,
            message_history=message_history,
            conversation_id=conversation_id,
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        usage = result.usage
        cost = self._compute_cost(usage)
        tool_calls = _extract_tool_calls(result)

        input_tokens = getattr(usage, "input_tokens", None) or 0
        output_tokens = getattr(usage, "output_tokens", None) or 0
        total_tokens = input_tokens + output_tokens

        await self._usage_writer.write(
            agent_name=self._config.name,
            model=str(self._config.model),
            request_tokens=input_tokens,
            response_tokens=output_tokens,
            total_tokens=total_tokens,
            cost=cost,
            user=deps.admin_user,
            success=True,
            latency_ms=latency_ms,
            tool_calls=[
                {
                    "name": tc.name,
                    "args": tc.args,
                    "ok": tc.is_error is False,
                }
                for tc in tool_calls
            ],
            session=deps.session,
        )

        return ChatResult(
            output=result.output,
            usage=UsageInfo(
                request_tokens=input_tokens,
                response_tokens=output_tokens,
                total_tokens=total_tokens,
                cost=cost,
            ),
            new_messages=result.new_messages(),
            tool_calls=tool_calls,
            conversation_id=result.conversation_id,
        )

    def chat_stream(
        self,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
    ) -> AsyncGenerator[StreamedRunResult[AdminDeps, Any], None]:
        if self._agent is None:
            raise RuntimeError("pydantic-ai is not installed.")

        return self._agent.run_stream(message, deps=deps, message_history=message_history)

    async def execute_tool(self, tool_name: str, params: dict[str, Any], deps: AdminDeps) -> Any:
        tool = self._config.get_tool(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' not found.")

        if tool.uses_context:
            from pydantic_ai import RunContext

            ctx = RunContext(deps=deps, retry=0, tool_name=tool_name)
            return await tool.handler(ctx, **params)
        return await tool.handler(**params)

    def get_tools(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self._config.tools]

    async def get_usage_stats(
        self, period: str = "day", session: Any | None = None
    ) -> dict[str, Any]:
        return await self._usage_writer.aggregate(
            agent_name=self._config.name,
            period=period,
            session=session,  # type: ignore[arg-type]
        )

    def _compute_cost(self, usage: RunUsage) -> float:
        cfg = self._config
        req = (getattr(usage, "input_tokens", None) or 0) / 1000
        resp = (getattr(usage, "output_tokens", None) or 0) / 1000
        in_cost = req * cfg.cost_per_1k_input_tokens
        out_cost = resp * cfg.cost_per_1k_output_tokens
        return round(in_cost + out_cost, 6)
