"""Tests that the streaming chat path actually persists the conversation.

A preceding regression left ``final_event`` unassigned inside the streaming
generator, so ``_persist_stream_result`` was never called and streamed chats
were never saved. This module locks in that the ``done`` event triggers
persistence.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from fastapi_admin_kit.ai.service import AIChatService


class _FakeAgent:
    _config = MagicMock(model="")

    async def stream(self, message, deps, message_history=None, conversation_id=None):
        yield {"type": "delta", "text": "Hi there!"}
        yield {
            "type": "done",
            "conversation_id": "conv-1",
            "output": "Hi there!",
            "usage": {
                "request_tokens": 1,
                "response_tokens": 2,
                "total_tokens": 3,
                "cost": 0.0,
            },
            "tool_calls": [],
            "new_messages": [],
        }


class _FakeRequest:
    def __init__(self, body: dict) -> None:
        self._body = body
        self.app = MagicMock()

    async def json(self):
        return self._body


@pytest.mark.asyncio
async def test_stream_persists_conversation_on_done():
    fake_agent = _FakeAgent()
    captured: dict = {}

    async def fake_persist(self, agent_name, agent, conversation_id, user_message, done):
        captured["called"] = True
        captured["agent_name"] = agent_name
        captured["conversation_id"] = conversation_id
        captured["user_message"] = user_message
        captured["done"] = done

    request = _FakeRequest(
        {
            "trigger": "submit-message",
            "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "hi"}]}],
            "agent": "default",
            "page_url": "/",
        }
    )

    with (
        patch.object(AIChatService, "_persist_stream_result", fake_persist),
        patch("fastapi_admin_kit.ai.service._get_ai_agents", return_value={"default": fake_agent}),
        patch("fastapi_admin_kit.ai.service._resolve_user", return_value=MagicMock()),
        patch("fastapi_admin_kit.ai.service._resolve_checker", return_value=MagicMock()),
        patch("fastapi_admin_kit.ai.service.get_db_session", return_value=MagicMock()),
    ):
        svc = AIChatService(request)
        resp = await svc.stream()
        # Iterate the streaming body so the generator runs to completion.
        async for _ in resp.body_iterator:
            pass

    assert captured.get("called") is True, "streaming chat was not persisted"
    assert captured["agent_name"] == "default"
    assert captured["user_message"] == "hi"
    assert captured["done"]["output"] == "Hi there!"


@pytest.mark.asyncio
async def test_stream_does_not_persist_without_done():
    """If the stream ends in error (no ``done``), nothing should be saved."""
    fake_agent = _FakeAgent()

    async def broken_stream(self, message, deps, message_history=None, conversation_id=None):
        yield {"type": "delta", "text": "partial"}
        yield {"type": "error", "error": "boom"}

    fake_agent.stream = broken_stream.__get__(fake_agent)

    captured: dict = {}

    async def fake_persist(self, agent_name, agent, conversation_id, user_message, done):
        captured["called"] = True

    request = _FakeRequest(
        {
            "trigger": "submit-message",
            "messages": [{"id": "m1", "role": "user", "parts": [{"type": "text", "text": "hi"}]}],
            "agent": "default",
            "page_url": "/",
        }
    )

    with (
        patch.object(AIChatService, "_persist_stream_result", fake_persist),
        patch("fastapi_admin_kit.ai.service._get_ai_agents", return_value={"default": fake_agent}),
        patch("fastapi_admin_kit.ai.service._resolve_user", return_value=MagicMock()),
        patch("fastapi_admin_kit.ai.service._resolve_checker", return_value=MagicMock()),
        patch("fastapi_admin_kit.ai.service.get_db_session", return_value=MagicMock()),
    ):
        svc = AIChatService(request)
        resp = await svc.stream()
        async for _ in resp.body_iterator:
            pass

    assert captured.get("called") is not True, "error stream must not persist a reply"
