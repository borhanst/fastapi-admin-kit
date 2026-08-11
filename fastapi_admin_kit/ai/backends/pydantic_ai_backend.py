"""Pydantic AI backend implementation of AIAgent."""

from __future__ import annotations

import json
import logging
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
from fastapi_admin_kit.ai.backends import AIBackend, register_backend
from fastapi_admin_kit.ai.deps import AdminDeps
from fastapi_admin_kit.ai.errors import error_detail

try:
    from pydantic_ai.exceptions import ModelHTTPError
except ImportError:  # pragma: no cover - pydantic-ai is an optional dependency

    class ModelHTTPError(Exception):
        pass


# Groq (and some other providers) reject malformed tool-call arguments
# server-side with a ``tool_use_failed`` error. The raw provider message leaks
# straight to the user, so we detect it and retry with a corrective instruction
# instead of surfacing the provider's internal text.
_GROQ_TOOL_FAIL_MARKERS = (
    "failed_generation",
    "Failed to call a function",
    "tool_use_failed",
    "Tool call validation failed",
    "tool call validation failed",
)

_TOOL_CALL_RETRY_LIMIT = 2

_CORRECTIVE_INSTRUCTION = (
    "Your previous reply attempted to call a tool, but the model provider "
    "rejected the call because the arguments were not valid JSON matching "
    "the tool's schema. Do NOT write tool calls as plain text. Use the "
    "native tool-calling mechanism with strictly valid JSON arguments that "
    "match the tool's parameter schema (all required fields present, no "
    "unknown fields). If a required value is unknown, ask the user for it "
    "rather than guessing."
)

_FRIENDLY_TOOL_FAILURE = (
    "I couldn't complete that request: the model produced a tool call with "
    "invalid arguments and the provider rejected it. Please rephrase your "
    "request, include the required details (such as an ID or name), and try "
    "again."
)


def _looks_like_tool_failure(text: str) -> bool:
    """Return True when *text* looks like a provider tool-call rejection."""
    return bool(text) and any(marker in text for marker in _GROQ_TOOL_FAIL_MARKERS)


def _model_http_error_text(err: ModelHTTPError) -> str:
    """Best-effort string representation of a :class:`ModelHTTPError`."""
    body = getattr(err, "body", None)
    if body is None:
        return str(err)
    try:
        body_str = json.dumps(body, default=str)
    except TypeError:
        body_str = str(body)
    return f"{err} {body_str}"


logger = logging.getLogger("fastapi_admin_kit.ai")

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
    from fastapi.encoders import jsonable_encoder

    try:
        return json.dumps(jsonable_encoder(result), indent=2, default=str, ensure_ascii=False)
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


async def _resolve_literal_calls(
    agent: PydanticAIAgent,
    output: str,
    result: AgentRunResult[Any],
    deps: AdminDeps,
    tool_calls: list[ToolCallRecord],
    cost: float,
    usage: Any,
) -> tuple[str, Any, float, list[ToolCallRecord]]:
    """Handle legacy literal ``<function=name {json}>`` output.

    Some models (e.g. Llama via Groq) emit tool calls as plain text instead of
    using native tool calling. This executes each parsed call directly, then
    runs a second LLM pass so the reply is natural language rather than raw
    JSON. Returns ``(output, usage, cost, tool_calls)``.
    """
    executed: list[tuple[str, dict[str, Any], Any, bool]] = []
    for name, args, _end in _parse_literal_function_calls(output):
        is_error = False
        try:
            tool_result = await agent.execute_tool(name, args, deps)
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
        [end for _name, _args, end in _parse_literal_function_calls(output)],
    )
    cleaned_output = _strip_literal_function_calls(rendered_output)

    second_history: list[Any] = list(result.all_messages())
    # The final assistant ModelResponse still contains the raw literal call
    # text; replace its text with the cleaned reply so we don't feed the raw
    # <function=...> back to the model.
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

    if agent._agent is None:
        return cleaned_output, usage, cost, tool_calls

    second_result: Any = None
    try:
        second_result = await agent._agent.run(
            user_prompt="",
            deps=deps,
            message_history=second_history,
            usage_limits=agent._config.usage_limits,
            metadata=agent._config.metadata,
        )
        output = second_result.output
        if isinstance(output, str):
            output = _strip_literal_function_calls(output)
    except Exception:  # noqa: BLE001
        if second_result is None:
            output = cleaned_output

    if second_result is not None:
        second_usage = second_result.usage
        second_cost = agent._compute_cost(second_usage)
        cost += second_cost
        usage = second_usage

    return output, usage, cost, tool_calls


