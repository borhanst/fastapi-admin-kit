"""Native Server-Sent Events (SSE) framing for AI streaming.

This is the admin kit's own wire protocol — no AG-UI, no Vercel AI Data
Stream. The stream is plain SSE, consumable by plain JavaScript (``fetch`` +
``ReadableStream``), Alpine.js, and htmx (``sse-connect`` / ``sse-swap``).

Events
------
``delta``
    ``data: <plain text>`` — an incremental piece of the assistant reply.
    Multi-line chunks are split across multiple ``data:`` lines (SSE joins
    them back together with ``\\n``), so newlines survive the trip intact.

``tool_call`` / ``tool_call_end``
    ``data: <json>`` — a tool call started / completed.

``tool_args``
    ``data: <json>`` — incremental tool-call arguments while a call streams.

``done``
    ``data: <json>`` — run finished. Payload carries ``conversation_id``,
    ``usage`` and the full ``tool_calls`` list. Always the last frame on a
    successful run.

``error``
    ``data: <json>`` — the run failed. ``{"error": "..."}``.
"""

from __future__ import annotations

import json


def sse_frame(name: str, data: str) -> str:
    """Format one named SSE frame, splitting ``data`` across ``data:`` lines.

    Multi-line ``data`` is safe: SSE consumers reconstruct the payload by
    joining each ``data:`` line with ``\\n`` (see the EventSource spec).
    """
    lines = data.split("\n")
    payload = "".join(f"data: {line}\n" for line in lines)
    return f"event: {name}\n{payload}\n"


def sse_delta(text: str) -> str:
    """Frame for a plain-text reply delta (newline-safe)."""
    return sse_frame("delta", text)


def sse_json(name: str, payload: dict | list) -> str:
    """Frame for a structured event whose data is JSON."""
    return sse_frame(name, json.dumps(payload, ensure_ascii=False, default=str))
