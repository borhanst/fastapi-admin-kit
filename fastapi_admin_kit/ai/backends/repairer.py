"""Provider output repair — the ``ModelOutputRepairer`` adapter.

Some models (Llama/Groq) emit tool calls as literal ``<function=name {json}>``
text instead of native tool calls, and providers like Groq reject malformed
tool-call arguments server-side with a ``tool_use_failed`` error.  All of that
provider-specific string hacking used to be baked into
``PydanticAIAgent.chat`` (and a second LLM pass for literal calls).  It now
lives here, isolated behind a single adapter, so:

* a bug in ``<function=…>`` repair is fixed in one module, not across
  ``chat``/``_resolve_literal_calls``;
* the core ``chat`` path stays clean;
* repair logic is unit-testable directly, without mocking a model that emits
  malformed output.

The module-level helper functions are kept (and re-exported by
``pydantic_ai_backend``) so existing tests and imports keep working.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from fastapi_admin_kit.ai.agent import ToolCallRecord

try:
    from pydantic_ai.exceptions import ModelHTTPError
except ImportError:  # pragma: no cover - pydantic-ai is an optional dependency

    class ModelHTTPError(Exception):
        pass


if TYPE_CHECKING:
    from pydantic_ai.result import AgentRunResult, RunUsage

    from fastapi_admin_kit.ai.backends.pydantic_ai_backend import PydanticAIAgent
    from fastapi_admin_kit.ai.deps import AdminDeps


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
    from fastapi_admin_kit.ai.agent import ToolCallRecord

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
    from pydantic_ai.messages import (
        ModelRequest,
        ModelResponse,
        TextPart,
        UserPromptPart,
    )

    executed: list[tuple[str, dict[str, Any], Any, bool]] = []
    for name, args, _end in _parse_literal_function_calls(output):
        is_error = False
        try:
            tool_result = await agent.execute_tool(name, args, deps)
        except Exception as e:  # noqa: BLE001
            from fastapi_admin_kit.ai.errors import error_detail

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
        second_usage: RunUsage = second_result.usage
        second_cost = agent._compute_cost(second_usage)
        cost += second_cost
        usage = second_usage

    return output, usage, cost, tool_calls


class ModelOutputRepairer:
    """Adapter isolating provider output repair from the core run path."""

    def looks_like_failure(self, text: str) -> bool:
        return _looks_like_tool_failure(text)

    def model_http_error_text(self, err: ModelHTTPError) -> str:
        return _model_http_error_text(err)

    def extract_literal_calls(self, text: str) -> list[tuple[str, dict[str, Any], int]]:
        return _parse_literal_function_calls(text)

    async def repair(
        self,
        agent: PydanticAIAgent,
        output: str,
        result: AgentRunResult[Any],
        deps: AdminDeps,
        tool_calls: list[ToolCallRecord],
        cost: float,
        usage: Any,
    ) -> tuple[str, Any, float, list[ToolCallRecord]]:
        """Repair literal ``<function=…>`` output, running the second LLM pass.

        Returns ``(output, usage, cost, tool_calls)``.
        """
        return await _resolve_literal_calls(agent, output, result, deps, tool_calls, cost, usage)
