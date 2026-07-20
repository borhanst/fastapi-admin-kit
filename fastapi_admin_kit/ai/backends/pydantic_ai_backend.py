"""Pydantic AI backend implementation of AIAgent."""

from __future__ import annotations

import time
from typing import Any

from fastapi_admin_kit.ai.agent import (
    AIAgent,
    ChatResult,
    ToolCallRecord,
    UsageInfo,
)
from fastapi_admin_kit.ai.deps import AdminDeps


def _extract_tool_calls(result: Any) -> list[ToolCallRecord]:
    """Extract tool call records from a Pydantic AI run result."""
    records: list[ToolCallRecord] = []
    messages = getattr(result, "all_messages", lambda: [])()
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
        config: Any,
        deps_factory: Any,
        usage_writer: Any,
    ) -> None:
        self._config = config
        self._deps_factory = deps_factory
        self._usage_writer = usage_writer
        self.name = config.name

        try:
            from pydantic_ai import Agent

            self._agent = Agent(
                config.model,
                deps_type=AdminDeps,
                result_type=config.result_type or str,
                system_prompt=config.system_prompt,
                retries=config.retries,
            )
            self._bind_tools(config.tools)
        except ImportError:
            self._agent = None

    def _bind_tools(self, tools: list[Any]) -> None:
        if self._agent is None:
            return
        for t in tools:
            if t.uses_context:
                self._agent.tool(t.handler)
            else:
                self._agent.tool_plain(t.handler)

    async def chat(
        self,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
    ) -> ChatResult:
        if self._agent is None:
            raise RuntimeError(
                "pydantic-ai is not installed. Install with: pip install pydantic-ai"
            )

        start = time.perfgit_counter()
        result = await self._agent.run(message, deps=deps, message_history=message_history)
        latency_ms = int((time.perf_counter() - start) * 1000)

        usage = result.usage()
        cost = self._compute_cost(usage)
        tool_calls = _extract_tool_calls(result)

        await self._usage_writer.write(
            agent_name=self._config.name,
            model=str(self._config.model),
            request_tokens=getattr(usage, "request_tokens", None) or 0,
            response_tokens=getattr(usage, "response_tokens", None) or 0,
            total_tokens=getattr(usage, "total_tokens", None) or 0,
            cost=cost,
            user=deps.admin_user,
            success=True,
            latency_ms=latency_ms,
            tool_calls=[
                {"name": tc.name, "args": tc.args, "ok": tc.is_error is False} for tc in tool_calls
            ],
            session=deps.session,
        )

        return ChatResult(
            output=result.data,
            usage=UsageInfo.from_pydantic_ai(usage, cost),
            new_messages=result.new_messages(),
            tool_calls=tool_calls,
        )

    def chat_stream(self, message: str, deps: AdminDeps, message_history: list | None = None):
        if self._agent is None:
            raise RuntimeError("pydantic-ai is not installed.")

        return self._agent.run_stream(message, deps=deps, message_history=message_history)

    async def execute_tool(self, tool_name: str, params: dict, deps: AdminDeps) -> Any:
        tool = self._config.get_tool(tool_name)
        if tool is None:
            raise ValueError(f"Tool '{tool_name}' not found.")

        if tool.uses_context:
            from pydantic_ai import RunContext

            ctx = RunContext(deps=deps, retry=0, tool_name=tool_name)
            return await tool.handler(ctx, **params)
        return await tool.handler(**params)

    def get_tools(self) -> list[dict]:
        return [t.to_schema() for t in self._config.tools]

    async def get_usage_stats(self, period: str = "day") -> dict:
        return await self._usage_writer.aggregate(
            agent_name=self._config.name,
            period=period,
            session=None,
        )

    def _compute_cost(self, usage: Any) -> float:
        cfg = self._config
        req = (getattr(usage, "request_tokens", None) or 0) / 1000
        resp = (getattr(usage, "response_tokens", None) or 0) / 1000
        in_cost = req * cfg.cost_per_1k_input_tokens
        out_cost = resp * cfg.cost_per_1k_output_tokens
        return round(in_cost + out_cost, 6)
