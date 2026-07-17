"""Tests for AI Agent Integration (Phase 1)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi_admin_kit.ai.agent import ChatResult, ToolCallRecord, UsageInfo
from fastapi_admin_kit.ai.config import AIAgentConfig, AIConfig
from fastapi_admin_kit.ai.deps import AdminDeps
from fastapi_admin_kit.ai.tools import Tool, ToolRegistry, tool, tool_registry

# ─── UsageInfo ───


class TestUsageInfo:
    def test_defaults(self):
        u = UsageInfo()
        assert u.request_tokens == 0
        assert u.response_tokens == 0
        assert u.total_tokens == 0
        assert u.cost == 0.0

    def test_from_pydantic_ai(self):
        usage = MagicMock(request_tokens=100, response_tokens=50, total_tokens=150)
        info = UsageInfo.from_pydantic_ai(usage, cost=0.005)
        assert info.request_tokens == 100
        assert info.response_tokens == 50
        assert info.total_tokens == 150
        assert info.cost == 0.005

    def test_from_pydantic_ai_none_attrs(self):
        usage = MagicMock(request_tokens=None, response_tokens=None, total_tokens=None)
        info = UsageInfo.from_pydantic_ai(usage, cost=0.0)
        assert info.request_tokens == 0
        assert info.response_tokens == 0
        assert info.total_tokens == 0


# ─── ChatResult ───


class TestChatResult:
    def test_defaults(self):
        r = ChatResult()
        assert r.output is None
        assert r.tool_calls == []
        assert r.conversation_id is None

    def test_with_values(self):
        r = ChatResult(output="hello", usage=UsageInfo(total_tokens=100))
        assert r.output == "hello"
        assert r.usage.total_tokens == 100


# ─── ToolCallRecord ───


class TestToolCallRecord:
    def test_record(self):
        tc = ToolCallRecord(name="lookup", args={"id": 1}, result={"found": True})
        assert tc.name == "lookup"
        assert tc.args == {"id": 1}
        assert tc.is_error is False


# ─── Tool ───


class TestTool:
    def test_tool_dataclass(self):
        async def handler():
            pass

        t = Tool(name="test", description="desc", handler=handler)
        assert t.name == "test"
        assert t.uses_context is True
        assert t.category == "general"

    def test_to_schema_empty(self):
        async def handler():
            pass

        t = Tool(name="test", description="desc", handler=handler)
        assert t.to_schema() == {}


# ─── ToolRegistry ───


class TestToolRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()

        async def handler():
            pass

        reg.register("my_tool", "does stuff", handler)
        t = reg.get("my_tool")
        assert t is not None
        assert t.name == "my_tool"

    def test_get_missing(self):
        reg = ToolRegistry()
        assert reg.get("nonexistent") is None

    def test_all(self):
        reg = ToolRegistry()

        async def h1():
            pass

        async def h2():
            pass

        reg.register("a", "a tool", h1)
        reg.register("b", "b tool", h2)
        assert len(reg.all()) == 2

    def test_by_category(self):
        reg = ToolRegistry()

        async def h():
            pass

        reg.register("a", "a", h, category="db")
        reg.register("b", "b", h, category="analytics")
        assert len(reg.by_category("db")) == 1
        assert len(reg.by_category("analytics")) == 1


# ─── @tool decorator ───


class TestToolDecorator:
    def test_decorator_registers(self):
        @tool(name="decorated_tool", description="test", uses_context=False)
        async def my_func(x: int) -> int:
            return x * 2

        t = tool_registry.get("decorated_tool")
        assert t is not None
        assert t.uses_context is False
        assert t.handler is my_func
        assert getattr(my_func, "_ai_tool", False) is True


# ─── AIAgentConfig ───


class TestAIAgentConfig:
    def test_config(self):
        cfg = AIAgentConfig(name="test", model="openai:gpt-4o")
        assert cfg.name == "test"
        assert cfg.model == "openai:gpt-4o"
        assert cfg.retries == 1
        assert cfg.tools == []

    def test_get_tool(self):
        async def h():
            pass

        t = Tool(name="x", description="x", handler=h)
        cfg = AIAgentConfig(name="test", model="m", tools=[t])
        assert cfg.get_tool("x") is t
        assert cfg.get_tool("y") is None


# ─── AIConfig ───


class TestAIConfig:
    def test_defaults(self):
        cfg = AIConfig()
        assert cfg.agents == []
        assert cfg.default_agent == "default"
        assert cfg.dashboard_enabled is True
        assert cfg.log_retention_days == 30


# ─── AdminDeps ───


class TestAdminDeps:
    def test_dataclass(self):
        deps = AdminDeps(
            session=MagicMock(),
            admin_user=MagicMock(),
            request=MagicMock(),
            registry=MagicMock(),
            permission_checker=MagicMock(),
        )
        assert deps.session is not None
        assert deps.admin_user is not None
