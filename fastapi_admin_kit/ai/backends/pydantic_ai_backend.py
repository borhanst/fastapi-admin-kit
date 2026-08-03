"""Pydantic AI backend implementation of AIAgent."""

from __future__ import annotations

import json
import re
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
from fastapi_admin_kit.ai.errors import error_detail

if TYPE_CHECKING:
    from pydantic_ai import Agent
    from pydantic_ai.result import AgentRunResult, RunUsage, StreamedRunResult

    from fastapi_admin_kit.ai.config import AIAgentConfig
    from fastapi_admin_kit.ai.tools import Tool
    from fastapi_admin_kit.ai.usage import AIUsageWriter


_LITERAL_CALL_RE = re.compile(r"<function=(\w+)")


def _parse_literal_json_object(text: str) -> tuple[dict[str, Any] | None, int]:
    """Parse a JSON object at the start of ``text``.

    Returns ``(parsed_dict, end_index)`` or ``(None, 0)`` when no complete
    JSON object is present. Handles nested braces and strings.
    """
    stripped = text.lstrip()
    if not stripped.startswith("{"):
        return None, 0

    depth = 0
    in_string = False
    escaped = False
    for i, ch in enumerate(stripped):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(stripped[: i + 1]), i + 1
                except json.JSONDecodeError:
                    return None, 0
    return None, 0


def _parse_literal_function_calls(
    text: str,
) -> list[tuple[str, dict[str, Any], int]]:
    """Extract literal ``<function=name {json}>`` calls from model output.

    Some models (e.g. Llama via Groq) occasionally emit tool calls as plain
    text instead of using native tool calling. Returns ``(name, args, end)``
    tuples where ``end`` is the index just past the call (args + optional
    closing tag) so callers can replace the whole expression.
    """
    calls: list[tuple[str, dict[str, Any], int]] = []
    for match in _LITERAL_CALL_RE.finditer(text):
        name = match.group(1)
        after_name = text[match.end() :]
        # Skip optional `>` between name and JSON (e.g. `<function=get_ticket> {…}`).
        # Some models also emit a stray `=` / `:` before the JSON object
        # (e.g. `<function=name>={"key": value}`) or wrap it in parentheses
        # (e.g. `<function=name>({"key": value})`). Tolerate all of these.
        after_name = after_name.lstrip(">").lstrip()
        while after_name[:1] in ("=", ":", "(", ">"):
            after_name = after_name[1:].lstrip()
        args, offset = _parse_literal_json_object(after_name)
        # Consume a trailing `)` if the JSON object was wrapped in parens.
        if offset:
            while after_name[offset : offset + 1] == ")":
                offset += 1
        stripped_len = len(text[match.end() :]) - len(after_name)
        end = match.end() + stripped_len + offset
        if offset == 0:
            closing = re.match(r"\s*</function>", text[end:])
            if closing:
                end += closing.end()
        calls.append((name, args or {}, end))
    return calls


