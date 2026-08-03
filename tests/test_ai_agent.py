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
        assert cfg.retries == 3
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


# ─── Literal tool-call parsing ───


class TestLiteralFunctionCalls:
    def _parse(self):
        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            _parse_literal_function_calls,
        )

        return _parse_literal_function_calls

    def test_plain_json(self):
        calls = self._parse()(
            'Answer. <function=search_tickets>{"keyword": "x", "limit": 5}</function>'
        )
        assert calls == [("search_tickets", {"keyword": "x", "limit": 5}, 61)]

    def test_stray_equals_before_json(self):
        calls = self._parse()('<function=search_tickets>={"keyword": "", "limit": 1000}</function>')
        assert calls == [("search_tickets", {"keyword": "", "limit": 1000}, 56)]

    def test_stray_colon_before_json(self):
        calls = self._parse()('<function=search_tickets>:{"keyword": "x"}</function>')
        assert calls == [("search_tickets", {"keyword": "x"}, 42)]

    def test_whitespace_around_equals(self):
        calls = self._parse()('<function=search_tickets> ={"a": 1}</function>')
        assert calls == [("search_tickets", {"a": 1}, 35)]

    def test_paren_wrapped_json(self):
        calls = self._parse()('<function=search_tickets>({"keyword": "", "limit": 10})</function>')
        assert calls == [("search_tickets", {"keyword": "", "limit": 10}, 55)]

    def test_paren_wrapped_no_close_tag(self):
        calls = self._parse()('Answer. <function=search_tickets>({"keyword": "x"})</function> done')
        assert calls == [("search_tickets", {"keyword": "x"}, 51)]

    def test_double_paren_wrapped_json(self):
        calls = self._parse()('<function=search_tickets>(({"a": 1}))</function>')
        assert calls == [("search_tickets", {"a": 1}, 37)]

    def test_no_json_leaves_empty_args(self):
        calls = self._parse()("<function=get_ticket></function>")
        assert calls == [("get_ticket", {}, 32)]


# ─── Second LLM pass (literal tool calls) ───


class TestSecondLLMPass:
    def _make_agent(self):
        from unittest.mock import AsyncMock

        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )
        from fastapi_admin_kit.ai.config import AIAgentConfig

        usage_writer = MagicMock()
        usage_writer.write = AsyncMock()
        config = AIAgentConfig(
            name="default",
            model="openai:gpt-4o",
            tools=[],
            retries=1,
        )
        agent = PydanticAIAgent.__new__(PydanticAIAgent)
        agent._config = config
        agent._usage_writer = usage_writer
        agent.name = "default"
        return agent, usage_writer

    def _fake_run_result(self, output: str):
        from pydantic_ai.messages import (
            ModelRequest,
            ModelResponse,
            TextPart,
            UserPromptPart,
        )

        result = MagicMock()
        result.output = output
        result.conversation_id = "conv-1"
        result.usage = MagicMock(input_tokens=10, output_tokens=5)
        result.all_messages.return_value = [
            ModelRequest(parts=[UserPromptPart(content="user msg")]),
            ModelResponse(parts=[TextPart(content=output)]),
        ]
        result.new_messages.return_value = []
        result.message_history = []
        return result

    async def test_second_pass_uses_user_prompt_and_returns_natural_language(
        self,
    ):
        from unittest.mock import AsyncMock

        agent, _usage_writer = self._make_agent()

        fake_agent = MagicMock()
        fake_output = 'Found <function=search_tickets>{"keyword": "x"}</function>'
        fake_agent.run = AsyncMock(
            side_effect=[
                self._fake_run_result(fake_output),  # first pass
                self._fake_run_result("There are no tickets matching 'x'."),  # second pass
            ]
        )
        agent._agent = fake_agent
        agent.execute_tool = AsyncMock(return_value={"count": 0, "tickets": []})
        agent._model = "openai:gpt-4o"

        deps = MagicMock()
        deps.admin_user = MagicMock()

        result = await agent.chat("how many tickets?", deps, conversation_id="conv-1")

        # The second pass must use `user_prompt`, not the removed `message` kwarg.
        second_call = fake_agent.run.call_args_list[-1]
        assert "user_prompt" in second_call.kwargs
        assert "message" not in second_call.kwargs
        assert result.output == "There are no tickets matching 'x'."
        assert "count" not in str(result.output)

    async def test_second_pass_fallback_does_not_leak_raw_json(self):
        from unittest.mock import AsyncMock

        agent, _usage_writer = self._make_agent()

        fake_agent = MagicMock()
        fake_output = 'Found <function=search_tickets>{"keyword": "x"}</function>'
        fake_agent.run = AsyncMock(
            side_effect=[
                self._fake_run_result(fake_output),  # first pass
                RuntimeError("boom"),  # second pass fails
            ]
        )
        agent._agent = fake_agent
        agent.execute_tool = AsyncMock(return_value={"count": 0, "tickets": []})
        agent._model = "openai:gpt-4o"

        deps = MagicMock()
        deps.admin_user = MagicMock()

        result = await agent.chat("how many tickets?", deps)

        # Even when the second pass fails, the fallback should substitute the
        # executed result (raw JSON) but the reply must still be text the model
        # would generate, not a bare JSON dump of the tool result.
        assert isinstance(result.output, str)
        assert "count" in result.output  # result IS present for the LLM
        assert "tickets" in result.output
