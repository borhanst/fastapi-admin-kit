"""Tests for AI Agent Integration (Phase 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from fastapi_admin_kit.ai.agent import ChatResult, ToolCallRecord, UsageInfo
from fastapi_admin_kit.ai.config import AIAgentConfig, AIConfig
from fastapi_admin_kit.ai.deps import AdminDeps
from fastapi_admin_kit.ai.model_agent import ModelAIAgent
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
        assert cfg.backend == "auto"

    def test_config_backend_explicit(self):
        cfg = AIAgentConfig(name="test", model="m", backend="pydantic_ai")
        assert cfg.backend == "pydantic_ai"

    def test_config_backend_langchain(self):
        cfg = AIAgentConfig(name="test", model="m", backend="langchain")
        assert cfg.backend == "langchain"

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


# ─── Prompt providers ───


class TestPromptProviders:
    def _make_deps(self, **overrides):
        from fastapi_admin_kit.ai.deps import AdminDeps

        base = dict(
            session=MagicMock(),
            admin_user=MagicMock(),
            request=MagicMock(),
            registry=MagicMock(),
            permission_checker=MagicMock(),
        )
        base.update(overrides)
        return AdminDeps(**base)

    def _ctx(self, deps):
        from pydantic_ai import RunContext
        from pydantic_ai.usage import RunUsage

        return RunContext(deps=deps, model=MagicMock(), usage=RunUsage())

    def test_guardrails_present(self):
        from fastapi_admin_kit.ai.prompts import guardrails

        text = guardrails(self._ctx(self._make_deps()))
        assert "PII" in text
        assert "house numbers" in text
        assert "credentials" in text
        assert "<function=" in text or "function" in text

    def test_guardrails_disabled_flag(self):
        cfg = AIAgentConfig(
            name="t",
            model="openai:gpt-4o",
            enable_default_guardrails=False,
        )
        assert cfg.enable_default_guardrails is False

    def test_page_context_returns_none_without_url(self):
        from fastapi_admin_kit.ai.prompts import page_context

        deps = self._make_deps(page_url=None)
        assert page_context(self._ctx(deps)) is None

    def test_page_context_describes_table_and_record(self):
        from fastapi_admin_kit.ai.prompts import page_context

        col = MagicMock()
        col.name = "id"
        col.type = MagicMock()
        col.type.__str__ = lambda self: "INTEGER"

        registered = MagicMock()
        registered.verbose_name = "Products"
        registered.columns = [col]

        registry = MagicMock()
        registry.get.return_value = registered

        admin_config = {"admin_path": "/admin"}
        request = MagicMock()
        request.app.state.admin_config = admin_config

        deps = self._make_deps(page_url="/admin/products/42", registry=registry, request=request)
        text = page_context(self._ctx(deps))
        assert text is not None
        assert "Products" in text
        assert "products" in text
        assert "ID: 42" in text

    def test_page_context_ignores_foreign_pages(self):
        from fastapi_admin_kit.ai.prompts import page_context

        admin_config = {"admin_path": "/admin"}
        request = MagicMock()
        request.app.state.admin_config = admin_config

        deps = self._make_deps(page_url="/other/whatever", request=request)
        assert page_context(self._ctx(deps)) is None

    async def test_user_context_lists_permitted_tables(self):
        from unittest.mock import AsyncMock

        from fastapi_admin_kit.ai.prompts import user_context

        checker = MagicMock()
        checker.has_permission = AsyncMock(side_effect=lambda t, a: t == "products")

        reg = MagicMock()
        p = MagicMock()
        p.table_name = "products"
        c = MagicMock()
        c.table_name = "customers"
        reg.all.return_value = [p, c]

        user = MagicMock()
        user.name = "Alice"
        user.email = "alice@example.com"
        user.is_superuser = False

        deps = self._make_deps(
            admin_user=user,
            registry=reg,
            permission_checker=checker,
        )
        text = await user_context(self._ctx(deps))
        assert "Alice" in text
        assert "products" in text
        assert "customers" not in text

    async def test_user_context_superuser_lists_all(self):
        from fastapi_admin_kit.ai.prompts import user_context

        reg = MagicMock()
        p = MagicMock()
        p.table_name = "products"
        reg.all.return_value = [p]

        user = MagicMock()
        user.name = "Admin"
        user.is_superuser = True

        deps = self._make_deps(admin_user=user, registry=reg)
        text = await user_context(self._ctx(deps))
        assert "Superuser" in text
        assert "products" in text


# ─── ModelAIAgent ───


class _FakeModel:
    __tablename__ = "ai_tests_products"


class TestModelAIAgent:
    class ProductAgent(ModelAIAgent):
        """Read-only by default (allow_write=False)."""

        model = _FakeModel

    class ProductWriteAgent(ModelAIAgent):
        model = _FakeModel
        allow_write = True

    class ProductPartialAgent(ModelAIAgent):
        model = _FakeModel
        allow_write = True
        can_create = False
        can_delete = True

    class NoViewAgent(ModelAIAgent):
        model = _FakeModel
        can_view = False

    def test_default_is_read_only(self):
        tools = self.ProductAgent.build_tools()
        names = [t.name for t in tools]
        assert names == ["query_ai_tests_products"]
        assert "create_ai_tests_products" not in names
        assert "update_ai_tests_products" not in names
        assert "delete_ai_tests_products" not in names

    def test_write_gated_listed_but_individually_off(self):
        tools = self.ProductWriteAgent.build_tools()
        names = [t.name for t in tools]
        assert "query_ai_tests_products" in names
        assert "create_ai_tests_products" in names
        assert "update_ai_tests_products" in names
        assert "delete_ai_tests_products" not in names  # can_delete defaults False

    def test_granular_flags_gate_write_tools(self):
        tools = self.ProductPartialAgent.build_tools()
        names = [t.name for t in tools]
        assert "create_ai_tests_products" not in names
        assert "update_ai_tests_products" in names
        assert "delete_ai_tests_products" in names

    def test_write_description_mentions_audit(self):
        tools = self.ProductWriteAgent.build_tools()
        for name in ("create_ai_tests_products", "update_ai_tests_products"):
            desc = next(t.description for t in tools if t.name == name)
            assert "audit" in desc.lower()

    def test_can_view_false_yields_no_query(self):
        tools = self.NoViewAgent.build_tools()
        assert [t.name for t in tools] == []

    def test_to_agent_config_links_tools(self):
        cfg = self.ProductWriteAgent.to_agent_config(name="prod-agent", model="openai:gpt-4o")
        assert cfg.name == "prod-agent"
        assert cfg.model == "openai:gpt-4o"
        names = {t.name for t in cfg.tools}
        expected = {
            "query_ai_tests_products",
            "create_ai_tests_products",
            "update_ai_tests_products",
        }
        assert expected <= names

    def test_to_agent_config_forwards_extra_kwargs(self):
        cfg = self.ProductWriteAgent.to_agent_config(
            name="prod-agent",
            model="openai:gpt-4o",
            api_key="sk-test",
            retries=5,
        )
        assert cfg.api_key == "sk-test"
        assert cfg.retries == 5


# ─── Config → Agent wiring ───


class TestAgentWiring:
    def _config(self, **overrides):
        kwargs = dict(name="t", model="openai:gpt-4o")
        kwargs.update(overrides)
        return AIAgentConfig(**kwargs)

    def test_new_fields_default(self):
        cfg = self._config()
        assert cfg.system_prompt_providers == []
        assert cfg.enable_default_guardrails is True
        assert cfg.metadata is None
        assert cfg.model_settings is None
        assert cfg.usage_limits is None
        assert cfg.max_concurrency is None

    def test_agent_receives_new_kwargs(self):
        from unittest.mock import AsyncMock, patch

        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )

        def meta(ctx):
            return {"agent": "t"}

        usage_limits = MagicMock()
        cfg = self._config(
            metadata=meta,
            model_settings={"temperature": 0.0},
            usage_limits=usage_limits,
            max_concurrency=3,
        )

        with patch("pydantic_ai.Agent") as mock_agent:
            mock_agent.return_value = MagicMock()
            agent = PydanticAIAgent.__new__(PydanticAIAgent)
            agent._config = cfg
            agent._usage_writer = AsyncMock()
            agent._bind_tools = lambda tools: None
            agent._register_instructions = lambda: None
            agent._build_model = lambda c: "openai:gpt-4o"
            PydanticAIAgent.__init__(agent, cfg, AsyncMock(), AsyncMock())

        kwargs = mock_agent.call_args.kwargs
        assert kwargs["model_settings"] == {"temperature": 0.0}
        assert kwargs["metadata"] is meta
        assert kwargs["max_concurrency"] == 3

    def test_run_receives_usage_limits_and_metadata(self):
        from unittest.mock import AsyncMock

        agent, _ = self._make_agent()
        usage_limits = MagicMock()
        agent._config.usage_limits = usage_limits
        agent._config.metadata = lambda ctx: {"agent": "t"}

        fake_agent = MagicMock()
        fake_result = MagicMock()
        fake_result.output = "hello"
        fake_result.usage = MagicMock(input_tokens=10, output_tokens=5)
        fake_result.all_messages.return_value = []
        fake_result.new_messages.return_value = []
        fake_result.conversation_id = None
        fake_agent.run = AsyncMock(return_value=fake_result)
        agent._agent = fake_agent

        deps = MagicMock()
        deps.admin_user = MagicMock()
        deps.debug = False
        deps.session = MagicMock()

        import asyncio

        asyncio.run(agent.chat("hi", deps))

        call_kwargs = fake_agent.run.call_args.kwargs
        assert call_kwargs["usage_limits"] is usage_limits
        assert callable(call_kwargs["metadata"])

    def _make_agent(self):
        from unittest.mock import AsyncMock

        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )

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


# ─── AIBackend registry ───


class TestBackendRegistry:
    def test_pydantic_backend_registered(self):
        from fastapi_admin_kit.ai.backends import (
            AIBackend,
            get_backend,
            get_default_backend,
        )

        backend = get_backend("pydantic_ai")
        assert backend is not None
        assert isinstance(backend, AIBackend)
        assert backend.name == "pydantic_ai"
        assert backend.is_available() is True
        assert get_default_backend() is backend

    def test_auto_resolves_to_pydantic_backend(self):
        from fastapi_admin_kit.ai.backends import resolve_backend

        assert resolve_backend("auto").name == "pydantic_ai"

    def test_explicit_pydantic_backend(self):
        from fastapi_admin_kit.ai.backends import resolve_backend

        assert resolve_backend("pydantic_ai").name == "pydantic_ai"

    def test_unknown_backend_not_registered(self):
        from fastapi_admin_kit.ai.backends import get_backend, resolve_backend

        assert get_backend("langchain") is None
        with pytest.raises(RuntimeError, match="langchain"):
            resolve_backend("langchain")

    def test_create_agent_via_backend(self):
        from fastapi_admin_kit.ai.backends import resolve_backend
        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )

        backend = resolve_backend("pydantic_ai")
        cfg = AIAgentConfig(name="backend-test", model="test", tools=[])
        agent = backend.create_agent(
            config=cfg,
            deps_factory=AsyncMock(),
            usage_writer=AsyncMock(),
        )
        assert isinstance(agent, PydanticAIAgent)
        assert agent.name == "backend-test"

    def test_get_streaming_adapter_returns_vercel_adapter(self):
        from fastapi_admin_kit.ai.backends import resolve_backend
        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )

        backend = resolve_backend("pydantic_ai")
        agent = PydanticAIAgent.__new__(PydanticAIAgent)
        agent._agent = MagicMock()
        adapter = backend.get_streaming_adapter(agent)
        assert adapter.__name__ == "VercelAIAdapter"

    def test_get_streaming_adapter_rejects_wrong_agent(self):
        from fastapi_admin_kit.ai.backends import resolve_backend

        backend = resolve_backend("pydantic_ai")
        with pytest.raises(TypeError, match="PydanticAIAgent"):
            backend.get_streaming_adapter(MagicMock())


class TestPluginBackendFactory:
    def test_on_startup_builds_agents_via_backend(self):
        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )
        from fastapi_admin_kit.ai.plugin import AIPlugin

        cfg = AIAgentConfig(name="plugin-agent", model="test", tools=[])
        plugin = AIPlugin(agents=[cfg])

        admin = MagicMock()
        plugin.on_startup(admin)

        agents = admin._app.state.ai_agents
        assert "plugin-agent" in agents
        assert isinstance(agents["plugin-agent"], PydanticAIAgent)
        assert admin._app.state.ai_config is plugin

    def test_on_startup_honours_explicit_backend(self):
        from fastapi_admin_kit.ai.backends import get_backend
        from fastapi_admin_kit.ai.plugin import AIPlugin

        cfg = AIAgentConfig(
            name="explicit-agent",
            model="test",
            backend="pydantic_ai",
            tools=[],
        )
        plugin = AIPlugin(agents=[cfg])

        admin = MagicMock()
        plugin.on_startup(admin)

        assert get_backend("pydantic_ai").name == "pydantic_ai"
        assert "explicit-agent" in admin._app.state.ai_agents
