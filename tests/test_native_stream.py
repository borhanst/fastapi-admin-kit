"""Tests for the native SSE streaming protocol and agent.stream()."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_admin_kit.ai.ui.native import sse_delta, sse_frame, sse_json


def _deps() -> MagicMock:
    from fastapi_admin_kit.ai.deps import AdminDeps

    user = MagicMock()
    user.email = "admin@example.com"
    user.id = 1
    return AdminDeps(
        session=AsyncMock(),
        admin_user=user,
        request=MagicMock(),
        registry=MagicMock(),
        permission_checker=MagicMock(),
    )


def _make_agent() -> object:
    from fastapi_admin_kit.ai.backends.pydantic_ai_backend import PydanticAIAgent
    from fastapi_admin_kit.ai.config import AIAgentConfig

    cfg = AIAgentConfig(name="stream-test", model="test", tools=[])
    agent = PydanticAIAgent.__new__(PydanticAIAgent)
    agent._config = cfg
    agent._model = None
    from pydantic_ai import Agent

    agent._agent = Agent(
        model="test",
        deps_type=__import__("fastapi_admin_kit.ai.deps", fromlist=["AdminDeps"]).AdminDeps,
    )
    return agent


# ─── SSE framing helpers ───


class TestSSEFraming:
    def test_sse_frame_single_line(self):
        frame = sse_frame("delta", "Hello")
        assert frame == "event: delta\ndata: Hello\n\n"

    def test_sse_delta_multiline(self):
        frame = sse_delta("line one\nline two")
        assert frame == "event: delta\ndata: line one\ndata: line two\n\n"

    def test_sse_json(self):
        frame = sse_json("done", {"conversation_id": "c1", "usage": {"total_tokens": 3}})
        assert frame.startswith("event: done\n")
        assert frame.endswith("\n\n")
        data = frame.split("\n")[1][6:]
        assert json.loads(data)["conversation_id"] == "c1"

    def test_sse_json_serializes_non_json_values(self):
        frame = sse_json("done", {"when": object()})
        data = frame.split("\n")[1][6:]
        assert isinstance(json.loads(data)["when"], str)


# ─── agent.stream() ───


@pytest.mark.asyncio
async def test_stream_yields_delta_and_done_events():
    agent = _make_agent()
    events = []
    async for ev in agent.stream("Hello", _deps()):
        events.append(ev)

    types = [ev["type"] for ev in events]
    assert "delta" in types
    assert types[-1] == "done"

    done = events[-1]
    assert "conversation_id" in done
    assert done["usage"]["total_tokens"] >= 0
    assert "tool_calls" in done
    assert done["tool_calls"] == []


@pytest.mark.asyncio
async def test_stream_respects_conversation_id():
    agent = _make_agent()
    done = None
    async for ev in agent.stream("Hi", _deps(), conversation_id="conv-123"):
        if ev["type"] == "done":
            done = ev
    assert done is not None
    assert done["conversation_id"] == "conv-123"
