# AI Agents — Setup

This guide covers installing and configuring the AI agent feature of FastAPI
Admin Kit, including the wire protocol it streams over.

## Installation

The AI feature ships as an extra. Pydantic AI is the built-in backend
(pinned at `>=2.21.0`); the admin kit's native SSE protocol needs no extra
runtime dependency.

```bash
pip install "fastapi-admin-kit[ai]"
```

Set your model provider key (OpenAI, Groq, Google, Anthropic, …) as an
environment variable, e.g.:

```bash
export OPENAI_API_KEY="sk-..."
export GROQ_API_KEY="gsk_..."
```

## Quick start

Create an `AIConfig` describing your agents and pass it to the `Admin`
constructor:

```python
from fastapi_admin_kit import Admin
from fastapi_admin_kit.ai import AIConfig, AIAgentConfig

ai_config = AIConfig(
    agents=[
        AIAgentConfig(
            name="default",
            model="openai:gpt-4o-mini",   # or "groq:llama-3.3-70b-versatile", …
            api_key=os.environ.get("OPENAI_API_KEY"),
            system_prompt=(
                "You are a helpful admin assistant. "
                "Use your tools to answer questions; never make up data."
            ),
            retries=3,
        ),
    ],
    default_agent="default",
    dashboard_enabled=True,
    log_retention_days=30,
)

admin = Admin(
    app=app,
    engine=engine,
    base=Base,
    title="My Admin",
    admin_path="/admin",
    secret_key=SECRET_KEY,
    ai_enabled=True,
    ai=ai_config,
)
```

See `example/example_ai.py` for a full working example.

## Agent configuration

`AIAgentConfig` supports:

| Field | Description |
| --- | --- |
| `name` | Unique agent name used in URLs and the agent selector. |
| `model` | Model spec string (`"openai:gpt-4o-mini"`, `"groq:..."`, …). |
| `backend` | `"auto"` (default) \| `"pydantic_ai"` \| `"langchain"`. `"auto"` resolves to the first available backend at startup. |
| `system_prompt` | Static system prompt string. |
| `system_prompt_providers` | Dynamic per-run instruction functions (`RunContext[AdminDeps] → str`). |
| `api_key` | Provider key (falls back to the provider's env var). |
| `tools` | List of tool names (resolved against the tool registry) and `Tool` objects. |
| `retries` | Retry count for failed tool calls. |
| `input_cost` / `output_cost` | Token pricing used for usage logs and cost dashboards. Accepts a `Cost(amount, per)` object or a `"amount/per"` string (`"1k"` or `"1m"`, e.g. `"0.00059/1k"`); a bare float is treated as per-1k. |

> **Free-tier APIs:** cost is computed purely from the `input_cost` / `output_cost`
> amounts you configure. The system does **not** know whether a model is free — if you
> pass a non-zero cost, it will be charged in the usage logs and dashboards. When using a
> free API tier, set the cost amounts to `0` (e.g. `input_cost=0`, `output_cost=0`) so
> reported costs stay at zero.
| `metadata` | Function tagging each run with tenant / user / etc. |
| `max_concurrency` | Concurrency limit for parallel tool calls. |
| `enable_default_guardrails` | Inject default guardrails, page context, and user permissions. |
| `result_type` | Typed result model, if any. |
| `model_settings` | Pydantic AI model settings overrides. |
| `usage_limits` | Optional usage limits. |

### Tools

Built-in tools (`query_database`, `create_record`, …) are registered in the
global tool registry. Register your own with the `@tool` decorator:

```python
from fastapi_admin_kit.ai import tool

@tool(description="Sum a column across all rows.")
async def sum_column(ctx: RunContext[AdminDeps], table: str, column: str) -> str:
    ...
```

## Streaming protocol (native SSE)

Replies stream over **Server-Sent Events (SSE)** using the admin kit's own
plain protocol — no AG-UI, no Vercel AI Data Stream. The backend consumes
pydantic-ai's `Agent.run_stream_events` and frames each event as an SSE frame:

```
event: delta          data: <plain text>            ← incremental reply text
event: tool_call      data: <json>                  ← tool invoked
event: tool_args      data: <json>                  ← streaming tool args
event: tool_call_end  data: <json>                  ← tool call complete
event: tool_result    data: <json>                  ← tool result
event: done           data: <json>                  ← usage + tool_calls + conversation_id
event: error          data: <json>                  ← failure
```

- `delta` payloads are **raw text** (multi-line chunks are split across
  multiple `data:` lines and rejoined with `\n` per the SSE spec), so
  consumers never need to JSON-decode the reply tokens.
- Every other event's `data` is a JSON document.
- `done` is always the final frame of a successful run and carries
  `conversation_id`, `usage` and the full `tool_calls` list.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/ai/chat/stream` | SSE chat. JSON body: `{"message", "agent", "conversation_id", "page_url"}`. Works with `fetch` + `ReadableStream` in plain JS / Alpine.js. |
| `GET` | `/ai/chat/sse` | Same protocol as query params for `EventSource` and htmx's SSE extension. |
| `GET` | `/ai/chat/htmx` | Demo page showing htmx SSE consumption. |
| `POST` | `/ai/chat` | Non-streaming single-turn chat. |
| `GET` | `/ai/conversations/{id}` | Fetch a full conversation. |
| `DELETE` | `/ai/conversations/{id}` | Delete a conversation. |
| `GET` | `/ai/agents` | Agent list page. |
| `GET` | `/ai/tools` | Tool registry page. |
| `GET` | `/ai/logs` | Usage / conversation logs. |

The `/ai/chat/*` routes are served relative to the admin path (`/admin/ai/chat`, …).

## Frontends

Three reference consumers ship with the kit:

- **Alpine.js** — `fastapi_admin_kit/templates/pages/ai/chat.html` (full page)
  and `fastapi_admin_kit/templates/partials/ai_chat_widget.html` (floating
  widget). Both parse `event:` / `data:` lines and append deltas incrementally.
- **htmx** — `fastapi_admin_kit/templates/pages/ai/chat_htmx.html` uses
  `hx-ext="sse"`, `sse-connect="/ai/chat/sse?agent=…&message=…"` and
  `sse-swap="delta"`.
- **React SDK** — `frontend/packages/fastapi-admin-kit-ui` exposes
  `nativeChat()` (fetch + SSE parser) and the `useChat` hook /
  `<AIChat>` component.

## Design notes

- `AIAgent.stream()` is backend-agnostic: it yields native event dicts, and a
  future LangChain backend can emit the same shape with no wire changes.
- A per-agent `backend` field with `"auto"` default preserves existing
  behaviour while leaving the door open for other backends.
- Superseded wire protocols: **Vercel AI Data Stream (AI SDK)** and **AG-UI**
  were previously considered/used and have been removed in favour of the
  native protocol above (no vendor dependency, simple debuggable `curl`-able
  streams, framework-agnostic consumption).
