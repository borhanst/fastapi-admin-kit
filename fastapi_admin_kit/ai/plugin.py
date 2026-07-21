"""AI Plugin — routes, nav items, and startup wiring."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter

    from fastapi_admin_kit.admin.core import Admin
    from fastapi_admin_kit.ai.agent import AIAgent
    from fastapi_admin_kit.ai.config import AIAgentConfig


class AIPlugin:
    """Plugin that adds AI agent capabilities to the admin panel."""

    name = "ai"

    def __init__(self, agents: list[AIAgentConfig] | None = None) -> None:
        self.agents = agents or []

    def get_routes(self) -> APIRouter:
        from fastapi_admin_kit.ai.dashboard import router

        return router

    def get_nav_items(self) -> list[dict[str, str]]:
        return [
            {"label": "AI Dashboard", "url": "/admin/ai/dashboard", "icon": "sparkles"},
            {"label": "AI Agents", "url": "/admin/ai/agents", "icon": "smart_toy"},
            {"label": "AI Tools", "url": "/admin/ai/tools", "icon": "build"},
            {"label": "AI Logs", "url": "/admin/ai/logs", "icon": "receipt_long"},
        ]

    def get_dashboard_widgets(self) -> list[dict[str, str]]:
        return []

    def on_startup(self, admin: Admin) -> None:
        """Initialize AI agents and store on admin state."""
        from fastapi_admin_kit.ai.backends.pydantic_ai_backend import (
            PydanticAIAgent,
        )
        from fastapi_admin_kit.ai.deps import get_admin_deps
        from fastapi_admin_kit.ai.usage import AIUsageWriter

        writer = AIUsageWriter()
        ai_agents: dict[str, AIAgent] = {}

        for cfg in self.agents:
            agent = PydanticAIAgent(
                config=cfg,
                deps_factory=get_admin_deps,
                usage_writer=writer,
            )
            ai_agents[cfg.name] = agent

        admin._app.state.ai_agents = ai_agents  # type: ignore[attr-defined]
        admin._app.state.ai_config = self  # type: ignore[attr-defined]