def _format_literal_call_result(result: Any) -> str:
    """Render a tool result as readable text for the chat reply."""
    try:
        return json.dumps(result, indent=2, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(result)


def _strip_literal_function_calls(text: str) -> str:
    """Remove literal ``<function=name {json}></function>`` expressions from text.

    Used after tool results have been rendered so the raw call syntax never
    leaks into the final chat reply.
    """
    return _LITERAL_CALL_RE.sub("", text).replace("</function>", "")


def _replace_literal_calls_with_results(
    text: str,
    results: list[tuple[str, dict[str, Any], Any, bool]],
    ends: list[int],
) -> str:
    """Replace each literal call in ``text`` with its executed result."""
    if not results:
        return text

    rendered: list[str] = []
    last = 0
    for idx, match in enumerate(_LITERAL_CALL_RE.finditer(text)):
        if idx >= len(results):
            break
        name, _args, result, is_error = results[idx]
        rendered.append(text[last : match.start()])
        if is_error:
            rendered.append(f"[Tool {name} failed: {result}]")
        else:
            rendered.append(_format_literal_call_result(result))
        last = max(ends[idx], match.end())
    rendered.append(text[last:])
    return "".join(rendered)


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

            self._model = self._build_model(config)
            model = self._model
            system_prompt = self._build_system_prompt(config)

            self._agent: Agent[AdminDeps, Any] | None = Agent(
                model,
                deps_type=AdminDeps,
                output_type=config.result_type or str,
                system_prompt=system_prompt,
                retries=config.retries,
            )
            self._bind_tools(config.tools)
            self._register_instructions()
        except ImportError:
            self._agent = None

    def _build_system_prompt(self, config: AIAgentConfig) -> str:
        """Build system prompt with tools list appended."""
        base = config.system_prompt or ""
        if not config.tools:
            return base

        tools_section = "\n\n## Available Tools\n\n"
        tools_section += "You have access to the following tools:\n\n"
        for t in config.tools:
            tools_section += f"- **{t.name}**: {t.description}\n"

        return base + tools_section

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

            parts = relative.split("/")
            table_name = parts[0]
            registered = ctx.deps.registry.get(table_name)
            if registered is None:
                return ""

            col_names = [c.name for c in registered.columns]
            col_types = {c.name: str(c.type) for c in registered.columns}
            cols_desc = ", ".join(f"{name} ({col_types.get(name, '?')})" for name in col_names)

            context = (
                f"The user is currently on the {registered.verbose_name} page "
                f"(table: {table_name}). "
                f"Available columns: {cols_desc}. "
                f"Use these exact table and column names when querying."
            )

            if len(parts) > 1 and parts[1]:
                record_id = parts[1]
                context += f" The user is viewing record with ID: {record_id}."

            return context

    async def chat(
        self,
        message: str,
        deps: AdminDeps,
        message_history: list | None = None,
        conversation_id: str | None = None,
    ) -> ChatResult:
        if self._agent is None:
            raise RuntimeError(
                """pydantic-ai is not installed. Install with:
                pip install pydantic-ai"""
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

        output = result.output
        if isinstance(output, str):
            literal_calls = _parse_literal_function_calls(output)
            if literal_calls:
                executed: list[tuple[str, dict[str, Any], Any, bool]] = []
                for name, args, _end in literal_calls:
                    is_error = False
                    try:
                        tool_result = await self.execute_tool(name, args, deps)
                    except Exception as e:  # noqa: BLE001
                        tool_result = error_detail(e, debug=deps.debug)
                        is_error = True
                    executed.append((name, args, tool_result, is_error))
                    tool_calls.append(
                        ToolCallRecord(
                            name=name,
                            args=args,
                            result=tool_result,
                            is_error=is_error,
                        )
                    )

                # Second LLM pass: send tool results back to the model for a
                # natural-language summary instead of inserting raw JSON.
                from pydantic_ai.messages import (
                    ModelRequest,
                    ModelResponse,
                    TextPart,
                    UserPromptPart,
                )

                # Strip the literal <function=...> calls from the assistant reply
                # so the model doesn't echo them back in the second pass.
                rendered_output = _replace_literal_calls_with_results(
                    output,
                    executed,
                    [end for _name, _args, end in literal_calls],
                )
                cleaned_output = _strip_literal_function_calls(rendered_output)

                second_history: list[Any] = list(result.all_messages())
                # The final assistant ModelResponse still contains the raw
                # literal call text; replace its text with the cleaned reply so
                # we don't feed the raw <function=...> back to the model.
                if second_history and isinstance(second_history[-1], ModelResponse):
                    last = second_history[-1]
                    second_history[-1] = ModelResponse(
                        parts=[
                            (TextPart(content=cleaned_output) if isinstance(p, TextPart) else p)
                            for p in last.parts
                        ]
                    )

                results_text = "\n\n".join(
                    (
                        f"Tool {name} returned:\n"
                        + (
                            _format_literal_call_result(tool_result)
                            if not is_error
                            else f"[Tool {name} failed: {tool_result}]"
                        )
                    )
                    for name, _args, tool_result, is_error in executed
                )
                second_history.append(
                    ModelRequest(
                        parts=[
                            UserPromptPart(
                                content=(
                                    "Below are the results of the tool calls that "
                                    "were made. Please answer the user's question in "
                                    "clear, plain natural language based on these "
                                    "results. Do NOT output any tool calls or JSON.\n\n"
                                    f"{results_text}"
                                )
                            )
                        ]
                    )
                )

                second_result: Any = None
                try:
                    second_result = await self._agent.run(
                        user_prompt="",
                        deps=deps,
                        message_history=second_history,
                    )
                    output = second_result.output
                    if isinstance(output, str):
                        output = _strip_literal_function_calls(output)
                except Exception:  # noqa: BLE001
                    if second_result is None:
                        output = cleaned_output

                if second_result is not None:
                    second_usage = second_result.usage
                    second_cost = self._compute_cost(second_usage)
                    cost += second_cost
                    usage = second_usage

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
            output=output,
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
            from pydantic_ai import RunContext, RunUsage

            ctx = RunContext(
                deps=deps,
                usage=RunUsage(),
                tool_name=tool_name,
                model=self._model,
            )
            try:
                return await tool.handler(ctx, **params)
            except TypeError as e:
                # pydantic-ai 2.21.0 may pass all args as keywords;
                # if handler expects ctx positionally, try positional call.
                if "missing 1 required positional argument" in str(e):
                    positional_params = list(params.values())
                    return await tool.handler(ctx, *positional_params)
                raise
        else:
            try:
                return await tool.handler(**params)
            except TypeError as e:
                if "missing 1 required positional argument" in str(e):
                    positional_params = list(params.values())
                    return await tool.handler(*positional_params)
                raise

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
