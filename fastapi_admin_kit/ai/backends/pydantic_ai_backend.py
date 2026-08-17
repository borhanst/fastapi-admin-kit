"""Pydantic AI backend implementation of AIAgent."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.ai.agent import (
    AIAgent,
    ChatResult,
    UsageInfo,
)
from fastapi_admin_kit.ai.backends import AIBackend, register_backend
from fastapi_admin_kit.ai.backends.repairer import (
    _CORRECTIVE_INSTRUCTION,
    _FRIENDLY_TOOL_FAILURE,
    ModelOutputRepairer,
    _extract_tool_calls,
    _looks_like_tool_failure,
    _parse_literal_function_calls,
)
from fastapi_admin_kit.ai.config import parse_cost
from fastapi_admin_kit.ai.deps import AdminDeps

__all__ = [
    "PydanticAIAgent",
    "PydanticAIBackend",
    "_looks_like_tool_failure",
    "_parse_literal_function_calls",
    "_extract_tool_calls",
    "_FRIENDLY_TOOL_FAILURE",
]

try:
    from pydantic_ai.exceptions import ModelHTTPError
except ImportError:  # pragma: no cover - pydantic-ai is an optional dependency

    class ModelHTTPError(Exception):
        pass


_TOOL_CALL_RETRY_LIMIT = 2

logger = logging.getLogger("fastapi_admin_kit.ai")

# Default repairer used when an agent is constructed without running
# ``__init__`` (e.g. unit tests that build it via ``__new__``).  Normally an
# instance gets its own :class:`ModelOutputRepairer` injected in ``__init__``.
_DEFAULT_REPAIRER = ModelOutputRepairer()

if TYPE_CHECKING:
    from pydantic_ai import Agent

    from fastapi_admin_kit.ai.config import AIAgentConfig
    from fastapi_admin_kit.ai.tools import Tool
    from fastapi_admin_kit.ai.usage import AIUsageWriter


class PydanticAIAgent(AIAgent):
    """Phase 1 implementation using Pydantic AI.

    Slimmed by the architecture review: provider output repair now lives in
    :class:`~fastapi_admin_kit.ai.backends.repairer.ModelOutputRepairer`, and
    persistence lives in :class:`~fastapi_admin_kit.ai.conversation
    .AIConversationStore`.  This class only builds the model, runs it, computes
    cost, and exposes native streaming events.
    """

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
        self._repairer = ModelOutputRepairer()
        self._build_error: str | None = None

        try:
            from pydantic_ai import Agent
        except ImportError:  # pydantic-ai itself is not installed
            self._agent = None
            return

        try:
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
        except ImportError as e:
            # A provider extra is missing (e.g. the `groq` package for Groq
            # models), NOT pydantic-ai itself. Report the real cause so the
            # user installs the right extra instead of being told pydantic-ai
            # is missing.
            self._agent = None
            self._build_error = (
                f"Could not build AI model '{config.model}': {e}. "
                "If this is a Groq/OpenAI/Anthropic/Google model, install the "
                "matching pydantic-ai provider extra, e.g. "
                '`pip install "pydantic-ai[groq]"`.'
            )
        except Exception as e:  # pragma: no cover - unexpected build failure
            self._agent = None
            self._build_error = f"Failed to build the AI agent: {e}"

    @property
    def repairer(self) -> ModelOutputRepairer:
        """The output-repair adapter (falls back to the module default)."""
        return getattr(self, "_repairer", _DEFAULT_REPAIRER)

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
                self._build_error
                or """pydantic-ai is not installed. Install with:
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
            literal_calls = self.repairer.extract_literal_calls(output)
            if literal_calls:
                output, usage, cost, tool_calls = await self.repairer.repair(
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
                if _attempt < self._tool_retry_limit and self.repairer.looks_like_failure(
                    self.repairer.model_http_error_text(err)
                ):
                    history = self._correction_history(result, history)
                    continue
                break

            output = result.output
            if isinstance(output, str) and self.repairer.looks_like_failure(output):
                if _attempt < self._tool_retry_limit:
                    history = self._correction_history(result, history)
                    continue
                return result, _FRIENDLY_TOOL_FAILURE
            return result, None

        if result is None:
            if last_err is not None and not self.repairer.looks_like_failure(
                self.repairer.model_http_error_text(last_err)
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

    def stream(
        self,
        message: str | list[Any],
        deps: AdminDeps,
        message_history: list | None = None,
        conversation_id: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream a reply as native events.

        Consumes ``pydantic_ai``'s event stream and normalises it into the
        admin kit's native events: ``delta`` events for text and a final
        ``done`` event carrying ``conversation_id``, ``output``, ``usage`` and
        the full tool-call list.  This is the real streaming seam — routes no
        longer reach into the backend via ``get_raw_agent``.  On a provider
        tool-call rejection it falls back to the (repairing) ``chat`` path and
        marks the result so the route does not double-write the usage log.
        """
        if self._agent is None:
            raise RuntimeError(
                self._build_error
                or """pydantic-ai is not installed. Install with:
                pip install pydantic-ai"""
            )

        async def _iterate() -> AsyncGenerator[dict[str, Any], None]:
            final_result: Any = None
            try:
                async with self._agent.run_stream_events(
                    user_prompt=message,
                    deps=deps,
                    message_history=message_history,
                    conversation_id=conversation_id,
                    usage_limits=self._config.usage_limits,
                    metadata=self._config.metadata,
                ) as event_stream:
                    async for event in event_stream:
                        if not hasattr(event, "event_kind"):
                            continue
                        if event.event_kind == "part_delta":
                            delta = getattr(event, "delta", None)
                            if delta is None:
                                continue
                            # Only surface *text* deltas as visible reply text.
                            # Thinking/reasoning deltas also expose
                            # ``content_delta`` but must stay hidden from the
                            # user — otherwise the model's internal reasoning
                            # ("Should respond with greeting. No tool calls.")
                            # leaks into the visible assistant message.
                            if getattr(delta, "part_delta_kind", None) != "text":
                                continue
                            if getattr(delta, "content_delta", None):
                                yield {"type": "delta", "text": delta.content_delta}
                        elif event.event_kind == "agent_run_result":
                            final_result = getattr(event, "result", None)

                if final_result is None:
                    raise RuntimeError("Agent stream ended without a final result.")

                usage = final_result.usage
                cost = self._compute_cost(usage)
                tool_calls = _extract_tool_calls(final_result)
                yield {
                    "type": "done",
                    "conversation_id": getattr(final_result, "conversation_id", None)
                    or conversation_id,
                    "output": str(getattr(final_result, "output", "")),
                    "usage": {
                        "request_tokens": getattr(usage, "request_tokens", None) or 0,
                        "response_tokens": getattr(usage, "output_tokens", None) or 0,
                        "total_tokens": getattr(usage, "total_tokens", None) or 0,
                        "cost": cost,
                    },
                    "tool_calls": [
                        {
                            "name": tc.name,
                            "args": tc.args,
                            "result": tc.result,
                            "is_error": tc.is_error,
                        }
                        for tc in tool_calls
                    ],
                    "new_messages": final_result.new_messages(),
                }
            except Exception as e:
                error_text = str(e)
                if self.repairer.looks_like_failure(error_text):
                    try:
                        fallback = await self.chat(
                            message,
                            deps,
                            message_history=message_history,
                            conversation_id=None,
                        )
                        output = str(fallback.output)
                        yield {"type": "delta", "text": output}
                        yield {
                            "type": "done",
                            "conversation_id": fallback.conversation_id,
                            "output": output,
                            "usage": {
                                "request_tokens": fallback.usage.request_tokens,
                                "response_tokens": fallback.usage.response_tokens,
                                "total_tokens": fallback.usage.total_tokens,
                                "cost": fallback.usage.cost,
                            },
                            "tool_calls": [
                                {
                                    "name": tc.name,
                                    "args": tc.args,
                                    "result": tc.result,
                                    "is_error": tc.is_error,
                                }
                                for tc in fallback.tool_calls
                            ],
                            "new_messages": fallback.new_messages,
                            "usage_recorded": True,
                        }
                        return
                    except Exception:
                        # The model could not be steered away from an invalid tool
                        # call. Surface the friendly message as a normal assistant
                        # reply (not a hard error bubble) and stop.
                        yield {"type": "delta", "text": _FRIENDLY_TOOL_FAILURE}
                        yield {
                            "type": "done",
                            "conversation_id": conversation_id,
                            "output": _FRIENDLY_TOOL_FAILURE,
                            "usage": {
                                "request_tokens": 0,
                                "response_tokens": 0,
                                "total_tokens": 0,
                                "cost": 0.0,
                            },
                            "tool_calls": [],
                            "new_messages": [],
                            "usage_recorded": True,
                        }
                        return
                # Non-tool errors (auth, rate limit, network, bad model, …) are
                # NOT tool-call rejections — surface the real cause verbatim
                # instead of the misleading tool-failure message.
                yield {"type": "error", "error": error_text}

        return _iterate()

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

    def _compute_cost(self, usage: Any) -> float:
        cfg = self._config
        in_c = parse_cost(cfg.input_cost)
        out_c = parse_cost(cfg.output_cost)
        req = (getattr(usage, "input_tokens", None) or 0) / in_c.divisor
        resp = (getattr(usage, "output_tokens", None) or 0) / out_c.divisor
        in_cost = req * in_c.amount
        out_cost = resp * out_c.amount
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