class PydanticAIAgent(AIAgent):
    """Phase 1 implementation using Pydantic AI."""

    _tool_retry_limit: int = _TOOL_CALL_RETRY_LIMIT

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
        self._tool_retry_limit = _TOOL_CALL_RETRY_LIMIT

        try:
            from pydantic_ai import Agent

            self._model = self._build_model(config)
            model = self._model
            system_prompt = self._build_system_prompt(config)

            agent_kwargs: dict[str, Any] = dict(
                model=model,
                deps_type=AdminDeps,
                output_type=config.result_type or str,
                system_prompt=system_prompt,
                retries=config.retries,
            )
            if config.model_settings is not None:
                agent_kwargs["model_settings"] = config.model_settings
            if config.metadata is not None:
                agent_kwargs["metadata"] = config.metadata
            if config.max_concurrency is not None:
                agent_kwargs["max_concurrency"] = config.max_concurrency

            self._agent: Agent[AdminDeps, Any] | None = Agent(**agent_kwargs)
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
                self._agent.tool(
                    t.handler,
                    name=t.name,
                    description=t.description,
                )
            else:
                self._agent.tool_plain(
                    t.handler,
                    name=t.name,
                    description=t.description,
                )

    def _register_instructions(self) -> None:
        """Register per-run instruction providers.

        Defaults (guardrails, page context, user context) compose with any
        user-supplied ``system_prompt_providers``. All receive the per-run
        ``RunContext`` so they can read the current ``AdminDeps``.
        """
        if self._agent is None:
            return

        from fastapi_admin_kit.ai.prompts import (
            guardrails,
            page_context,
            user_context,
        )

        if self._config.enable_default_guardrails:
            self._agent.instructions(guardrails)
        self._agent.instructions(page_context)
        self._agent.instructions(user_context)

        for provider in self._config.system_prompt_providers:
            self._agent.instructions(provider)

    async def chat(
        self,
        message: str | list[Any],
        deps: AdminDeps,
        message_history: list | None = None,
        conversation_id: str | None = None,
    ) -> ChatResult:
        if self._agent is None:
            raise RuntimeError(
                """pydantic-ai is not installed. Install with:
                pip install pydantic-ai"""
            )

        user_repr = getattr(deps.admin_user, "email", None) or getattr(
            deps.admin_user, "id", "anonymous"
        )
        display_message = message if isinstance(message, str) else "[multimodal input]"
        logger.info(
            "[AI Agent '%s'] Starting chat run | Model: %s | User: %s | Page: %s | Message: %r",
            self.name,
            self._config.model,
            user_repr,
            deps.page_url or "N/A",
            display_message[:100] + "..." if len(display_message) > 100 else display_message,
        )

        start = time.perf_counter()
        result, output_override = await self._run_with_tool_retries(
            message, deps, message_history, conversation_id
        )
        latency_ms = int((time.perf_counter() - start) * 1000)

        if result is None:
            # Every attempt was rejected by the provider (e.g. Groq
            # tool_use_failed). Surface a friendly message instead of the
            # raw provider error.
            logger.warning(
                "[AI Agent '%s'] All tool-call attempts failed; returning friendly fallback.",
                self.name,
            )
            await self._usage_writer.write(
                agent_name=self._config.name,
                model=str(self._config.model),
                request_tokens=0,
                response_tokens=0,
                total_tokens=0,
                cost=0.0,
                user=deps.admin_user,
                success=False,
                latency_ms=latency_ms,
                tool_calls=[],
                session=deps.session,
            )
            return ChatResult(
                output=output_override or _FRIENDLY_TOOL_FAILURE,
                usage=UsageInfo(
                    request_tokens=0,
                    response_tokens=0,
                    total_tokens=0,
                    cost=0.0,
                ),
                new_messages=[],
                tool_calls=[],
                conversation_id=conversation_id,
            )

        usage = result.usage
        cost = self._compute_cost(usage)
        tool_calls = _extract_tool_calls(result)

        output = output_override if output_override is not None else result.output
        if isinstance(output, str):
            literal_calls = _parse_literal_function_calls(output)
            if literal_calls:
                output, usage, cost, tool_calls = await _resolve_literal_calls(
                    self, output, result, deps, tool_calls, cost, usage
                )

        input_tokens = getattr(usage, "input_tokens", None) or 0
        output_tokens = getattr(usage, "output_tokens", None) or 0
        total_tokens = input_tokens + output_tokens

        # Log details of each tool call
        for tc in tool_calls:
            status = "ERROR" if tc.is_error else "OK"
            logger.info(
                "[AI Agent '%s'] Tool Call [%s] | Tool: %s | Model: %s | Args: %s",
                self.name,
                status,
                tc.name,
                self._config.model,
                tc.args,
            )

        logger.info(
            "[AI Agent '%s'] Run Completed | Model: %s | Latency: %d ms | "
            "Tokens: %d (in: %d, out: %d) | Cost: $%.6f | Tool Calls: %d",
            self.name,
            self._config.model,
            latency_ms,
            total_tokens,
            input_tokens,
            output_tokens,
            cost,
            len(tool_calls),
        )

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

    async def _run_with_tool_retries(
        self,
        message: str | list[Any],
        deps: AdminDeps,
        message_history: list | None,
        conversation_id: str | None,
    ) -> tuple[Any, str | None]:
        """Run the agent, recovering from provider tool-call rejections.

        Groq (and some other providers) reject malformed tool-call arguments
        server-side. pydantic-ai either surfaces that as a ``ModelHTTPError``
        or converts it into a final output containing the raw provider text.
        In both cases we retry with a corrective instruction appended to the
        message history. Returns ``(result, output_override)`` where
        ``output_override`` is a friendly message when every attempt failed.
        """
        result: Any = None
        last_err: Exception | None = None
        history: list | None = message_history

        for _attempt in range(self._tool_retry_limit + 1):
            try:
                result = await self._agent.run(
                    message,
                    deps=deps,
                    message_history=history,
                    conversation_id=conversation_id,
                    usage_limits=self._config.usage_limits,
                    metadata=self._config.metadata,
                )
            except ModelHTTPError as err:
                last_err = err
                if _attempt < self._tool_retry_limit and _looks_like_tool_failure(
                    _model_http_error_text(err)
                ):
                    history = self._correction_history(result, history)
                    continue
                break

            output = result.output
            if isinstance(output, str) and _looks_like_tool_failure(output):
                if _attempt < self._tool_retry_limit:
                    history = self._correction_history(result, history)
                    continue
                return result, _FRIENDLY_TOOL_FAILURE
            return result, None

        if result is None:
            if last_err is not None and not _looks_like_tool_failure(
                _model_http_error_text(last_err)
            ):
                # A non-tool-call provider error (auth, rate limit, …): let it
                # propagate so callers can handle it as before.
                raise last_err
            return None, _FRIENDLY_TOOL_FAILURE
        return result, None

    def _correction_history(self, result: Any, history: list | None) -> list:
        """Build a message history that appends a corrective instruction."""
        from pydantic_ai.messages import ModelRequest, UserPromptPart

        base: list = list(result.all_messages()) if result is not None else list(history or [])
        base.append(ModelRequest(parts=[UserPromptPart(content=_CORRECTIVE_INSTRUCTION)]))
        return base

    def chat_stream(
        self,
        message: str | list[Any],
        deps: AdminDeps,
        message_history: list | None = None,
    ) -> AsyncGenerator[StreamedRunResult[AdminDeps, Any], None]:
        if self._agent is None:
            raise RuntimeError("pydantic-ai is not installed.")

        return self._agent.run_stream(
            message,
            deps=deps,
            message_history=message_history,
            usage_limits=self._config.usage_limits,
            metadata=self._config.metadata,
        )

    async def execute_tool(self, tool_name: str, params: dict[str, Any], deps: AdminDeps) -> Any:
        tool = self._config.get_tool(tool_name)
        if tool is None:
            logger.warning(
                "[AI Agent '%s'] Tool execution failed: tool '%s' not found.",
                self.name,
                tool_name,
            )
            raise ValueError(f"Tool '{tool_name}' not found.")

        logger.info(
            "[AI Agent '%s'] Executing Tool '%s' | Model: %s | Params: %s",
            self.name,
            tool_name,
            self._config.model,
            params,
        )

        try:
            if tool.uses_context:
                from pydantic_ai import RunContext, RunUsage

                ctx = RunContext(
                    deps=deps,
                    usage=RunUsage(),
                    tool_name=tool_name,
                    model=self._model,
                )
                try:
                    res = await tool.handler(ctx, **params)
                except TypeError as e:
                    # pydantic-ai 2.21.0 may pass all args as keywords;
                    # if handler expects ctx positionally, try positional call.
                    if "missing 1 required positional argument" in str(e):
                        positional_params = list(params.values())
                        res = await tool.handler(ctx, *positional_params)
                    else:
                        raise
            else:
                try:
                    res = await tool.handler(**params)
                except TypeError as e:
                    if "missing 1 required positional argument" in str(e):
                        positional_params = list(params.values())
                        res = await tool.handler(*positional_params)
                    else:
                        raise
            logger.info("[AI Agent '%s'] Tool '%s' executed successfully.", self.name, tool_name)
            return res
        except Exception as err:
            logger.error("[AI Agent '%s'] Tool '%s' failed: %s", self.name, tool_name, err)
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

    def get_raw_agent(self) -> Any:
        """Return the underlying Pydantic AI agent for direct streaming."""
        if self._agent is None:
            raise RuntimeError("pydantic-ai is not installed.")
        return self._agent

    def _compute_cost(self, usage: RunUsage) -> float:
        cfg = self._config
        req = (getattr(usage, "input_tokens", None) or 0) / 1000
        resp = (getattr(usage, "output_tokens", None) or 0) / 1000
        in_cost = req * cfg.cost_per_1k_input_tokens
        out_cost = resp * cfg.cost_per_1k_output_tokens
        return round(in_cost + out_cost, 6)


class PydanticAIBackend(AIBackend):
    """Backend that builds :class:`PydanticAIAgent` instances.

    Registered automatically on import under the ``"pydantic_ai"`` key and
    selected by default (``AIAgentConfig.backend == "auto"``) whenever
    ``pydantic-ai`` is installed.
    """

    name = "pydantic_ai"

    def create_agent(
        self,
        config: AIAgentConfig,
        *,
        deps_factory: Callable[..., Awaitable[AdminDeps]],
        usage_writer: AIUsageWriter,
    ) -> PydanticAIAgent:
        return PydanticAIAgent(
            config=config,
            deps_factory=deps_factory,
            usage_writer=usage_writer,
        )

    def get_streaming_adapter(self, agent: AIAgent) -> type | None:
        if not isinstance(agent, PydanticAIAgent):
            raise TypeError(
                f"{self.name} backend expects a PydanticAIAgent, got {type(agent).__name__}"
            )
        return None

    def is_available(self) -> bool:
        try:
            import pydantic_ai  # noqa: F401
        except ImportError:
            return False
        return True


register_backend(PydanticAIBackend())
